"""Shared ffmpeg engine for assemble.py and edit_video.py: frame-accurate cutting/joining with audio kept in sync,
probing, loudness measurement and two-pass loudness normalisation. Pure ffmpeg + numpy (skill venv).

A film is rendered from PARTS. Each part is one of:
  {"file": path, "in": s, "out": s, "speed": 1.0}          a piece of a video file (speed 0.25-4)
  {"freeze": path, "at": s, "dur": s}                         one frame of a video held for dur seconds (silent)
  {"image": path, "dur": s}                                   a still image shown for dur seconds (silent)
All parts are scaled/padded to one size, one fps, 48 kHz stereo audio (silence where a part has none), then joined.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

FPS = 24
AR = 48000


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH (Windows: winget install Gyan.FFmpeg)")
    return exe


def run(args, cwd=None):
    p = subprocess.run([ffmpeg(), "-hide_banner", "-nostdin", *args], capture_output=True, text=True, cwd=cwd,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + p.stderr[-3000:])
    return p.stderr


def probe(path) -> dict:
    exe = shutil.which("ffprobe")
    out = subprocess.run([exe, "-v", "error", "-show_entries",
                          "format=duration:stream=codec_type,width,height,r_frame_rate,sample_rate,channels",
                          "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8")
    d = json.loads(out.stdout or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    fps = None
    if v and v.get("r_frame_rate") and v["r_frame_rate"] != "0/0":
        n, m = v["r_frame_rate"].split("/")
        fps = float(n) / float(m)
    return {"duration": float(d.get("format", {}).get("duration", 0) or 0), "has_video": v is not None,
            "has_audio": a is not None, "width": v.get("width") if v else None, "height": v.get("height") if v else None,
            "fps": fps}


def even(x: int) -> int:
    return int(x) // 2 * 2


def part_duration(p) -> float:
    if "file" in p:
        return (p["out"] - p["in"]) / p.get("speed", 1.0)
    return float(p["dur"])


def atempo_chain(speed: float) -> str:
    """atempo accepts 0.5-2.0 per stage; chain stages for other factors."""
    stages, s = [], speed
    while s > 2.0:
        stages.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        stages.append("atempo=0.5")
        s /= 0.5
    stages.append(f"atempo={s:.6f}")
    return ",".join(stages)


def render_parts(parts, out, width, height, fps=FPS, crf=16, preset="medium"):
    """Join parts into one H.264/AAC file. Returns the output duration (seconds)."""
    if not parts:
        raise ValueError("nothing to render")
    inputs, index, chains, labels = [], {}, [], []
    norm = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},format=yuv420p")
    aform = f"aresample={AR},aformat=sample_fmts=fltp:channel_layouts=stereo"

    def add_input(path, extra=()):
        key = (str(path), tuple(extra))
        if key not in index:
            index[key] = len(index)          # ffmpeg numbers INPUT FILES, not command-line items
            inputs.extend([*extra, "-i", str(path)])
        return index[key]

    for i, p in enumerate(parts):
        dur = part_duration(p)
        if dur <= 0:
            raise ValueError(f"part {i} has no length: {p}")
        if "file" in p:
            k = add_input(p["file"])
            sp = float(p.get("speed", 1.0))
            chains.append(f"[{k}:v]trim=start={p['in']:.6f}:end={p['out']:.6f},setpts=(PTS-STARTPTS)/{sp:.6f},{norm}[v{i}]")
            if probe(p["file"])["has_audio"] and not p.get("mute"):
                chains.append(f"[{k}:a]atrim=start={p['in']:.6f}:end={p['out']:.6f},asetpts=PTS-STARTPTS,"
                              f"{atempo_chain(sp) + ',' if abs(sp - 1) > 1e-6 else ''}{aform},apad,atrim=duration={dur:.6f}[a{i}]")
            else:
                chains.append(f"anullsrc=r={AR}:cl=stereo,atrim=duration={dur:.6f},{aform}[a{i}]")
        elif "freeze" in p:
            k = add_input(p["freeze"])
            chains.append(f"[{k}:v]trim=start={p['at']:.6f}:duration={1 / fps + 1e-4:.6f},setpts=PTS-STARTPTS,{norm},"
                          f"tpad=stop_mode=clone:stop_duration={dur:.6f},trim=duration={dur:.6f}[v{i}]")
            chains.append(f"anullsrc=r={AR}:cl=stereo,atrim=duration={dur:.6f},{aform}[a{i}]")
        elif "image" in p:
            k = add_input(p["image"], ("-loop", "1", "-t", f"{dur + 0.5:.3f}"))
            chains.append(f"[{k}:v]{norm},trim=duration={dur:.6f},setpts=PTS-STARTPTS[v{i}]")
            chains.append(f"anullsrc=r={AR}:cl=stereo,atrim=duration={dur:.6f},{aform}[a{i}]")
        else:
            raise ValueError(f"unknown part {p}")
        labels.append(f"[v{i}][a{i}]")
    graph = ";".join(chains) + ";" + "".join(labels) + f"concat=n={len(parts)}:v=1:a=1[v][a]"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    run(["-y", *inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", preset,
         "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", str(AR),
         "-movflags", "+faststart", str(out)])
    return probe(out)["duration"]


def loudness(path) -> dict:
    """Integrated loudness (LUFS), true peak (dBTP) and loudness range of a file's audio."""
    err = run(["-i", str(path), "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
    if not m:
        raise RuntimeError("loudness measurement failed")
    d = json.loads(m[-1])
    return {"lufs": float(d["input_i"]), "true_peak": float(d["input_tp"]), "lra": float(d["input_lra"]),
            "thresh": float(d["input_thresh"]), "offset": float(d["target_offset"])}


def loudnorm_filter(path_or_measure, target=-14.0, tp=-1.5, lra=11.0) -> str:
    """Second pass of a two-pass loudnorm (linear, exact) built from a first-pass measurement."""
    m = path_or_measure if isinstance(path_or_measure, dict) else loudness(path_or_measure)
    if not all(math.isfinite(m[k]) for k in ("lufs", "true_peak", "lra", "thresh", "offset")):
        return f"loudnorm=I={target}:TP={tp}:LRA={lra}"
    return (f"loudnorm=I={target}:TP={tp}:LRA={lra}:measured_I={m['lufs']}:measured_TP={m['true_peak']}:"
            f"measured_LRA={m['lra']}:measured_thresh={m['thresh']}:offset={m['offset']}:linear=true")


# ------------------------------------------------------------------ deterministic continuity & cut-seam audits
def decode_rgb(path, clip_in: float = 0.0, clip_out: float | None = None, w: int = 160, h: int = 90) -> tuple[np.ndarray, float]:
    """Decode video segment [clip_in, clip_out] as (N, H, W, 3) uint8 RGB frames."""
    info = probe(path)
    fps = float(info["fps"] or FPS)
    vf = []
    if clip_in > 0 or clip_out is not None:
        t_args = [f"start={clip_in:.6f}"] if clip_in > 0 else []
        if clip_out is not None:
            t_args.append(f"end={clip_out:.6f}")
        vf.append("trim=" + ":".join(t_args) + ",setpts=PTS-STARTPTS")
    vf.append(f"scale={w}:{h}")
    p = subprocess.run(
        [ffmpeg(), "-v", "error", "-i", str(path), "-vf", ",".join(vf), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    )
    if p.returncode != 0:
        raise RuntimeError("ffmpeg decode failed:\n" + p.stderr.decode("utf-8", errors="replace")[-1200:])
    fb = w * h * 3
    usable = (len(p.stdout) // fb) * fb
    frames = np.frombuffer(p.stdout[:usable], dtype=np.uint8).reshape(-1, h, w, 3).copy()
    return frames, fps


def analyze_frames(
    frames: np.ndarray,
    fps: float,
    file_path: str | Path,
    clip_in: float = 0.0,
    jump_mae: float = 12.0,
    tail_sec: float = 0.6,
) -> dict:
    """Detect sudden frame-to-frame jumps, tail snaps, and pure-black opening frames."""
    n = int(len(frames))
    dur = n / fps if fps > 0 else 0.0
    dark_first = bool(n > 0 and float(frames[0].mean()) < 5.0)
    if n < 2:
        return {"file": str(file_path), "frames": n, "fps": round(fps, 3), "duration": round(dur, 4),
                "dark_first_frame": dark_first, "median_mae": 0.0, "max_mae": 0.0,
                "jumps": [], "tail_jumps": [], "recommended_trim_out": None}
    diffs = np.mean(np.abs(frames[1:].astype(np.float32) - frames[:-1].astype(np.float32)), axis=(1, 2, 3))
    jumps, tail_jumps = [], []
    for idx in range(len(diffs)):
        val = float(diffs[idx])
        if val >= jump_mae:
            bad_frame = idx + 1
            t_local = bad_frame / fps
            entry = {"frame": bad_frame, "t": round(clip_in + t_local, 4), "mae": round(val, 2)}
            jumps.append(entry)
            if dur - t_local <= tail_sec + 1e-6:
                tail_jumps.append(entry)
    rec_out = round(clip_in + tail_jumps[0]["frame"] / fps, 4) if tail_jumps else None
    return {
        "file": str(file_path), "frames": n, "fps": round(fps, 3), "duration": round(dur, 4),
        "dark_first_frame": dark_first, "median_mae": round(float(np.median(diffs)), 2),
        "max_mae": round(float(np.max(diffs)), 2),
        "jumps": jumps, "tail_jumps": tail_jumps, "recommended_trim_out": rec_out,
    }


def scan_clip_jumps(
    path, clip_in: float = 0.0, clip_out: float | None = None, jump_mae: float = 12.0, tail_sec: float = 0.6
) -> dict:
    """Decode one clip window and report internal jumps, tail snaps, and recommended trim."""
    frames, fps = decode_rgb(path, clip_in=clip_in, clip_out=clip_out)
    return analyze_frames(frames, fps, path, clip_in=clip_in, jump_mae=jump_mae, tail_sec=tail_sec)


def classify_seam(seam_mae: float) -> str:
    if seam_mae < 6.0:
        return "frame_locked"
    if seam_mae < 12.0:
        return "soft_match"
    return "cut"


def resolve_seg_bounds(s: dict) -> tuple[str | None, float, float | None]:
    path = s.get("file") or s.get("clip")
    raw_in = s.get("in") if s.get("in") is not None else s.get("clip_in")
    raw_out = s.get("out") if s.get("out") is not None else s.get("clip_out")
    c_in = float(raw_in) if raw_in is not None else 0.0
    c_out = float(raw_out) if raw_out is not None else None
    return path, c_in, c_out


def audit_segments(
    segs: list[dict], bridged_scenes: set | None = None, jump_mae: float = 12.0, tail_sec: float = 0.6
) -> dict:
    """Measure boundary seam MAE across sequential segments and scan each segment for internal/tail jumps."""
    bridged = bridged_scenes or set()
    decoded, clip_jumps = [], []
    t_acc = 0.0
    for s in segs:
        path, c_in, c_out = resolve_seg_bounds(s)
        if not path or not Path(path).exists():
            continue
        is_image = s.get("kind") == "image"
        if not is_image and c_out is not None and c_out - c_in <= 1e-6:
            continue
        frames, fps = decode_rgb(path, clip_in=(0.0 if is_image else c_in), clip_out=(None if is_image else c_out))
        if len(frames) == 0:
            continue
        rep = analyze_frames(frames, fps, path, clip_in=c_in, jump_mae=jump_mae, tail_sec=tail_sec)
        rep["scene"] = s.get("scene")
        sp = float(s.get("speed") or 1.0)
        seg_dur = (c_out - c_in) / sp if c_out is not None else rep["duration"]
        cut_t = float(s["film_end"]) if s.get("film_end") is not None else round(t_acc + seg_dur, 4)
        decoded.append({
            "scene": s.get("scene"), "file": path, "in": c_in, "out": c_out, "fps": fps,
            "kind": s.get("kind"), "bridged": (s.get("scene") in bridged) or bool(s.get("bridged")),
            "first": frames[0], "last": frames[-1], "cut_t": round(cut_t, 4), "rep": rep, "seg": s,
        })
        t_acc = cut_t
        if rep["jumps"]:
            clip_jumps.append(rep)
    transitions = []
    for k in range(len(decoded) - 1):
        a, b = decoded[k], decoded[k + 1]
        seam = float(np.mean(np.abs(a["last"].astype(np.float32) - b["first"].astype(np.float32))))
        kind = classify_seam(seam)
        tr = {
            "from_scene": a["scene"], "to_scene": b["scene"], "at": a["cut_t"],
            "seam_mae": round(seam, 2), "kind": kind,
        }
        if b["bridged"]:
            tr["bridged"] = True
            tr["bridge_mismatch"] = seam >= 8.0
        transitions.append(tr)
    dark_first = bool(decoded and decoded[0]["rep"]["dark_first_frame"])
    return {"transitions": transitions, "clip_jumps": clip_jumps, "dark_first_frame": dark_first}


def write_rgb_jpg(rgb_img: np.ndarray, out_path: Path) -> None:
    """Write an (H, W, 3) uint8 RGB image to JPEG using ffmpeg without extra libraries."""
    h, w, _ = rgb_img.shape
    out_path.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(
        [ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pixel_format", "rgb24",
         "-video_size", f"{w}x{h}", "-i", "-", "-q:v", "3", str(out_path)],
        input=np.ascontiguousarray(rgb_img, dtype=np.uint8).tobytes(),
        capture_output=True,
    )
    if p.returncode != 0:
        raise RuntimeError("ffmpeg image write failed:\n" + p.stderr.decode("utf-8", errors="replace")[-800:])


def grab_frame_rgb(path, t: float, w: int = 320, h: int = 180) -> np.ndarray:
    """Grab one frame at clip time t as uint8 (H, W, 3) RGB."""
    p = subprocess.run(
        [ffmpeg(), "-v", "error", "-ss", f"{max(0.0, t):.5f}", "-i", str(path), "-frames:v", "1",
         "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    )
    fb = w * h * 3
    if p.returncode != 0 or len(p.stdout) < fb:
        return np.zeros((h, w, 3), dtype=np.uint8)
    return np.frombuffer(p.stdout[:fb], dtype=np.uint8).reshape(h, w, 3).copy()


def build_cut_sheet(segs: list[dict], transitions: list[dict], out_path: Path, tile_w: int = 320, tile_h: int = 180) -> None:
    """Render (-1f, cut, +1f) triplets for each transition row with a status bar header."""
    if not transitions:
        return
    video_segs = []
    for s in segs:
        path, c_in, c_out = resolve_seg_bounds(s)
        if not path or not Path(path).exists():
            continue
        if s.get("kind") != "image" and c_out is not None and c_out - c_in <= 1e-6:
            continue
        video_segs.append(s)
    colors = {"frame_locked": (60, 210, 90), "soft_match": (235, 175, 45), "cut": (220, 60, 60)}
    rows = []
    for idx, tr in enumerate(transitions):
        if idx + 1 >= len(video_segs):
            break
        sa, sb = video_segs[idx], video_segs[idx + 1]
        pa, c_in_a, c_out_a = resolve_seg_bounds(sa)
        pb, c_in_b, _ = resolve_seg_bounds(sb)
        fa, fb = probe(pa), probe(pb)
        dt_a = 1.0 / float(fa["fps"] or FPS)
        dt_b = 1.0 / float(fb["fps"] or FPS)
        dur_a = float(fa["duration"] or 0.0)
        dur_b = float(fb["duration"] or 0.0)
        t_out = c_out_a if c_out_a is not None else dur_a
        t_prev = 0.0 if sa.get("kind") == "image" or dur_a <= dt_a * 1.5 else min(max(0.0, dur_a - dt_a), max(0.0, t_out - dt_a))
        t_cut = 0.0 if sb.get("kind") == "image" else min(max(0.0, dur_b - dt_b), max(0.0, c_in_b))
        t_next = 0.0 if sb.get("kind") == "image" or dur_b <= dt_b * 1.5 else min(max(0.0, dur_b - dt_b), t_cut + dt_b)
        f_prev = grab_frame_rgb(pa, t_prev, tile_w, tile_h)
        f_cut = grab_frame_rgb(pb, t_cut, tile_w, tile_h)
        f_next = grab_frame_rgb(pb, t_next, tile_w, tile_h)
        strip = np.concatenate([f_prev, f_cut, f_next], axis=1)
        bar = np.zeros((18, strip.shape[1], 3), dtype=np.uint8)
        bar[:] = colors.get(tr["kind"], (220, 60, 60))
        try:
            import cv2
            txt = f"S{tr['from_scene']}->S{tr['to_scene']} @{tr['at']:.2f}s MAE={tr['seam_mae']:.2f} [{tr['kind']}]"
            cv2.putText(bar, txt, (8, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (15, 15, 15), 1, cv2.LINE_AA)
        except Exception:
            pass
        rows.append(np.concatenate([bar, strip], axis=0))
    if not rows:
        return
    write_rgb_jpg(np.concatenate(rows, axis=0), out_path)
