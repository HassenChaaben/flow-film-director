"""Assemble the film from accepted clips, with the audio the user chose, and write the timeline used for editing.

Usage (skill venv python):
  python assemble.py film/<slug>/storyboard.json [--out film/<slug>/final/film.mp4]
  python assemble.py --clips a.mp4 b.mp4 ... --out film.mp4 [--soundtrack music.mp3] [--mode soundtrack] ...

Clips: every scene with accepted.clip, in scene id order, cut to its `trim` [in, out] (whole clip when no trim).
A voiced take (accepted.clip_voiced, made by voice_convert.py) is used instead of accepted.clip when present.

Audio - storyboard "audio" block (or CLI flags):
  "mode": "native"      clips' own sound (dialogue + ambience)                                   [default]
          "soundtrack"  music for the whole film; clips muted (or kept low with clip_volume)
          "voiceover"   narration file(s) on top; clips low; optional music ducked under the voice
          "mixed"       clips' dialogue + music, music ducked automatically whenever someone speaks
  "soundtrack": {"file": "<path>", "start": 0, "volume_db": 0, "fade_in": 0.5, "fade_out": 2.0,
                 "loop": true, "snap_cuts_to_beats": false, "max_shift": 0.5}
  "voiceover": [{"file": "<path>", "at": 0.0}]          (one file, or lines placed at film times)
  "clip_volume": 0..1  (default: native/mixed 1.0, voiceover 0.25, soundtrack 0.0)
  "target_lufs": -14   (social -14, YouTube -14, broadcast -23); true peak limited to -1.5 dBTP

Beat snapping (soundtrack modes): every cut is moved to the nearest music beat within max_shift seconds, only by
shortening the clip or using frames the clip still has; each shot keeps at least 1 s. Moves are reported.
Writes the film, <film>.timeline.json (film time -> scene/clip/clip time, for edit_video.py) and prints a report.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audiokit import load, tempo_and_beats  # noqa: E402
from editkit import AR, FPS, even, loudness, loudnorm_filter, probe, render_parts, run  # noqa: E402


def collect(sb_path: Path):
    sb = json.loads(sb_path.read_text(encoding="utf-8"))
    base = sb_path.parent
    segs = []
    for sc in sorted(sb["scenes"], key=lambda s: s["id"]):
        acc = sc.get("accepted") or {}
        clip = acc.get("clip_voiced") or acc.get("clip")
        if not clip:
            raise SystemExit(f"scene {sc['id']} has no accepted clip - finish Phase 6 first")
        p = Path(clip) if Path(clip).is_absolute() else base / clip
        if not p.exists():
            raise SystemExit(f"scene {sc['id']}: clip not found {p}")
        dur = probe(p)["duration"]
        a, b = (sc.get("trim") or [0.0, dur])
        segs.append({"scene": sc["id"], "file": str(p.resolve()), "in": float(a), "out": min(float(b), dur), "clip_len": dur})
    audio = sb.get("audio", {})
    for key in ("soundtrack",):
        if isinstance(audio.get(key), dict) and audio[key].get("file") and not Path(audio[key]["file"]).is_absolute():
            audio[key]["file"] = str((base / audio[key]["file"]).resolve())
    for vo in audio.get("voiceover", []) or []:
        if not Path(vo["file"]).is_absolute():
            vo["file"] = str((base / vo["file"]).resolve())
    return segs, audio, sb


def snap_to_beats(segs, beats, max_shift=0.5, min_len=1.0):
    """Move each cut (end of every segment but the last) to the nearest beat it can reach. Deterministic."""
    moves, t = [], 0.0
    for i, s in enumerate(segs):
        length = s["out"] - s["in"]
        if i == len(segs) - 1:
            break
        cut = t + length
        can_extend = s["clip_len"] - s["out"]
        cands = [b for b in beats if cut - max_shift <= b <= cut + min(max_shift, can_extend) and b - t >= min_len]
        if cands:
            b = min(cands, key=lambda x: (abs(x - cut), x))
            s["out"] = round(s["in"] + (b - t), 4)
            moves.append({"scene": s["scene"], "cut_was": round(cut, 3), "cut_now": round(b, 3)})
            t = b
        else:
            moves.append({"scene": s["scene"], "cut_was": round(cut, 3), "cut_now": round(cut, 3), "note": "no beat in reach"})
            t = cut
    return moves


def mix_audio(video_in, out, audio, film_dur, workdir):
    """Build the final soundtrack on top of the rendered picture and normalise loudness (two-pass)."""
    mode = audio.get("mode", "native")
    st = audio.get("soundtrack") or {}
    vos = audio.get("voiceover") or []
    clip_vol = float(audio.get("clip_volume", {"native": 1.0, "mixed": 1.0, "voiceover": 0.25, "soundtrack": 0.0}[mode]))
    target = float(audio.get("target_lufs", -14))
    inputs, chains, mixes = ["-i", str(video_in)], [], []
    chains.append(f"[0:a]volume={clip_vol:.4f}[clip]")
    mixes.append("[clip]")
    duck_from = None
    if mode in ("voiceover",) and vos:
        vlabels = []
        for k, vo in enumerate(vos):
            inputs += ["-i", vo["file"]]
            ms = int(round(float(vo.get("at", 0)) * 1000))
            chains.append(f"[{len(inputs) // 2 - 1}:a]aresample={AR},aformat=channel_layouts=stereo,adelay={ms}|{ms},apad[vo{k}]")
            vlabels.append(f"[vo{k}]")
        chains.append(f"{''.join(vlabels)}amix=inputs={len(vlabels)}:normalize=0:duration=longest,atrim=duration={film_dur:.6f}[vo]")
        if st.get("file"):  # only split for ducking when there is music to duck
            chains.append("[vo]asplit=2[vomix][voside]")
            mixes.append("[vomix]")
            duck_from = "[voside]"
        else:
            mixes.append("[vo]")
    if mode == "mixed" and st.get("file"):
        chains[0] = f"[0:a]volume={clip_vol:.4f},asplit=2[clip][clipside]"
        duck_from = "[clipside]"
    if st.get("file") and mode in ("soundtrack", "voiceover", "mixed"):
        mdur = probe(st["file"])["duration"]
        start = float(st.get("start", 0))
        loop = st.get("loop", True) and (mdur - start) < film_dur
        inputs += (["-stream_loop", "-1"] if loop else []) + ["-ss", f"{start:.3f}", "-i", st["file"]]
        k = len([x for x in inputs if x == "-i"]) - 1
        fi, fo = float(st.get("fade_in", 0.5)), float(st.get("fade_out", 2.0))
        chain = (f"[{k}:a]aresample={AR},aformat=channel_layouts=stereo,atrim=duration={film_dur:.6f},asetpts=PTS-STARTPTS,"
                 f"volume={float(st.get('volume_db', 0)):.2f}dB")
        if fi > 0:
            chain += f",afade=t=in:st=0:d={fi:.3f}"
        if fo > 0:
            chain += f",afade=t=out:st={max(0.0, film_dur - fo):.3f}:d={fo:.3f}"
        chains.append(chain + "[music0]")
        if duck_from:  # music dips ~12 dB whenever the voice/dialogue is present
            chains.append(f"[music0]{duck_from}sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350:makeup=1[music]")
        else:
            chains.append("[music0]anull[music]")
        mixes.append("[music]")
        if mdur - start < film_dur and not loop:
            print(f"warning: soundtrack ({mdur - start:.1f}s from start) is shorter than the film ({film_dur:.1f}s)", file=sys.stderr)
    elif mode == "soundtrack":
        raise SystemExit("mode 'soundtrack' needs audio.soundtrack.file (ask the user for the soundtrack file path)")
    graph = ";".join(chains) + f";{''.join(mixes)}amix=inputs={len(mixes)}:normalize=0:duration=first,atrim=duration={film_dur:.6f}[mix]"
    pre = Path(workdir) / "premix.wav"
    run(["-y", *inputs, "-filter_complex", graph, "-map", "[mix]", "-c:a", "pcm_s16le", "-ar", str(AR), str(pre)])
    m = loudness(pre)
    gain = target - m["lufs"]
    if m["true_peak"] + gain > -1.5:
        # Peaky audio (drums) cannot reach the target in linear mode without clipping: raise the gain and let a
        # look-ahead limiter hold the peaks at -2 dBFS, then normalise exactly (linear) on the limited signal.
        lim = Path(workdir) / "limited.wav"
        run(["-y", "-i", str(pre), "-af", f"volume={gain:.2f}dB,alimiter=limit={10 ** (-2.0 / 20):.4f}:attack=3:release=60:level=false",
             "-c:a", "pcm_s24le", "-ar", str(AR), str(lim)])
        pre = lim
    norm = loudnorm_filter(pre, target=target)
    run(["-y", "-i", str(video_in), "-i", str(pre), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", norm + f",aresample={AR}",
         "-c:a", "aac", "-b:a", "192k", "-ar", str(AR), "-shortest", "-movflags", "+faststart", str(out)])
    return mode, clip_vol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("storyboard", nargs="?")
    ap.add_argument("--clips", nargs="*")
    ap.add_argument("--out")
    ap.add_argument("--mode", choices=["native", "soundtrack", "voiceover", "mixed"])
    ap.add_argument("--soundtrack")
    ap.add_argument("--soundtrack-start", type=float)
    ap.add_argument("--snap", action="store_true", help="snap cuts to the soundtrack's beats")
    ap.add_argument("--voiceover")
    ap.add_argument("--clip-volume", type=float)
    ap.add_argument("--target-lufs", type=float)
    ap.add_argument("--size", help="WxH, default: first clip's size")
    ap.add_argument("--fps", type=float, default=FPS)
    a = ap.parse_args()
    if a.storyboard:
        sb_path = Path(a.storyboard).resolve()
        segs, audio, sb = collect(sb_path)
        out = Path(a.out) if a.out else sb_path.parent / "final" / "film.mp4"
    elif a.clips:
        segs = []
        for i, c in enumerate(a.clips, 1):
            d = probe(c)["duration"]
            segs.append({"scene": i, "file": str(Path(c).resolve()), "in": 0.0, "out": d, "clip_len": d})
        audio, out = {}, Path(a.out or "film.mp4")
    else:
        sys.exit(__doc__)
    if a.mode:
        audio["mode"] = a.mode
    if a.soundtrack:
        audio.setdefault("soundtrack", {})["file"] = str(Path(a.soundtrack).resolve())
        audio.setdefault("mode", "soundtrack")
    if a.soundtrack_start is not None:
        audio.setdefault("soundtrack", {})["start"] = a.soundtrack_start
    if a.snap:
        audio.setdefault("soundtrack", {})["snap_cuts_to_beats"] = True
    if a.voiceover:
        audio["voiceover"] = [{"file": str(Path(a.voiceover).resolve()), "at": 0.0}]
        audio.setdefault("mode", "voiceover")
    if a.clip_volume is not None:
        audio["clip_volume"] = a.clip_volume
    if a.target_lufs is not None:
        audio["target_lufs"] = a.target_lufs
    audio.setdefault("mode", "native")

    report = {"mode": audio["mode"]}
    st = audio.get("soundtrack") or {}
    if st.get("file"):
        y = load(st["file"], sr=22050, start=float(st.get("start", 0)))
        bpm, beats = tempo_and_beats(y, 22050)
        report["soundtrack"] = {"file": st["file"], "bpm": bpm, "beats_found": len(beats)}
        if st.get("snap_cuts_to_beats"):
            report["beat_snap"] = snap_to_beats(segs, beats, float(st.get("max_shift", 0.5)))
    first = probe(segs[0]["file"])
    w, h = (map(int, a.size.lower().split("x")) if a.size else (first["width"], first["height"]))
    parts = [{"file": s["file"], "in": s["in"], "out": s["out"]} for s in segs]
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        picture = Path(td) / "picture.mp4"
        film_dur = render_parts(parts, picture, even(w), even(h), fps=a.fps)
        mode, clip_vol = mix_audio(picture, out, audio, film_dur, td)
    t, timeline = 0.0, []
    for s in segs:
        d = s["out"] - s["in"]
        timeline.append({"film_start": round(t, 4), "film_end": round(t + d, 4), "scene": s["scene"], "clip": s["file"],
                         "clip_in": round(s["in"], 4), "clip_out": round(s["out"], 4), "speed": 1.0})
        t += d
    meta = {"film": str(out.resolve()), "duration": round(probe(out)["duration"], 3), "fps": a.fps, "size": [even(w), even(h)],
            "audio": {**audio, "clip_volume": clip_vol}, "segments": timeline}
    tl = out.with_suffix(".timeline.json")
    tl.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    report.update({"film": str(out), "timeline": str(tl), "duration": meta["duration"], "expected": round(t, 3),
                   "loudness": loudness(out)})
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
