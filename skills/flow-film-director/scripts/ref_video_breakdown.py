"""Break a reference video into shots and record exactly what happens in each one (the "memory" of the reference).

Usage (use the skill venv python, see setup_env.py):
  python ref_video_breakdown.py <video> --out film/<slug>/reference [--start 12.5 --end 41] [--max-shots 40]

Writes to --out:
  breakdown.json   machine record: per shot start/end/duration, camera move, shot size, people with screen
                   position and timed body events, pose speed, risk level. Feed this to build_prompts.py.
  breakdown.md     the same as a readable shot list - the agent adds the meaning of each action under "Agent notes".
  shots/shot-NN/   kf-000.jpg ... kf-100.jpg (0/25/50/75/100 % of the shot, full resolution),
                   frames/ (every sampled frame, 8 fps, for reading the action beat by beat),
                   sheet.jpg (contact sheet with the timeline), pose.npz (body tracks for motion_match.py)
Same video + same arguments -> same files (fixed sampling, fixed thresholds, sequential decoding).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402

from facekit import FaceKit, grid, imwrite, label, log  # noqa: E402
from motionkit import SAMPLE_FPS, PoseTracker, analyse_segment, hsv_hist, is_cut, iter_frames, risk, small, video_info  # noqa: E402

MIN_SHOT = 0.30  # seconds; shorter "shots" are flashes and merge into the previous one


def detect_shots(path, start, end):
    info = video_info(path)
    cuts, prev_h, prev_s, last_t = [start], None, None, start
    for _, t, frame in iter_frames(path, start, end):
        h = hsv_hist(frame)
        s = small(frame, 160)
        if prev_h is not None:
            cut, _ = is_cut(prev_h, h, prev_s, s)
            if cut and t - cuts[-1] >= MIN_SHOT:
                cuts.append(t)
        prev_h, prev_s, last_t = h, s, t
    stop = end if end is not None else last_t + 1 / info["fps"]
    return [(cuts[i], cuts[i + 1] if i + 1 < len(cuts) else stop) for i in range(len(cuts))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--max-shots", type=int, default=60)
    a = ap.parse_args()
    out = Path(a.out)
    (out / "shots").mkdir(parents=True, exist_ok=True)
    info = video_info(a.video)
    log(f"video {info['width']}x{info['height']} {info['fps']:.3f} fps {info['duration']:.1f}s")
    shots = detect_shots(a.video, a.start, a.end)
    log(f"{len(shots)} shots")
    if len(shots) > a.max_shots:
        sys.exit(f"{len(shots)} shots found (> --max-shots {a.max_shots}). Pick a smaller part with --start/--end.")
    pose, kit = PoseTracker(), FaceKit(score_threshold=0.6)
    record, md = [], ["# Reference breakdown", "", f"Source: `{a.video}`  ({info['width']}x{info['height']}, {info['fps']:.2f} fps)",
                      f"Window: {a.start:.2f}s - {(a.end if a.end else info['duration']):.2f}s, {len(shots)} shots. "
                      "Body events are measured; fill **Agent notes** by reading the frames.", ""]
    for n, (s0, s1) in enumerate(shots, 1):
        frames = []
        r = analyse_segment(a.video, s0, s1, pose, kit, keep_frames=frames)
        sid = f"shot-{n:02d}"
        d = out / "shots" / sid
        (d / "frames").mkdir(parents=True, exist_ok=True)
        for t, f in frames:
            imwrite(d / "frames" / f"t{t:08.3f}.jpg", small(f, 960))
        kfs = []
        for pct in (0, 25, 50, 75, 100):
            if frames:
                t, f = frames[min(len(frames) - 1, int(round((len(frames) - 1) * pct / 100)))]
                p = d / f"kf-{pct:03d}.jpg"
                imwrite(p, f)
                kfs.append({"pct": pct, "t": round(t, 3), "file": str(p)})
        sel = frames if len(frames) <= 12 else [frames[int(i)] for i in np.linspace(0, len(frames) - 1, 12)]
        imwrite(d / "sheet.jpg", grid([label(f, f"{sid} t={t:.2f}s") for t, f in sel], cols=4, tile_w=400))
        cam = np.array([list(c) if c else [np.nan] * 4 for c in r["cam_steps"]], dtype=float).reshape(-1, 4)
        np.savez_compressed(d / "pose.npz", tracks=r["tracks"], times=np.array(r["times"]), energy=np.array(r["energy"]), cam=cam)
        rk = risk(r)
        rec = {k: v for k, v in r.items() if k not in ("tracks", "times", "energy", "cam_steps")}
        rec.update({"id": sid, "keyframes": kfs, "sheet": str(d / "sheet.jpg"), "frames_dir": str(d / "frames"),
                    "pose_file": str(d / "pose.npz"), "risk": rk,
                    "energy_peaks": [round(r["times"][i], 2) for i in range(1, len(r["energy"]) - 1)
                                     if r["energy"][i] > r["energy"][i - 1] and r["energy"][i] >= r["energy"][i + 1]
                                     and r["energy"][i] > 1.5 * (np.median(r["energy"]) + 1e-6)]})
        record.append(rec)
        md += [f"## {sid}  {s0:.2f}s - {s1:.2f}s  ({r['duration']:.2f}s)",
               f"- shot size: **{r['shot_size']}** | camera: **{r['camera']['move']}** (pan {r['camera']['pan']}, tilt {r['camera']['tilt']}, zoom {r['camera']['zoom']})",
               f"- people: {r['people_count']} | pose speed: {r['pose_speed']} | risk: **{rk['level']}** {('(' + '; '.join(rk['reasons']) + ')') if rk['reasons'] else ''}",
               f"- motion peaks (s): {rec['energy_peaks'][:12]}",
               f"- sheet: `{d / 'sheet.jpg'}`  frames: `{d / 'frames'}`"]
        for p in r["people"]:
            md.append(f"- **{p['id']}** ({p['position']}, x {p['x_start']} -> {p['x_end']}):")
            md += [f"  - t={e['t']:.2f}s {e['event']}" for e in p["events"]]
        md += ["- Agent notes (fill by reading frames): who is who, what each hand holds, exact action per beat with times, "
               "gaze, expression, props, set, light, what must be copied exactly.", ""]
        log(f"{sid} {r['duration']:.2f}s {r['shot_size']} {r['camera']['move']} people={r['people_count']} risk={rk['level']}")
    (out / "breakdown.json").write_text(json.dumps({"source": str(a.video), "info": info, "window": [a.start, a.end],
                                                    "sample_fps": SAMPLE_FPS, "pose_available": pose.available,
                                                    "shots": record}, indent=2, default=float), encoding="utf-8")
    (out / "breakdown.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"breakdown_md": str(out / "breakdown.md"), "breakdown_json": str(out / "breakdown.json"),
                      "shots": len(record), "pose_available": pose.available,
                      "risk": {s["id"]: s["risk"]["level"] for s in record}}, indent=2))


if __name__ == "__main__":
    main()
