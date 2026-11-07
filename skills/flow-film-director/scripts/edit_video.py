"""Edit exact frames, scenes and periods of the assembled film - deterministic, frame-accurate, audio kept in sync.

Usage (skill venv python):
  python edit_video.py locate --timeline final/film.timeline.json --at 12.4
  python edit_video.py locate --timeline final/film.timeline.json --range 12 15
  python edit_video.py frame  --film final/film.mp4 --at 12.4 --out fix/frame-12.4.png
  python edit_video.py apply  --timeline final/film.timeline.json --edits edits.json [--out final/film-v2.mp4]

`locate` maps film time to scene, take and time inside the take (what to regenerate or splice).
`apply` runs the edits IN ORDER; every edit's times refer to the film as it is after the edits before it.
It writes the new film and its new timeline (<out>.timeline.json), so you can locate/edit again.

Edits (times in seconds of the film; ranges [start, end]):
  structural (change timing)
    {"op": "cut", "range": [a, b]}                                    remove a period
    {"op": "replace", "range": [a, b], "source": "x.mp4", "source_in": 0, "audio": "source|original|silence"}
    {"op": "splice", "range": [a, b], "source": "new_take.mp4", "audio": "source|original"}
        replace a period with the SAME moment of a new take of that scene (source_in found from the timeline)
    {"op": "insert", "at": t, "source": "x.mp4", "source_in": 0, "source_out": 2.5}
    {"op": "insert", "at": t, "image": "card.png", "dur": 2.0}           title card / corrected still
    {"op": "speed", "range": [a, b], "factor": 0.5, "audio": "keep|mute"} slow motion (<1) or faster (>1)
    {"op": "freeze", "at": t, "dur": 1.5}                                 hold a frame
  look and sound (timing unchanged)
    {"op": "color", "range": [a, b], "brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "gamma": 1.0}
    {"op": "text", "range": [a, b], "text": "SALE -20%", "position": "bottom|top|center", "size": 0.06,
     "color": "white", "box": true}                                       titles, prices, names (Flow cannot draw text)
    {"op": "overlay", "range": [a, b], "image": "logo.png", "position": "top-right", "width": 0.18}
    {"op": "blur", "range": [a, b], "box": [x, y, w, h]}                  fractions of the frame, e.g. hide a stray object
    {"op": "zoom", "range": [a, b], "factor": 1.25, "center": [0.5, 0.4]} punch-in
    {"op": "volume", "range": [a, b], "db": -10}      {"op": "mute", "range": [a, b]}
    {"op": "audio_replace", "range": [a, b], "source": "line.wav", "source_in": 0}
    {"op": "fade", "in": 0.5, "out": 1.0}
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from editkit import AR, probe, render_parts, run  # noqa: E402

STRUCTURAL = {"cut", "replace", "splice", "insert", "speed", "freeze"}
FONTS = ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


# ------------------------------------------------------------------ timeline bookkeeping
def split(segs, t):
    out = []
    for s in segs:
        if s["film_start"] < t < s["film_end"] - 1e-6:
            sp = s.get("speed", 1.0)
            ct = s.get("clip_in", 0) + (t - s["film_start"]) * sp
            left, right = dict(s), dict(s)
            left["film_end"], left["clip_out"] = t, ct
            right["film_start"], right["clip_in"] = t, ct
            out += [left, right]
        else:
            out.append(s)
    return out


def shift(segs, after, delta):
    for s in segs:
        if s["film_start"] >= after - 1e-6:
            s["film_start"] = s["film_start"] + delta
            s["film_end"] = s["film_end"] + delta
    return segs


def rnd(segs):
    for s in segs:
        for k in ("film_start", "film_end", "clip_in", "clip_out"):
            if k in s and s[k] is not None:
                s[k] = round(s[k], 4)
    return segs


def tl_cut(segs, a, b):
    segs = split(split(segs, a), b)
    keep = [s for s in segs if not (s["film_start"] >= a - 1e-6 and s["film_end"] <= b + 1e-6)]
    return rnd(shift(keep, b, -(b - a)))


def tl_insert(segs, t, seg):
    d = seg["film_end"] - seg["film_start"]
    segs = shift(split(segs, t), t, d)
    segs.append(seg)
    return rnd(sorted(segs, key=lambda s: s["film_start"]))


def tl_replace(segs, a, b, seg):
    segs = split(split(segs, a), b)
    keep = [s for s in segs if not (s["film_start"] >= a - 1e-6 and s["film_end"] <= b + 1e-6)]
    keep.append(seg)
    return rnd(sorted(keep, key=lambda s: s["film_start"]))


def locate(meta, a, b=None):
    b = a if b is None else b
    hits = []
    for s in meta["segments"]:
        if s["film_end"] > a and s["film_start"] <= b:
            lo, hi = max(a, s["film_start"]), min(b, s["film_end"])
            sp = s.get("speed", 1.0)
            ci = s.get("clip_in", 0)
            hits.append({**s, "film_from": round(lo, 3), "film_to": round(hi, 3),
                         "take_from": round(ci + (lo - s["film_start"]) * sp, 3),
                         "take_to": round(ci + (hi - s["film_start"]) * sp, 3),
                         "scene_from": round((lo - s["film_start"]) * sp, 3)})
    return hits


# ------------------------------------------------------------------ rendering one edit
def structural(film, dur, e, meta, size, fps, out, segs):
    W, H = size
    op = e["op"]
    F = str(film)
    parts = []

    def keep(x, y):
        if y - x > 1e-3:
            parts.append({"file": F, "in": x, "out": y})

    if op == "cut":
        a, b = e["range"]
        keep(0, a)
        keep(b, dur)
        segs = tl_cut(segs, a, b)
    elif op in ("replace", "splice"):
        a, b = e["range"]
        src = str(Path(e["source"]).resolve())
        if op == "splice" and "source_in" not in e:
            hit = locate(meta, a, b)
            if len(hit) != 1:
                raise SystemExit(f"splice range {a}-{b} must lie inside ONE scene (found {len(hit)}); split it in two edits")
            x = hit[0]["take_from"]
        else:
            x = float(e.get("source_in", 0))
        sdur = probe(src)["duration"]
        if x + (b - a) > sdur + 1e-3:
            raise SystemExit(f"{op}: source {src} has {sdur:.2f}s, needs {x:.2f}+{b - a:.2f}s")
        keep(0, a)
        parts.append({"file": src, "in": x, "out": x + (b - a), "mute": e.get("audio") == "silence"})
        keep(b, dur)
        segs = tl_replace(segs, a, b, {"film_start": a, "film_end": b, "scene": e.get("scene", "replaced"),
                                       "clip": src, "clip_in": x, "clip_out": x + (b - a), "speed": 1.0, "kind": op})
    elif op == "insert":
        t = float(e["at"])
        keep(0, t)
        if "image" in e:
            d = float(e["dur"])
            parts.append({"image": str(Path(e["image"]).resolve()), "dur": d})
            seg = {"scene": "insert", "clip": str(Path(e["image"]).resolve()), "clip_in": 0, "clip_out": d, "kind": "image"}
        else:
            src = str(Path(e["source"]).resolve())
            si = float(e.get("source_in", 0))
            so = float(e.get("source_out", probe(src)["duration"]))
            d = so - si
            parts.append({"file": src, "in": si, "out": so})
            seg = {"scene": e.get("scene", "insert"), "clip": src, "clip_in": si, "clip_out": so, "kind": "insert"}
        keep(t, dur)
        seg.update({"film_start": t, "film_end": t + d, "speed": 1.0})
        segs = tl_insert(segs, t, seg)
    elif op == "speed":
        a, b = e["range"]
        f = float(e["factor"])
        if not 0.25 <= f <= 4:
            raise SystemExit("speed factor must be between 0.25 and 4")
        keep(0, a)
        parts.append({"file": F, "in": a, "out": b, "speed": f, "mute": e.get("audio") == "mute"})
        keep(b, dur)
        segs = speed_timeline(segs, a, b, f)
    elif op == "freeze":
        t, d = float(e["at"]), float(e["dur"])
        keep(0, t)
        parts.append({"freeze": F, "at": min(t, dur - 1.0 / fps), "dur": d})
        keep(t, dur)
        segs = tl_insert(segs, t, {"film_start": t, "film_end": t + d, "scene": "freeze", "clip": F, "clip_in": t,
                                   "clip_out": t, "speed": 0.0, "kind": "freeze"})
    new_dur = render_parts(parts, out, W, H, fps=fps, crf=14)
    if op in ("replace", "splice") and e.get("audio") == "original":
        tmp = Path(out).with_suffix(".tmp.mp4")
        run(["-y", "-i", str(out), "-i", F, "-map", "0:v", "-map", "1:a", "-c", "copy", "-shortest", str(tmp)])
        shutil.move(str(tmp), str(out))
    return new_dur, segs


def speed_timeline(segs, a, b, f):
    segs = split(split(segs, a), b)
    delta = (b - a) / f - (b - a)
    out = []
    for s in segs:
        s = dict(s)
        if s["film_start"] >= a - 1e-6 and s["film_end"] <= b + 1e-6:
            s["film_start"] = a + (s["film_start"] - a) / f
            s["film_end"] = a + (s["film_end"] - a) / f
            s["speed"] = s.get("speed", 1.0) * f
        elif s["film_start"] >= b - 1e-6:
            s["film_start"] += delta
            s["film_end"] += delta
        out.append(s)
    return rnd(out)


def pos_xy(position, w_expr="w", h_expr="h", W="W", H="H", margin=0.04):
    m = f"{margin}*{H}"
    return {
        "top-left": (m, m), "top-right": (f"{W}-{w_expr}-{m}", m), "bottom-left": (m, f"{H}-{h_expr}-{m}"),
        "bottom-right": (f"{W}-{w_expr}-{m}", f"{H}-{h_expr}-{m}"), "center": (f"({W}-{w_expr})/2", f"({H}-{h_expr})/2"),
        "top": (f"({W}-{w_expr})/2", m), "bottom": (f"({W}-{w_expr})/2", f"{H}-{h_expr}-{m}"),
    }[position]


def look(film, e, out, work):
    """Timing-preserving edits: one ffmpeg pass on the current film."""
    op = e["op"]
    inputs = ["-i", str(film)]
    vf, af = None, None
    info = probe(film)
    FW, FH = info["width"], info["height"]
    a, b = e.get("range", [0, 0])
    en = f"enable='between(t,{a:.4f},{b:.4f})'"
    if op == "color":
        vf = (f"[0:v]eq=brightness={float(e.get('brightness', 0))}:contrast={float(e.get('contrast', 1))}:"
              f"saturation={float(e.get('saturation', 1))}:gamma={float(e.get('gamma', 1))}:{en}[v]")
    elif op == "text":
        font = e.get("font") or next((f for f in FONTS if Path(f).exists()), None)
        if not font:
            raise SystemExit("no font found: pass \"font\": \"<path to .ttf>\"")
        shutil.copy(font, Path(work) / "font.ttf")
        (Path(work) / "text.txt").write_text(e["text"], encoding="utf-8")
        size = float(e.get("size", 0.06))
        x, y = pos_xy(e.get("position", "bottom"), "text_w", "text_h", "w", "h")
        box = ":box=1:boxcolor=black@0.45:boxborderw=18" if e.get("box", True) else ""
        vf = (f"[0:v]drawtext=fontfile=font.ttf:textfile=text.txt:expansion=none:fontsize=h*{size}:"
              f"fontcolor={e.get('color', 'white')}:x={x}:y={y}{box}:{en}[v]")
    elif op == "overlay":
        inputs += ["-loop", "1", "-i", str(Path(e["image"]).resolve())]
        x, y = pos_xy(e.get("position", "top-right"), "overlay_w", "overlay_h", "main_w", "main_h")
        wf = float(e.get("width", 0.18))
        lw = max(2, int(round(FW * wf / 2)) * 2)          # explicit size (scale2ref is deprecated in ffmpeg 7)
        vf = (f"[1:v]scale={lw}:-2,format=rgba[lg];"
              f"[0:v][lg]overlay=x={x}:y={y}:shortest=1:{en}[v]")
    elif op == "blur":
        x, y, w, h = e["box"]
        vf = (f"[0:v]split[m][c];[c]crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},boxblur={int(e.get('strength', 20))}:2[bl];"
              f"[m][bl]overlay=x=main_w*{x}:y=main_h*{y}:{en}[v]")
    elif op == "zoom":
        f = float(e.get("factor", 1.25))
        cx, cy = e.get("center", [0.5, 0.5])
        vf = (f"[0:v]split[m][z];[z]crop=iw/{f}:ih/{f}:"
              f"min(max(iw*{cx}-iw/{f}/2\\,0)\\,iw-iw/{f}):min(max(ih*{cy}-ih/{f}/2\\,0)\\,ih-ih/{f}),"
              f"scale={FW}:{FH},setsar=1[zz];[m][zz]overlay=0:0:{en}[v]")
    elif op in ("volume", "mute"):
        db = -120 if op == "mute" else float(e.get("db", 0))
        af = f"[0:a]volume={db}dB:{en}[a]"
    elif op == "audio_replace":
        src = str(Path(e["source"]).resolve())
        si = float(e.get("source_in", 0))
        inputs += ["-ss", f"{si:.4f}", "-i", src]
        ms = int(round(a * 1000))
        af = (f"[0:a]volume=-120dB:{en}[base];[1:a]aresample={AR},aformat=channel_layouts=stereo,"
              f"atrim=duration={b - a:.4f},adelay={ms}|{ms}[ins];[base][ins]amix=inputs=2:normalize=0:duration=first[a]")
    elif op == "fade":
        d = probe(film)["duration"]
        fi, fo = float(e.get("in", 0)), float(e.get("out", 0))
        v, au = [], []
        if fi > 0:
            v.append(f"fade=t=in:st=0:d={fi}")
            au.append(f"afade=t=in:st=0:d={fi}")
        if fo > 0:
            v.append(f"fade=t=out:st={d - fo:.4f}:d={fo}")
            au.append(f"afade=t=out:st={d - fo:.4f}:d={fo}")
        vf = f"[0:v]{','.join(v) or 'null'}[v]"
        af = f"[0:a]{','.join(au) or 'anull'}[a]"
    else:
        raise SystemExit(f"unknown op {op}")
    graph = ";".join(x for x in (vf, af) if x)
    args = ["-y", *inputs, "-filter_complex", graph]
    args += ["-map", "[v]", "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p"] if vf else ["-map", "0:v", "-c:v", "copy"]
    args += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", str(AR)] if af else ["-map", "0:a", "-c:a", "copy"]
    run([*args, "-movflags", "+faststart", str(Path(out).resolve())], cwd=work)


def apply(timeline_path, edits, out):
    meta = json.loads(Path(timeline_path).read_text(encoding="utf-8"))
    film = Path(meta["film"])
    size, fps = meta["size"], meta.get("fps", 24)
    segs = copy.deepcopy(meta["segments"])
    log = []
    with tempfile.TemporaryDirectory() as td:
        cur = Path(td) / "step-0.mp4"
        shutil.copy(film, cur)
        for i, e in enumerate(edits, 1):
            nxt = Path(td) / f"step-{i}.mp4"
            before = probe(cur)["duration"]
            if e["op"] in STRUCTURAL:
                meta_now = {**meta, "segments": segs}
                _, segs = structural(cur, before, e, meta_now, size, fps, nxt, segs)
            else:
                look(cur, e, nxt, td)
            after = probe(nxt)["duration"]
            log.append({"edit": i, "op": e["op"], "before": round(before, 3), "after": round(after, 3),
                        "timeline_end": segs[-1]["film_end"] if segs else 0})
            cur = nxt
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(cur, out)
    new_meta = {**meta, "film": str(Path(out).resolve()), "duration": round(probe(out)["duration"], 3), "segments": segs,
                "edited_from": meta["film"], "edits": edits}
    tl = Path(out).with_suffix(".timeline.json")
    tl.write_text(json.dumps(new_meta, indent=2), encoding="utf-8")
    return {"film": str(out), "timeline": str(tl), "duration": new_meta["duration"], "steps": log}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    lo = sub.add_parser("locate")
    lo.add_argument("--timeline", required=True)
    lo.add_argument("--at", type=float)
    lo.add_argument("--range", nargs=2, type=float)
    fr = sub.add_parser("frame")
    fr.add_argument("--film", required=True)
    fr.add_argument("--at", type=float, required=True)
    fr.add_argument("--out", required=True)
    ap_ = sub.add_parser("apply")
    ap_.add_argument("--timeline", required=True)
    ap_.add_argument("--edits", required=True)
    ap_.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "locate":
        meta = json.loads(Path(a.timeline).read_text(encoding="utf-8"))
        hits = locate(meta, *(a.range if a.range else (a.at, None)))
        print(json.dumps({"hits": hits}, indent=2))
    elif a.cmd == "frame":
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        run(["-y", "-i", a.film, "-vf", f"select='gte(t\\,{a.at:.4f})'", "-frames:v", "1", "-vsync", "vfr", a.out])
        print(a.out)
    else:
        edits = json.loads(Path(a.edits).read_text(encoding="utf-8"))
        edits = edits.get("edits", edits) if isinstance(edits, dict) else edits
        meta = json.loads(Path(a.timeline).read_text(encoding="utf-8"))
        out = a.out or str(Path(meta["film"]).with_name(Path(meta["film"]).stem + "-edit.mp4"))
        print(json.dumps(apply(a.timeline, edits, out), indent=2))


if __name__ == "__main__":
    main()
