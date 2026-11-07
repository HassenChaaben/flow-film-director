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
import re
import shutil
import subprocess
from pathlib import Path

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
    return (f"loudnorm=I={target}:TP={tp}:LRA={lra}:measured_I={m['lufs']}:measured_TP={m['true_peak']}:"
            f"measured_LRA={m['lra']}:measured_thresh={m['thresh']}:offset={m['offset']}:linear=true")
