"""Deterministic motion analysis shared by ref_video_breakdown.py and motion_match.py.

Everything here is fixed-rule: same video in -> same numbers and same words out.
- shot cuts: HSV histogram correlation between consecutive frames
- camera move: RANSAC similarity transform between sampled frames (pan / tilt / push-in / pull-out / handheld / static)
- people: MediaPipe PoseLandmarker (33 body points, up to 4 people) when installed, else none
- shot size: largest face height / frame height (YuNet), else torso length
- action events: rule-based words from the pose (hand height, posture, facing, travel)
"""
from __future__ import annotations

import sys
import urllib.request
import warnings
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from facekit import MODEL_DIR, log  # noqa: E402

POSE_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"
JOINTS = {  # MediaPipe indices; left/right = the PERSON's left/right
    "nose": 0, "l_shoulder": 11, "r_shoulder": 12, "l_elbow": 13, "r_elbow": 14, "l_wrist": 15, "r_wrist": 16,
    "l_hip": 23, "r_hip": 24, "l_knee": 25, "r_knee": 26, "l_ankle": 27, "r_ankle": 28,
}
JOINT_NAMES = list(JOINTS)
JOINT_IDX = [JOINTS[n] for n in JOINT_NAMES]
warnings.filterwarnings("ignore", category=RuntimeWarning)  # nanmean of all-NaN slices is expected
SAMPLE_FPS = 8.0  # analysis rate for camera/pose/energy (fixed -> deterministic)


# ---------------------------------------------------------------- video reading
def video_info(path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"cannot open video {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return {"fps": fps, "frames": n, "width": w, "height": h, "duration": n / fps if fps else 0}


def iter_frames(path, start=0.0, end=None):
    """Yield (frame_index, time_s, frame) for every frame in [start, end) - sequential decode (exact, deterministic)."""
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    first = int(round(start * fps))
    if first:
        cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    i = first
    while True:
        if end is not None and i / fps >= end:
            break
        ok, frame = cap.read()
        if not ok:
            break
        yield i, i / fps, frame
        i += 1
    cap.release()


def small(frame, width=320):
    h, w = frame.shape[:2]
    return cv2.resize(frame, (width, max(1, int(h * width / w))), interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------- shot cuts
def hsv_hist(frame):
    hsv = cv2.cvtColor(small(frame, 160), cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [16, 8, 8], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(hist, hist).flatten()


def is_cut(prev_hist, hist, prev_small, cur_small):
    corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
    diff = float(np.mean(cv2.absdiff(prev_small, cur_small)))
    return corr < 0.55 or (corr < 0.75 and diff > 40.0), round(float(corr), 3)


# ---------------------------------------------------------------- camera motion
def camera_step(prev_gray, gray):
    """Similarity transform prev->cur on background features. Returns dx, dy (fraction of width), scale, rotation deg."""
    pts = cv2.goodFeaturesToTrack(prev_gray, maxCorners=300, qualityLevel=0.01, minDistance=7)
    if pts is None or len(pts) < 12:
        return None
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, pts, None)
    good0, good1 = pts[st.flatten() == 1], nxt[st.flatten() == 1]
    if len(good0) < 12:
        return None
    m, _ = cv2.estimateAffinePartial2D(good0, good1, method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if m is None:
        return None
    w = prev_gray.shape[1]
    scale = float(np.hypot(m[0, 0], m[1, 0]))
    rot = float(np.degrees(np.arctan2(m[1, 0], m[0, 0])))
    return float(m[0, 2] / w), float(m[1, 2] / w), scale, rot


def classify_camera(steps):
    """steps: list of (dx, dy, scale, rot) between consecutive samples. Content moving left = camera panning right."""
    steps = [s for s in steps if s is not None]
    if not steps:
        return {"move": "unknown", "pan": 0, "tilt": 0, "zoom": 1, "jitter": 0}
    a = np.array(steps)
    pan, tilt = float(-a[:, 0].sum()), float(-a[:, 1].sum())
    zoom = float(np.prod(a[:, 2]))
    jitter = float(np.std(a[:, 0]) + np.std(a[:, 1]))
    moves = []
    if zoom > 1.06:
        moves.append("push-in")
    elif zoom < 0.94:
        moves.append("pull-out")
    if abs(pan) > 0.06:
        moves.append("pan right" if pan > 0 else "pan left")
    if abs(tilt) > 0.06:
        moves.append("tilt down" if tilt > 0 else "tilt up")
    if jitter > 0.012:
        moves.append("handheld shake")
    return {"move": " + ".join(moves) or "static", "pan": round(pan, 3), "tilt": round(tilt, 3),
            "zoom": round(zoom, 3), "jitter": round(jitter, 4)}


# ---------------------------------------------------------------- pose
class PoseTracker:
    """MediaPipe PoseLandmarker, one independent detection per sampled frame (tracking is done by track_people). available=False when mediapipe is not installed."""

    def __init__(self, num_poses=4):
        self.available = False
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mpp
            from mediapipe.tasks.python import vision
        except Exception as e:  # noqa: BLE001
            log(f"pose disabled (mediapipe not importable: {e}). Run scripts/setup_env.py and use the venv python.")
            return
        self.mp, self.vision = mp, vision
        p = MODEL_DIR / "pose_landmarker_full.task"
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            log("downloading pose_landmarker_full.task ...")
            urllib.request.urlretrieve(POSE_URL, p.with_suffix(".part"))
            p.with_suffix(".part").replace(p)
        self.opts = vision.PoseLandmarkerOptions(
            base_options=mpp.BaseOptions(model_asset_path=str(p)),
            running_mode=vision.RunningMode.IMAGE,  # per-frame detection: VIDEO mode locks onto one person and misses others
            num_poses=num_poses,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.lm = None
        self.available = True

    def reset(self):
        """New landmarker per shot: tracking must not carry across a cut."""
        if not self.available:
            return
        if self.lm is not None:
            self.lm.close()
        self.lm = self.vision.PoseLandmarker.create_from_options(self.opts)
        self.ts = 0

    def detect(self, frame, t_ms):
        """Returns list of (13,3) arrays [x, y, visibility] in normalised image coords, x in [0,1] of width."""
        if not self.available:
            return []
        if self.lm is None:
            self.reset()
        self.ts = max(self.ts + 1, int(t_ms))
        # MediaPipe favours the most prominent person, so search the whole frame AND its left/right 60 % halves,
        # map crop coordinates back to the full frame, and merge duplicates (same shoulder centre).
        img = small(frame, 960)
        w = img.shape[1]
        found = []
        for x0, x1 in ((0, w), (0, int(w * 0.6)), (int(w * 0.4), w)):
            rgb = cv2.cvtColor(np.ascontiguousarray(img[:, x0:x1]), cv2.COLOR_BGR2RGB)
            res = self.lm.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb))
            for person in res.pose_landmarks or []:
                arr = np.array([[(x0 + person[i].x * (x1 - x0)) / w, person[i].y, getattr(person[i], "visibility", 1.0) or 0.0]
                                for i in JOINT_IDX])
                c = body_center(arr)
                if np.isnan(c).any():
                    continue
                dup = next((k for k, f in enumerate(found)
                            if np.linalg.norm(body_center(f) - c) < max(0.06, _shoulder_width(arr))), None)
                if dup is None:
                    found.append(arr)
                elif np.nanmean(arr[:, 2]) > np.nanmean(found[dup][:, 2]):  # keep the more confident copy
                    found[dup] = arr
        return found


def body_center(p):
    """Shoulder midpoint (shoulders stay in frame in close shots, hips often do not), else hips, else any visible joint.
    Using one stable anchor avoids centre jumps when the hips leave the frame during a push-in."""
    for a, b in (("l_shoulder", "r_shoulder"), ("l_hip", "r_hip")):
        q = p[[JOINT_NAMES.index(a), JOINT_NAMES.index(b)]]
        if (q[:, 2] >= 0.5).all():
            return q[:, :2].mean(axis=0)
    pts = [q[:2] for q in p if q[2] >= 0.5]
    return np.mean(pts, axis=0) if pts else np.array([np.nan, np.nan])


def _shoulder_width(p):
    q = p[[1, 2]]
    return float(np.linalg.norm(q[0, :2] - q[1, :2])) if (q[:, 2] >= 0.5).all() else 0.0


def track_people(pose_frames):
    """pose_frames: list (per sample) of list of (13,3). Greedy nearest-centre tracking, gate scaled to body size,
    then broken tracks are re-joined. Returns tracks[n_people, n_samples, 13, 3] (NaN where unseen), numbered left->right."""
    tracks, last = [], []
    for s, people in enumerate(pose_frames):
        used = set()
        for p in sorted(people, key=lambda q: body_center(q)[0] if not np.isnan(body_center(q)[0]) else 9):
            c = body_center(p)
            gate = max(0.12, 1.5 * _shoulder_width(p))
            best, bd = None, gate
            for k, lc in enumerate(last):
                if k in used or lc is None or np.isnan(c[0]):
                    continue
                d = float(np.linalg.norm(c - lc))
                if d < bd:
                    best, bd = k, d
            if best is None:
                tracks.append({s: p})
                last.append(c)
                best = len(tracks) - 1
            else:
                tracks[best][s] = p
                last[best] = c
            used.add(best)
    # re-join: a track that starts after another one ended, near where it ended, is the same person
    merged = True
    while merged:
        merged = False
        for i in range(len(tracks)):
            for j in range(len(tracks)):
                if i == j or not tracks[i] or not tracks[j]:
                    continue
                a, b = tracks[i], tracks[j]
                if max(a) < min(b) and min(b) - max(a) <= 16:
                    if float(np.linalg.norm(body_center(a[max(a)]) - body_center(b[min(b)]))) < max(0.2, 2 * _shoulder_width(b[min(b)])):
                        a.update(b)
                        tracks[j] = {}
                        merged = True
        tracks = [t for t in tracks if t]
    n = len(pose_frames)
    # drop flickers: a "person" seen in < 25% of samples is noise
    keep = [t for t in tracks if len(t) >= max(2, int(0.25 * n))]
    keep.sort(key=lambda t: body_center(t[min(t)])[0])
    arr = np.full((len(keep), n, len(JOINT_NAMES), 3), np.nan)
    for i, t in enumerate(keep):
        for s, p in t.items():
            arr[i, s] = p
    return arr


def normalise(p):
    """Centre on body centre, scale by torso length -> comparable across framing/size. Low-visibility joints -> NaN."""
    p = p.copy()
    p[p[:, 2] < 0.5, :2] = np.nan
    c = body_center(p)
    sh = np.nanmean(p[[1, 2], :2], axis=0)
    hp = np.nanmean(p[[7, 8], :2], axis=0)
    torso = float(np.linalg.norm(sh - hp)) if not (np.isnan(sh).any() or np.isnan(hp).any()) else np.nan
    if np.isnan(torso) or torso < 1e-3:
        sw = float(np.linalg.norm(p[1, :2] - p[2, :2])) if not np.isnan(p[[1, 2], :2]).any() else np.nan
        torso = sw * 1.4 if not np.isnan(sw) else np.nan
    if np.isnan(torso) or np.isnan(c).any():
        return np.full((len(JOINT_NAMES), 2), np.nan)
    return (p[:, :2] - c) / torso


# ---------------------------------------------------------------- words from poses
def hand_level(p, side):
    w = p[JOINT_NAMES.index(f"{side}_wrist")]
    if w[2] < 0.5:
        return "out of view"
    nose, sh = p[0], np.nanmean(p[[1, 2], 1])
    hp = np.nanmean(p[[7, 8], 1]) if (p[[7, 8], 2] >= 0.5).any() else sh + 0.25
    y = w[1]
    if nose[2] >= 0.5 and y < nose[1] - 0.6 * abs(sh - nose[1]):
        return "above head"
    if nose[2] >= 0.5 and y < (nose[1] + sh) / 2:
        return "face level"
    if y < sh + 0.35 * (hp - sh):
        return "shoulder/chest"
    if y < hp - 0.05 * (hp - sh):
        return "stomach"
    if y < hp + 0.35 * (hp - sh):
        return "waist/hip"
    return "down by the leg"


def posture(p):
    v = p[:, 2] >= 0.5
    li, ri, lk, rk, la, ra = (JOINT_NAMES.index(n) for n in ("l_hip", "r_hip", "l_knee", "r_knee", "l_ankle", "r_ankle"))
    sh_y = np.nanmean(np.where(v[[1, 2]], p[[1, 2], 1], np.nan))
    hip_y = np.nanmean(np.where(v[[li, ri]], p[[li, ri], 1], np.nan))
    if np.isnan(hip_y) or np.isnan(sh_y):
        return "upper body only"
    torso = abs(hip_y - sh_y)
    knee_y = np.nanmean(np.where(v[[lk, rk]], p[[lk, rk], 1], np.nan))
    if abs(np.nanmean(p[[1, 2], 0]) - np.nanmean(p[[li, ri], 0])) > 1.2 * torso:
        return "lying / bent over"
    if np.isnan(knee_y):
        return "upper body only"
    if knee_y - hip_y < 0.35 * torso:
        ank_y = np.nanmean(np.where(v[[la, ra]], p[[la, ra], 1], np.nan))
        return "crouching" if not np.isnan(ank_y) and ank_y - knee_y < 0.6 * torso else "sitting"
    return "standing"


def facing(p):
    ls, rs, nose = p[1], p[2], p[0]
    if ls[2] < 0.5 or rs[2] < 0.5:
        return "unknown"
    torso = np.nanmean(p[[7, 8], 1]) - np.nanmean(p[[1, 2], 1]) if (p[[7, 8], 2] >= 0.5).all() else 0.3
    width = abs(ls[0] - rs[0]) / max(abs(torso), 1e-3)
    if nose[2] < 0.3:
        return "back to camera"
    mid = (ls[0] + rs[0]) / 2
    off = (nose[0] - mid) / max(abs(ls[0] - rs[0]), 1e-3)
    if width < 0.35:
        return "profile " + ("facing screen-right" if off > 0 else "facing screen-left")
    if abs(off) > 0.25:
        return "three-quarter " + ("toward screen-right" if off > 0 else "toward screen-left")
    return "facing camera"


def describe_track(track, times, min_hold=2):
    """Rule-based event list for one person. Emits a change only when the new state holds for min_hold samples."""
    feats = {"posture": posture, "facing": facing,
             "right hand": lambda p: hand_level(p, "r"), "left hand": lambda p: hand_level(p, "l")}
    events = []
    unknown = {"upper body only", "unknown", "out of view"}  # "can't see" is not an action: never an event
    for name, fn in feats.items():
        states = [fn(track[i]) if not np.isnan(track[i][:, 0]).all() else None for i in range(len(times))]
        states = [None if s in unknown else s for s in states]
        cur, since = None, None
        for i, s in enumerate(states):
            if s is None:
                continue
            if cur is None:
                cur = s
                events.append((times[i], f"{name}: {s}"))
                continue
            if s != cur:
                if all(states[j] == s for j in range(i, min(len(states), i + min_hold))):
                    events.append((times[i], f"{name}: {cur} -> {s}"))
                    cur = s
    centers = [body_center(track[i]) for i in range(len(times))]
    seen = [(times[i], c) for i, c in enumerate(centers) if not np.isnan(c).any()]
    if len(seen) >= 2:
        dx = seen[-1][1][0] - seen[0][1][0]
        dy = seen[-1][1][1] - seen[0][1][1]
        if abs(dx) > 0.08:
            events.append((seen[-1][0], f"travels {'screen-right' if dx > 0 else 'screen-left'} by {abs(dx):.2f} of frame width"))
        if abs(dy) > 0.08:
            events.append((seen[-1][0], f"moves {'down/closer' if dy > 0 else 'up/away'} in frame by {abs(dy):.2f} of frame height"))
    events.sort(key=lambda e: e[0])
    return [{"t": round(float(t), 2), "event": e} for t, e in events]


def screen_position(x):
    return "left third" if x < 0.36 else ("right third" if x > 0.64 else "centre")


def shot_size(face_ratio=None, torso_ratio=None):
    r = face_ratio
    if r is not None and r > 0:
        if r > 0.45:
            return "extreme close-up"
        if r > 0.25:
            return "close-up"
        if r > 0.15:
            return "medium close-up"
        if r > 0.08:
            return "medium shot"
        if r > 0.04:
            return "medium-wide shot"
        return "wide shot"
    if torso_ratio is not None and torso_ratio > 0:
        if torso_ratio > 0.45:
            return "medium close-up"
        if torso_ratio > 0.25:
            return "medium shot"
        if torso_ratio > 0.12:
            return "medium-wide shot"
        return "wide shot"
    return "unknown"


SIZE_ORDER = ["extreme close-up", "close-up", "medium close-up", "medium shot", "medium-wide shot", "wide shot"]


# ---------------------------------------------------------------- one-shot analysis
def analyse_segment(path, start, end, pose: PoseTracker, face_kit=None, sample_fps=SAMPLE_FPS, keep_frames=None):
    """Analyse [start, end) of a video as ONE shot. Returns dict with arrays (times, energy, camera, tracks) + summary.
    keep_frames: optional list to receive (time, full-res frame) at the sampled times."""
    info = video_info(path)
    step = max(1, int(round(info["fps"] / sample_fps)))
    pose.reset()
    times, energy, cam_steps, pose_frames, face_ratios = [], [], [], [], []
    prev_gray = None
    k = 0
    for i, t, frame in iter_frames(path, start, end):
        if k % step == 0:
            sm = small(frame, 320)
            gray = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                cam_steps.append(camera_step(prev_gray, gray))
                energy.append(float(np.mean(cv2.absdiff(prev_gray, gray))))
            else:
                energy.append(0.0)
            prev_gray = gray
            times.append(round(t, 3))
            pose_frames.append(pose.detect(frame, t * 1000))
            if face_kit is not None and len(times) % 4 == 1:
                faces = face_kit.faces(frame, max_side=960)
                if faces:
                    face_ratios.append(max(f["box"][3] for f in faces) / frame.shape[0])
            if keep_frames is not None:
                keep_frames.append((t, frame))
        k += 1
    tracks = track_people(pose_frames) if pose.available else np.zeros((0, len(times), len(JOINT_NAMES), 3))
    torso_ratio = None
    if len(tracks):
        tr = []
        for p in tracks.reshape(-1, len(JOINT_NAMES), 3):
            if not np.isnan(p).any() and (p[[1, 2, 7, 8], 2] >= 0.5).all():
                tr.append(abs(np.mean(p[[7, 8], 1]) - np.mean(p[[1, 2], 1])))
        torso_ratio = float(np.median(tr)) if tr else None
    face_ratio = float(np.median(face_ratios)) if face_ratios else None
    cam = classify_camera(cam_steps)
    people = []
    for n in range(len(tracks)):
        xs = [body_center(tracks[n, s])[0] for s in range(len(times))]
        xs = [x for x in xs if not np.isnan(x)]
        people.append({
            "id": f"P{n + 1}",
            "position": screen_position(float(np.median(xs))) if xs else "unknown",
            "x_start": round(xs[0], 3) if xs else None, "x_end": round(xs[-1], 3) if xs else None,
            "events": describe_track(tracks[n], times),
        })
    # pose speed = mean normalised joint displacement per second (how violent the action is)
    speeds = []
    for n in range(len(tracks)):
        nz = np.array([normalise(tracks[n, s]) for s in range(len(times))])
        d = np.linalg.norm(np.diff(nz, axis=0), axis=2)
        if np.isfinite(d).any():
            speeds.append(float(np.nanmean(d)) * sample_fps)
    duration = (times[-1] - times[0] + 1 / info["fps"]) if times else 0
    return {
        "start": round(start, 3), "end": round(end if end is not None else start + duration, 3),
        "duration": round(duration, 2), "times": times, "energy": energy, "camera": cam,
        "shot_size": shot_size(face_ratio, torso_ratio), "face_ratio": round(face_ratio, 3) if face_ratio else None,
        "people": people, "people_count": len(tracks), "pose_speed": round(max(speeds), 3) if speeds else None,
        "tracks": tracks, "pose_available": pose.available, "cam_steps": cam_steps, "fps": info["fps"],
    }


def risk(shot):
    """Fixed rules: how hard is this shot for Flow. Reasons are shown to the user before generating."""
    reasons = []
    if shot["duration"] < 1.5:
        reasons.append("very short shot (fast cutting)")
    if shot["people_count"] > 2:
        reasons.append(f"{shot['people_count']} people in frame")
    if shot.get("pose_speed") and shot["pose_speed"] > 1.5:
        reasons.append("fast body movement")
    if "handheld" in shot["camera"]["move"] or abs(shot["camera"]["pan"]) > 0.4:
        reasons.append("fast or shaky camera")
    if shot["shot_size"] in ("wide shot", "medium-wide shot"):
        reasons.append("faces small in frame (identity is harder)")
    if any("travels" in e["event"] for p in shot["people"] for e in p["events"]):
        reasons.append("people travel across the frame")
    level = "high" if len(reasons) >= 3 else ("medium" if reasons else "low")
    return {"level": level, "reasons": reasons}
