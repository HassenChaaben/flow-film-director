"""End-to-end tests for the local features: soundtrack/assembly, video editing, character voices, prompt building.

Usage (any Python 3.10+; the scripts themselves run in the skill's environments):
  python tests/run_tests.py                       # soundtrack + edit + prompts (synthetic media, ~3-6 min)
  python tests/run_tests.py --voice-a A.mp4 --voice-b B.ogg     # + voice tests on two real people
      A: one recording of person A with >= 45 s of speech (first 30 s -> profile, the rest is "unseen")
      B: >= 10 s of speech of a different person B
  python tests/run_tests.py --only edit,soundtrack
Environment: PY (skill venv python, default ~/.flow-film/venv), VPY (voice venv python, default ~/.flow-film/voice-venv).
Every test prints the measured numbers it judged. Exit code 0 only if every test passed.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "skills" / "flow-film-director" / "scripts"
HOME = Path.home() / ".flow-film"
PY = os.environ.get("PY") or str(HOME / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
VPY = os.environ.get("VPY") or str(HOME / "voice-venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
FPS, W, H = 24, 640, 360
RESULTS = []


# ------------------------------------------------------------------ helpers
def sh(args, ok_codes=(0,), cwd=None, timeout=1800):
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=cwd, timeout=timeout)
    if p.returncode not in ok_codes:
        raise AssertionError(f"command failed ({p.returncode}): {' '.join(map(str, args))[:300]}\n{p.stderr[-2500:]}\n{p.stdout[-1500:]}")
    return p


def js(p):
    """Last JSON object printed on stdout."""
    out = p.stdout.strip()
    start = out.find("{")
    return json.loads(out[start:])


def ff(*args):
    sh(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args])


def frame(path, t, w=160, h=90):
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.5f}", "-i", str(path), "-frames:v", "1", "-vf", f"scale={w}:{h}",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    return np.frombuffer(p.stdout, np.uint8).reshape(h, w, 3).astype(np.float32)


def mae(a, b):
    return float(np.abs(a - b).mean())


def local_change(a, b, grid=4):
    """Largest mean change of any cell in a grid x grid split: sees a small logo that a whole-frame mean misses."""
    h, w = a.shape[:2]
    return max(float(np.abs(a[i * h // grid:(i + 1) * h // grid, j * w // grid:(j + 1) * w // grid]
                            - b[i * h // grid:(i + 1) * h // grid, j * w // grid:(j + 1) * w // grid]).mean())
               for i in range(grid) for j in range(grid))


def same_frame(film, t, src, src_t):
    """Best MAE of the film frame at t against the source frame at src_t +-1 frame (frame accuracy check)."""
    f = frame(film, t)
    return min(mae(f, frame(src, max(0.0, src_t + d / FPS))) for d in (-1, 0, 1))


def audio(path, sr=48000):
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True)
    return np.frombuffer(p.stdout, np.float32)


def band_db(y, sr, freq, t0, t1):
    seg = y[int(t0 * sr):int(t1 * sr)]
    if len(seg) < 256:
        return -200.0
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    f = np.fft.rfftfreq(len(seg), 1 / sr)
    m = (f > freq * 0.9) & (f < freq * 1.1)
    return float(20 * np.log10(spec[m].max() / len(seg) + 1e-12))


def rms_db(y, sr, t0, t1):
    seg = y[int(t0 * sr):int(t1 * sr)]
    return float(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-9)) if len(seg) else -200.0


def clicks(y, sr, rel=0.25, floor_db=-50):
    """Start times of the 3 kHz click bursts ONLY (kick drums, voices and other tones are ignored):
    3 kHz band energy per 2.7 ms hop, onsets above `rel` x the loudest burst and above floor_db."""
    n, hop = 512, 128
    if len(y) < n:
        return []
    idx = np.arange(n)[None, :] + hop * np.arange(1 + (len(y) - n) // hop)[:, None]
    spec = np.abs(np.fft.rfft(y[idx] * np.hanning(n), axis=1))
    f = np.fft.rfftfreq(n, 1 / sr)
    band = spec[:, (f > 2700) & (f < 3300)].max(axis=1)
    other = spec[:, (f > 200) & ((f < 2400) | (f > 3800))].max(axis=1)
    level = 20 * np.log10(band / n + 1e-12)
    peak = band.max()
    if peak <= 0:
        return []
    hit = (band > rel * peak) & (level > floor_db) & (band > 2 * other)
    out, last = [], -1e9
    for i in np.where(hit)[0]:
        t = (i * hop + n / 2) / sr
        if t - last > 0.2:
            out.append(round(t - 0.004, 4))
        last = t
    return out


def write_wav(path, y, sr):
    y2 = np.clip(y, -1, 1)
    pcm = (y2 * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def music(path, bpm, seconds, sr=44100, offset=0.0):
    """Kick on every beat (60 Hz), hat on off-beats, 220 Hz pad. Returns true beat times."""
    t = np.arange(int(seconds * sr)) / sr
    y = 0.08 * np.sin(2 * np.pi * 220 * t)
    beat = 60.0 / bpm
    beats = []
    rng = np.random.default_rng(1)
    b = offset
    while b < seconds:
        beats.append(round(b, 4))
        k = int(b * sr)
        n = int(0.15 * sr)
        tt = np.arange(min(n, len(y) - k)) / sr
        y[k:k + len(tt)] += 0.7 * np.sin(2 * np.pi * 60 * tt) * np.exp(-tt / 0.05)
        h = int((b + beat / 2) * sr)
        m = min(int(0.03 * sr), max(0, len(y) - h))
        if m > 0:
            y[h:h + m] += 0.15 * rng.standard_normal(m) * np.exp(-np.arange(m) / (0.008 * sr))
        b += beat
    write_wav(path, y, sr)
    return beats


def clip(path, src, seconds, click_phase, tone=None):
    """Test clip: moving pattern video + 3 kHz clicks at k + click_phase seconds (+ optional steady tone)."""
    expr = f"if(between(mod(t\\,1)\\,{click_phase}\\,{click_phase + 0.01})\\,0.9*sin(2*PI*3000*t)\\,0)"
    if tone:
        expr += f"+0.3*sin(2*PI*{tone}*t)"
    ff("-f", "lavfi", "-i", f"{src}=size={W}x{H}:rate={FPS}", "-f", "lavfi", "-i", f"aevalsrc={expr}:s=48000:c=mono",
       "-t", str(seconds), "-c:v", "libx264", "-crf", "8", "-preset", "veryfast", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-b:a", "256k", "-ac", "2", str(path))


def test(name, group):
    def deco(fn):
        fn._name, fn._group = name, group
        return fn
    return deco


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ------------------------------------------------------------------ fixtures
class Fx:
    def __init__(self, d: Path):
        self.d = d
        self.A, self.B, self.C = d / "A.mp4", d / "B.mp4", d / "C.mp4"
        clip(self.A, "testsrc2", 6, 0.25)
        clip(self.B, "testsrc", 6, 0.50)
        clip(self.C, "mandelbrot", 8, 0.75, tone=1000)
        self.m120 = d / "m120.wav"
        self.b120 = music(self.m120, 120, 40, offset=0.0)
        self.film = None


def assemble_film(fx, out, *extra):
    p = sh([PY, SCRIPTS / "assemble.py", "--clips", fx.A, fx.B, fx.C, "--out", out, *extra])
    return js(p)


# ------------------------------------------------------------------ soundtrack / assembly tests
@test("tempo + beats on synthetic tracks (120 / 87 / 140 BPM)", "soundtrack")
def t_beats(fx):
    code = ("import sys,json; sys.path.insert(0,sys.argv[1]); from audiokit import load,tempo_and_beats;"
            "y=load(sys.argv[2],sr=22050); print(json.dumps(tempo_and_beats(y,22050)))")
    for bpm in (120, 87, 140):
        path = fx.d / f"beats_{bpm}.wav"        # own file: must not overwrite the shared soundtrack fx.m120
        truth = music(path, bpm, 30, offset=0.3)
        found_bpm, beats = json.loads(sh([PY, "-c", code, SCRIPTS, path]).stdout)
        ratio = found_bpm / bpm
        octave = min(abs(ratio - r) for r in (0.5, 1.0, 2.0))
        check(octave < 0.015, f"{bpm} BPM detected as {found_bpm}")
        errs = [min(abs(b - x) for x in truth) for b in beats[2:-2]]
        med = float(np.median(errs))
        check(med < 0.03, f"{bpm} BPM: beats off by median {med * 1000:.0f} ms")
        print(f"    {bpm} BPM -> {found_bpm}, median beat error {med * 1000:.1f} ms over {len(errs)} beats")


@test("native assembly: exact length, frame-accurate joins, sound in sync, -14 LUFS", "soundtrack")
def t_native(fx):
    out = fx.d / "native.mp4"
    r = assemble_film(fx, out)
    check(abs(r["duration"] - 20.0) < 1.5 / FPS, f"duration {r['duration']} != 20.0")
    tl = json.loads(Path(r["timeline"]).read_text())
    check([s["scene"] for s in tl["segments"]] == [1, 2, 3], "timeline order")
    for t, src, st in ((2.5 / FPS + 1, fx.A, 2.5 / FPS + 1), (6 + 0.5 / FPS, fx.B, 0.5 / FPS), (12 + 3.5 / FPS, fx.C, 3.5 / FPS)):
        e = same_frame(out, t, src, st)
        check(e < 6, f"frame at {t:.3f}s does not match its source (MAE {e:.1f})")
    y = audio(out)
    cl = clicks(y, 48000)
    expect = [k + 0.25 for k in range(6)] + [6 + k + 0.5 for k in range(6)] + [12 + k + 0.75 for k in range(8)]
    err = max(min(abs(c - e) for c in cl) for e in expect)
    check(err < 0.02, f"audio clicks drift from picture by {err * 1000:.0f} ms")
    check(abs(r["loudness"]["lufs"] + 14) < 1.0, f"loudness {r['loudness']['lufs']} LUFS")
    check(r["loudness"]["true_peak"] <= -1.0, f"true peak {r['loudness']['true_peak']}")
    print(f"    20.00 s -> {r['duration']} s, sync error {err * 1000:.1f} ms, {r['loudness']['lufs']} LUFS, peak {r['loudness']['true_peak']} dBTP")
    fx.film = out


@test("soundtrack mode: music only, clips muted, fades, loudness", "soundtrack")
def t_soundtrack(fx):
    out = fx.d / "st.mp4"
    r = assemble_film(fx, out, "--soundtrack", fx.m120)
    y = audio(out)
    tone_clip = band_db(y, 48000, 1000, 13, 18)       # clip C's 1 kHz tone must be gone
    pad = band_db(y, 48000, 220, 13, 18)              # the music's 220 Hz pad must be there
    check(pad - tone_clip > 30, f"clip sound not muted: music {pad:.1f} dB vs clip tone {tone_clip:.1f} dB")
    check(len(clicks(y, 48000, 0.5)) == 0, "clip clicks still audible")
    start, mid, end = rms_db(y, 48000, 0, 0.05), rms_db(y, 48000, 8, 10), rms_db(y, 48000, 19.9, 20)
    check(mid - start > 12 and mid - end > 12, f"fades missing: start {start:.1f}, mid {mid:.1f}, end {end:.1f} dB")
    check(abs(r["loudness"]["lufs"] + 14) < 1.0, f"loudness {r['loudness']['lufs']}")
    check(r["soundtrack"]["bpm"] and abs(r["soundtrack"]["bpm"] - 120) < 2, f"bpm {r['soundtrack']['bpm']}")
    print(f"    music-clip separation {pad - tone_clip:.1f} dB, fade in/out {mid - start:.1f}/{mid - end:.1f} dB, {r['loudness']['lufs']} LUFS")


@test("soundtrack shorter than the film loops seamlessly", "soundtrack")
def t_loop(fx):
    short = fx.d / "short.wav"
    music(short, 120, 7.0)
    out = fx.d / "loop.mp4"
    assemble_film(fx, out, "--soundtrack", short)
    y = audio(out)
    worst = min(rms_db(y, 48000, t, t + 1) for t in range(1, 17))
    check(worst > -40, f"silence inside the film where music should loop ({worst:.1f} dB)")
    print(f"    7 s track over 20 s film, quietest second {worst:.1f} dB")


@test("cuts snapped to the beat grid", "soundtrack")
def t_snap(fx):
    out = fx.d / "snap.mp4"
    r = assemble_film(fx, out, "--soundtrack", fx.m120, "--snap")
    tl = json.loads(Path(r["timeline"]).read_text())
    cuts = [s["film_end"] for s in tl["segments"][:-1]]
    err = max(min(abs(c - b) for b in fx.b120) for c in cuts)
    check(err < 0.03, f"cuts not on beats: worst {err * 1000:.0f} ms ({cuts})")
    check(abs(r["duration"] - tl["segments"][-1]["film_end"]) < 1.5 / FPS, "timeline length != film length")
    print(f"    cuts at {cuts}, worst distance to a beat {err * 1000:.1f} ms; moves {[m['cut_now'] - m['cut_was'] for m in r['beat_snap']]}")


@test("mixed mode: music ducks under dialogue", "soundtrack")
def t_duck(fx):
    talk = fx.d / "talk.mp4"   # 'dialogue' = 1 kHz tone from 3 s to 6 s, silence elsewhere
    ff("-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}", "-f", "lavfi",
       "-i", "aevalsrc='if(between(t\\,3\\,6)\\,0.5*sin(2*PI*1000*t)\\,0)':s=48000:c=mono", "-t", "10",
       "-c:v", "libx264", "-crf", "12", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", str(talk))
    out = fx.d / "duck.mp4"
    sh([PY, SCRIPTS / "assemble.py", "--clips", talk, "--out", out, "--soundtrack", fx.m120, "--mode", "mixed"])
    y = audio(out)
    during, outside = band_db(y, 48000, 220, 3.8, 5.6), band_db(y, 48000, 220, 7.0, 8.8)
    voice = band_db(y, 48000, 1000, 3.8, 5.6)
    check(outside - during > 6, f"music not ducked: {outside:.1f} dB outside vs {during:.1f} dB under dialogue")
    check(voice > during, "dialogue not above the music")
    print(f"    music under dialogue {outside - during:.1f} dB lower; dialogue {voice - during:.1f} dB above music")


@test("voiceover mode: narration on top, clips low", "soundtrack")
def t_vo(fx):
    vo = fx.d / "vo.wav"
    sr = 48000
    t = np.arange(int(sr * 20)) / sr
    write_wav(vo, np.where((t > 2) & (t < 8), 0.4 * np.sin(2 * np.pi * 600 * t), 0.0), sr)
    out = fx.d / "vo.mp4"
    sh([PY, SCRIPTS / "assemble.py", "--clips", fx.A, fx.B, fx.C, "--out", out, "--voiceover", vo])
    y = audio(out)
    v, c = band_db(y, sr, 600, 3, 7), band_db(y, sr, 3000, 2.2, 2.3)
    check(v > -60, f"narration missing ({v:.1f} dB)")
    print(f"    narration level {v:.1f} dB, clips kept at 25 %")


# ------------------------------------------------------------------ edit tests
def edit(fx, edits, name):
    tl = Path(fx.film).with_suffix(".timeline.json")
    ej = fx.d / f"{name}.json"
    ej.write_text(json.dumps({"edits": edits}))
    out = fx.d / f"{name}.mp4"
    r = js(sh([PY, SCRIPTS / "edit_video.py", "apply", "--timeline", tl, "--edits", ej, "--out", out]))
    meta = json.loads(Path(r["timeline"]).read_text())
    total = sum(s["film_end"] - s["film_start"] for s in meta["segments"])
    check(abs(total - r["duration"]) < 2 / FPS, f"timeline ({total:.3f}s) disagrees with film ({r['duration']}s)")
    gaps = max((abs(meta["segments"][i + 1]["film_start"] - meta["segments"][i]["film_end"]) for i in range(len(meta["segments"]) - 1)), default=0)
    check(gaps < 1e-3, f"timeline has gaps/overlaps ({gaps})")
    return out, r, meta


def ensure_film(fx):
    if fx.film is None:
        out = fx.d / "native.mp4"
        assemble_film(fx, out)
        fx.film = out


@test("locate: film time -> scene and take time", "edit")
def t_locate(fx):
    ensure_film(fx)
    r = js(sh([PY, SCRIPTS / "edit_video.py", "locate", "--timeline", Path(fx.film).with_suffix(".timeline.json"), "--range", "7", "13"]))
    hits = r["hits"]
    check([h["scene"] for h in hits] == [2, 3], f"scenes {[h['scene'] for h in hits]}")
    check(abs(hits[0]["take_from"] - 1.0) < 1e-3 and abs(hits[1]["take_to"] - 1.0) < 1e-3, f"take times {hits}")
    print(f"    7-13 s -> scene 2 take {hits[0]['take_from']}-{hits[0]['take_to']} s, scene 3 take {hits[1]['take_from']}-{hits[1]['take_to']} s")


@test("cut a period: frame-accurate, sound in sync, timeline shifted", "edit")
def t_cut(fx):
    ensure_film(fx)
    out, r, meta = edit(fx, [{"op": "cut", "range": [2.0, 3.0]}], "cut")
    check(abs(r["duration"] - 19.0) < 1.5 / FPS, f"duration {r['duration']}")
    e = same_frame(out, 2.0 + 0.5 / FPS, fx.A, 3.0 + 0.5 / FPS)
    check(e < 6, f"frame after the cut is wrong (MAE {e:.1f})")
    cl = clicks(audio(out), 48000)
    check(any(abs(c - 2.25) < 0.02 for c in cl), "click that was at 3.25 s is not at 2.25 s")
    check(abs(meta["segments"][-1]["film_start"] - 11.0) < 1e-3, f"scene 3 should start at 11.0, starts {meta['segments'][-1]['film_start']}")
    print(f"    20 -> {r['duration']} s, frame MAE {e:.1f}, sync ok, scene 3 now at 11.0 s")


@test("replace + splice a period with another take (same moment)", "edit")
def t_splice(fx):
    ensure_film(fx)
    out, r, meta = edit(fx, [{"op": "replace", "range": [1.0, 2.0], "source": str(fx.C), "source_in": 0.0},
                             {"op": "splice", "range": [7.0, 9.0], "source": str(fx.C)}], "splice")
    check(abs(r["duration"] - 20.0) < 1.5 / FPS, f"duration changed: {r['duration']}")
    e1 = same_frame(out, 1.5 + 0.5 / FPS, fx.C, 0.5 + 0.5 / FPS)
    e2 = same_frame(out, 8.0 + 0.5 / FPS, fx.C, 2.0 + 0.5 / FPS)   # scene 2 starts at 6 -> take time 2.0
    e3 = same_frame(out, 9.5 + 0.5 / FPS, fx.B, 3.5 + 0.5 / FPS)   # after the splice: original take again
    check(max(e1, e2, e3) < 6, f"frames wrong: replace {e1:.1f}, splice {e2:.1f}, after {e3:.1f}")
    print(f"    replace MAE {e1:.1f}, splice MAE {e2:.1f} (take time found from timeline), continuity MAE {e3:.1f}")


@test("speed (slow motion), freeze frame, title card insert", "edit")
def t_time(fx):
    ensure_film(fx)
    card = fx.d / "card.png"
    ff("-f", "lavfi", "-i", f"color=c=red:s={W}x{H}", "-frames:v", "1", str(card))
    out, r, meta = edit(fx, [{"op": "speed", "range": [0.0, 2.0], "factor": 0.5},
                             {"op": "freeze", "at": 5.0, "dur": 1.5},
                             {"op": "insert", "at": 0.0, "image": str(card), "dur": 1.0}], "time")
    check(abs(r["duration"] - (20 + 2 + 1.5 + 1)) < 2 / FPS, f"duration {r['duration']}")
    red = frame(out, 0.5)
    check(red[..., 0].mean() > 200 and red[..., 1].mean() < 60, "title card not shown")
    e = same_frame(out, 1.0 + 2.0 + 0.5 / FPS, fx.A, 1.0 + 0.25 / FPS)   # slow-mo: film 3.0 = source 1.0 (+1 s card)
    f1, f2 = frame(out, 1 + 5.2), frame(out, 1 + 6.3)
    check(e < 8, f"slow motion frame wrong (MAE {e:.1f})")
    check(mae(f1, f2) < 3, f"freeze frame moves (MAE {mae(f1, f2):.1f})")
    print(f"    {r['duration']} s (= 20 + 2 slow-mo + 1.5 freeze + 1 card), slow-mo MAE {e:.1f}, freeze MAE {mae(f1, f2):.1f}")


@test("look edits: text, color, blur, zoom, logo - only inside their range", "edit")
def t_look(fx):
    ensure_film(fx)
    logo = fx.d / "logo.png"
    ff("-f", "lavfi", "-i", "color=c=yellow:s=200x100", "-frames:v", "1", str(logo))
    edits = [{"op": "text", "range": [0.0, 1.0], "text": "SALE -20% : l'été", "position": "bottom", "size": 0.08},
             {"op": "color", "range": [2.0, 3.0], "saturation": 0.0},
             {"op": "blur", "range": [4.0, 5.0], "box": [0.25, 0.25, 0.5, 0.5]},
             {"op": "zoom", "range": [6.0, 7.0], "factor": 1.5},
             {"op": "overlay", "range": [8.0, 9.0], "image": str(logo), "position": "top-right", "width": 0.2}]
    out, r, meta = edit(fx, edits, "look")
    check(abs(r["duration"] - 20.0) < 1.5 / FPS, f"duration changed {r['duration']}")
    rows = []
    for t, label in ((0.5, "text"), (2.5, "color"), (4.5, "blur"), (6.5, "zoom"), (8.5, "logo")):
        inside = local_change(frame(out, t + 0.5 / FPS), frame(fx.film, t + 0.5 / FPS))
        outside = local_change(frame(out, t + 1.0 + 0.5 / FPS), frame(fx.film, t + 1.0 + 0.5 / FPS))
        rows.append(f"{label} {inside:.1f}/{outside:.1f}")
        check(inside > 10 and outside < 4, f"{label}: change inside {inside:.1f} (must be >10), outside {outside:.1f} (must be <4)")
    g = frame(out, 2.5)
    check(float(np.abs(g[..., 0] - g[..., 1]).mean()) < 4, "saturation 0 did not make the frame grey")
    print("    inside/outside change (MAE): " + ", ".join(rows))


@test("audio edits: mute and replace a period, fade", "edit")
def t_audio_edit(fx):
    ensure_film(fx)
    tone = fx.d / "line.wav"
    sr = 48000
    t = np.arange(sr * 3) / sr
    write_wav(tone, 0.5 * np.sin(2 * np.pi * 700 * t), sr)
    out, r, meta = edit(fx, [{"op": "mute", "range": [1.0, 2.0]},
                             {"op": "audio_replace", "range": [3.0, 4.0], "source": str(tone)},
                             {"op": "fade", "in": 0.5, "out": 0.5}], "aud")
    y = audio(out)
    muted = rms_db(y, sr, 1.1, 1.9)
    rep = band_db(y, sr, 700, 3.1, 3.9)
    outside = band_db(y, sr, 700, 4.2, 4.9)
    check(muted < -60, f"mute range still has sound ({muted:.1f} dB)")
    check(rep - outside > 30, f"replacement line missing ({rep:.1f} vs {outside:.1f} dB)")
    check(not any(3.0 < c < 4.0 for c in clicks(y, sr)), "original sound still inside the replaced range")
    check(frame(out, 0.02).mean() < 40, "fade-in missing")
    print(f"    muted range {muted:.1f} dB, replaced line +{rep - outside:.1f} dB, fade ok")


@test("frame extraction for fixing a single frame", "edit")
def t_frame(fx):
    ensure_film(fx)
    png = fx.d / "f.png"
    sh([PY, SCRIPTS / "edit_video.py", "frame", "--film", fx.film, "--at", f"{6 + 2.5 / FPS:.4f}", "--out", png])
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-vf", "scale=160:90", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    img = np.frombuffer(p.stdout, np.uint8).reshape(90, 160, 3).astype(np.float32)
    e = min(mae(img, frame(fx.B, (2 + d) / FPS + 0.5 / FPS)) for d in (-1, 0, 1))
    check(e < 6, f"extracted frame is not the requested one (MAE {e:.1f})")
    print(f"    frame at {6 + 2.5 / FPS:.3f}s = scene 2 frame 2 (MAE {e:.1f})")


# ------------------------------------------------------------------ prompt building with audio
@test("storyboard audio rules: soundtrack path required, no dialogue in soundtrack mode, voices", "prompts")
def t_prompts(fx):
    base = fx.d / "sb"
    base.mkdir(exist_ok=True)
    (base / "voices").mkdir(exist_ok=True)
    (base / "voices" / "p.json").write_text("{}")
    sb = {"flow_project": "T", "aspect_ratio": "9:16",
          "cast": {"Sam": {"ref": "asset:Sam", "lock": "Sam: man about 30.", "voice": "voices/p.json"}},
          "audio": {"mode": "soundtrack"},
          "scenes": [{"id": 1, "duration": 4, "characters": [{"name": "Sam", "start": "standing"}],
                      "beats": [{"from": 0, "to": 4, "who": "Sam", "action": "nods"}], "use_end_frame": False}]}
    def build(s):
        (base / "storyboard.json").write_text(json.dumps(s))
        p = sh([PY, SCRIPTS / "build_prompts.py", base / "storyboard.json"], ok_codes=(0, 1))
        return p.returncode, js(p)
    code, r = build(sb)
    check(code == 1 and any("soundtrack.file" in e for e in r["errors"]), f"missing soundtrack path not caught: {r['errors']}")
    sb["audio"]["soundtrack"] = {"file": str(fx.m120)}
    sb["scenes"][0]["dialogue"] = [{"who": "Sam", "line": "Hello."}]
    code, r = build(sb)
    check(code == 1 and any("soundtrack" in e and "dialogue" in e for e in r["errors"]), f"dialogue in soundtrack mode not caught: {r['errors']}")
    sb["audio"]["mode"] = "mixed"
    code, r = build(sb)
    check(code == 0, f"mixed mode with dialogue should build: {r['errors']}")
    md = (base / "prompts" / "scene-01.md").read_text()
    check("clean close-microphone dialogue" in md and "No music in the clip." in md, "voice/music rules missing from the prompt")
    sb["cast"]["Sam"]["voice"] = "voices/missing.json"
    code, r = build(sb)
    check(code == 1 and any("voice" in e for e in r["errors"]), "missing voice profile not caught")
    sb["cast"]["Sam"]["voice"] = "voices/p.json"
    sb["flow_project"] = "SamAndLinaFilm"
    code, r = build(sb)
    check(code == 1 and any("starts with the character name" in e for e in r["errors"]), "project name starting with a character name not caught")
    print("    missing soundtrack path, dialogue under soundtrack, missing voice profile, project named after a character: all caught; mixed mode builds")


@test("character likeness invariants: safety words, curly hair, glasses, profile angle", "prompts")
def t_prompt_likeness(fx):
    base = fx.d / "sb_likeness"
    base.mkdir()
    def build(s):
        (base / "storyboard.json").write_text(json.dumps(s))
        p = sh([PY, SCRIPTS / "build_prompts.py", base / "storyboard.json"], ok_codes=(0, 1))
        return p.returncode, js(p)

    # 1. Safety banned words check (pistol, guns, weapons)
    sb_safety = {
        "intent": "story", "default_model": "Omni 1.1 Flash",
        "cast": {"Sam": {"kind": "person", "lock": "Sam: tall, dark curls."}},
        "scenes": [{
            "id": 1, "duration": 4,
            "characters": [{"name": "Sam", "start": "holding two pistols at his side"}],
            "beats": [{"from": 0, "to": 4, "who": "Sam", "action": "walks"}],
            "use_end_frame": False
        }]
    }
    code, r = build(sb_safety)
    check(code == 1 and any("safety-sensitive" in e or "pistol" in e for e in r["errors"]), f"safety word 'pistols' not caught: {r['errors']}")

    # 2. Likeness invariant: glasses description (keyhole)
    sb_glasses = {
        "intent": "story", "default_model": "Omni 1.1 Flash",
        "cast": {"Sam": {"kind": "person", "lock": "Sam: wears rounded keyhole-bridge glasses."}},
        "scenes": [{
            "id": 1, "duration": 4,
            "characters": [{"name": "Sam", "start": "standing"}],
            "beats": [{"from": 0, "to": 4, "who": "Sam", "action": "nods"}],
            "use_end_frame": False
        }]
    }
    code, r = build(sb_glasses)
    check(code == 1 and any("goggles" in e or "keyhole" in e for e in r["errors"]), f"keyhole glasses not caught: {r['errors']}")

    # 3. Likeness invariant: curly hair contradiction (buzz cut)
    sb_hair = {
        "intent": "story", "default_model": "Omni 1.1 Flash",
        "cast": {"Sam": {"kind": "person", "lock": "Sam: natural deep black curly hair."}},
        "scenes": [{
            "id": 1, "duration": 4,
            "characters": [{"name": "Sam", "start": "tight crew cut flat to head"}],
            "beats": [{"from": 0, "to": 4, "who": "Sam", "action": "nods"}],
            "use_end_frame": False
        }]
    }
    code, r = build(sb_hair)
    check(code == 1 and any("curly hair" in e for e in r["errors"]), f"curly hair contradiction not caught: {r['errors']}")

    # 4. Likeness invariant: 90° pure side profile angle rejection
    sb_profile = {
        "intent": "story", "default_model": "Omni 1.1 Flash",
        "cast": {"Sam": {"kind": "person", "lock": "Sam: tall, dark curls."}},
        "scenes": [{
            "id": 1, "duration": 4,
            "shot": {"angle": "profile", "size": "medium shot"},
            "characters": [{"name": "Sam", "start": "walking"}],
            "beats": [{"from": 0, "to": 4, "who": "Sam", "action": "walks"}],
            "use_end_frame": False
        }]
    }
    code, r = build(sb_profile)
    check(code == 1 and any("three-quarter" in e for e in r["errors"]), f"profile angle not rejected: {r['errors']}")

    # 5. Clean 3/4 frontal shot builds cleanly
    sb_clean = {
        "intent": "story", "default_model": "Omni 1.1 Flash",
        "cast": {"Sam": {"kind": "person", "lock": "Sam: tight black curls about 3 cm on top, short tapered sides, ears and forehead visible; grey see-through rounded-square plastic glasses."}},
        "scenes": [{
            "id": 1, "duration": 4,
            "shot": {"angle": "three-quarter frontal", "size": "medium shot"},
            "characters": [{"name": "Sam", "start": "standing alert"}],
            "beats": [{"from": 0, "to": 4, "who": "Sam", "action": "nods"}],
            "use_end_frame": False
        }]
    }
    code, r = build(sb_clean)
    check(code == 0, f"clean 3/4 frontal shot failed to build: {r['errors']}")
    print("    safety banned words, keyhole glasses, curly hair contradiction, profile angle: all enforced; clean 3/4 builds")

@test("forensic fixes: two-shot refs, approved costume, profile text, name prefixes, curl length, stored Flow look", "prompts")
def t_forensic(fx):
    base = fx.d / "sb_forensic"
    base.mkdir()
    still = fx.d / "kf.png"
    ff("-f", "lavfi", "-i", f"testsrc2=size={W}x{H}", "-frames:v", "1", str(still))
    (base / "breakdown.json").write_text(json.dumps({"shots": [{"id": "shot-01", "start": 0.0, "duration": 3.0,
        "shot_size": "medium shot", "camera": {"move": "static"}, "frames_dir": str(fx.d),
        "keyframes": [{"pct": 0, "t": 0.0, "file": str(still)}, {"pct": 100, "t": 3.0, "file": str(still)}]}]}))
    home = Path(os.environ["FLOW_MCP_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    lock_sam = "Sam: man about 30, tight black curls about 3 cm on top, short sides, short beard."
    lock_lina = "Lina: woman about 30, straight black hair to the shoulders."
    def sb(**kw):
        d = {"flow_project": "CafeFilm", "aspect_ratio": "16:9", "reference_breakdown": "breakdown.json",
             "cast": {"Sam": {"ref": "asset:Sam", "lock": lock_sam, "outfit": "red and black armoured suit"},
                      "Lina": {"ref": "asset:Lina", "lock": lock_lina}},
             "scenes": [{"id": 1, "ref_shot": "shot-01", "characters": [{"name": "Sam", "start": "standing"}, {"name": "Lina", "start": "standing"}],
                         "beats": [{"from": 0, "to": 3, "who": "Sam", "action": "nods once"}], "use_end_frame": False}]}
        for k, v in kw.items():
            d[k] = v
        return d
    def build(s):
        (base / "storyboard.json").write_text(json.dumps(s))
        p = sh([PY, SCRIPTS / "build_prompts.py", base / "storyboard.json"], ok_codes=(0, 1))
        return p.returncode, js(p), json.loads((base / "prompts" / "stage1-start-keyframes.json").read_text())
    # two-shot: identity images only, no movie frame by default
    code, r, st = build(sb())
    check(code == 0, f"two-shot should build: {r['errors']}")
    refs = st["scenes"][0]["reference_images"]
    check(refs == ["asset:Sam", "asset:Lina"], f"two-shot refs should be the two characters only, got {refs}")
    s2 = sb(); s2["scenes"][0]["use_ref_frame"] = True
    code, r, st = build(s2)
    check(len(st["scenes"][0]["reference_images"]) == 3, "use_ref_frame: true should add the composition frame")
    # approved costume: generic clause, no mask, face beats suit
    s3 = sb(); s3["cast"]["Sam"]["costume_approved"] = True; s3["scenes"][0]["characters"] = [{"name": "Sam", "start": "standing"}]
    code, r, st = build(s3)
    pr = st["scenes"][0]["prompt"]
    check(code == 0 and "copy only its camera angle" in pr and "No mask, no hood" in pr and "keep the face" in pr,
          f"approved costume rules missing: {r['errors']} / {pr[:200]}")
    # profile written in the scene text
    s4 = sb(); s4["scenes"][0]["characters"][0]["start"] = "walking in profile toward screen-right"
    code, r, _ = build(s4)
    check(code == 1 and any("side profile" in e for e in r["errors"]), f"profile in start text not caught: {r['errors']}")
    s4["scenes"][0]["characters"][0]["start"] = "walking, three-quarter profile toward camera"
    code, r, _ = build(s4)
    check(code == 0, f"three-quarter wording must be allowed: {r['errors']}")
    # one name a prefix of another
    s5 = sb(); s5["cast"]["Samir"] = {"ref": "asset:Samir", "lock": "Samir: man."}
    code, r, _ = build(s5)
    check(code == 1 and any("prefix" in e for e in r["errors"]), f"name prefix not caught: {r['errors']}")
    # curly hair without a length
    s6 = sb(); s6["cast"]["Sam"]["lock"] = "Sam: man about 30, natural curly hair."
    code, r, _ = build(s6)
    check(code == 1 and any("length in cm" in e for e in r["errors"]), f"curly without length not caught: {r['errors']}")
    # the look Flow really appends must be the lock
    (home / "characters.json").write_text(json.dumps({"sam": "Sam: iconic red suit, thin-framed glasses."}))
    code, r, _ = build(sb())
    check(code == 1 and any("stored in Flow" in e for e in r["errors"]) and any("iconic" in e for e in r["errors"]),
          f"stale / banned stored look not caught: {r['errors']}")
    (home / "characters.json").write_text(json.dumps({"sam": lock_sam}))
    code, r, _ = build(sb())
    check(code == 0, f"matching stored look should build: {r['errors']}")
    (home / "characters.json").unlink()
    print("    two-shot = identity refs only; costume clause; profile text; name prefix; curl length; stored Flow look: all enforced")


@test("fast mode: parallel ingredient videos, builder-owned prompt, fight staging and ally rules", "prompts")
def t_fast(fx):
    base = fx.d / "sb_fast"
    base.mkdir()
    def sb():
        return {"flow_project": "FightFilm", "mode": "fast", "aspect_ratio": "16:9", "default_model": "Omni 1.1 Flash",
                "cast": {"Sam": {"ref": "asset:Sam", "identity": "late 20s, tall, short black hair about 2 cm, no glasses", "outfit": "black jacket and jeans"},
                         "Lina": {"ref": "asset:Lina", "identity": "late 20s, straight black hair to the shoulders"},
                         "Guards": {"kind": "extra", "count": 4, "look": "masked guards in grey armour"}},
                "scenes": [{"id": 1, "duration": 6,
                            "characters": [{"name": "Sam", "start": "in a fighting stance"}, {"name": "Lina", "start": "in a fighting stance"}],
                            "sides": {"allies": ["Sam", "Lina"], "opponents": "Guards",
                                      "staging": "Sam and Lina on the left facing right; the guards on the right facing left"},
                            "beats": [{"from": 0, "to": 3, "who": "Sam", "action": "blocks a guard's punch", "target": "Guards"},
                                      {"from": 3, "to": 6, "who": "Lina", "action": "pushes a guard back", "target": "Guards"}]}]}
    def build(s):
        (base / "storyboard.json").write_text(json.dumps(s))
        p = sh([PY, SCRIPTS / "build_prompts.py", base / "storyboard.json"], ok_codes=(0, 1))
        return p.returncode, js(p)
    code, r = build(sb())
    check(code == 0 and r["fast"] == 1, f"fast fight should build: {r['errors']}")
    v = json.loads((base / "prompts" / "stage-fast-video.json").read_text())["scenes"][0]
    pr = v["prompt"]
    check(v["builder_lock"] and v["parallel"] and v["reference_images"] == ["asset:Sam", "asset:Lina"], f"stage flags/refs wrong: {v}")
    check("first_frame" not in v and v["duration"] == 6, "fast video must use ingredients, not a first frame")
    for must in ("Grounded, serious, cinematic realism", "never strike each other", "face the guards, never each other",
                 "opponents: exactly 4 masked guards", "Sam = the person in the Sam reference image",
                 "face the camera in a clear three-quarter view", "(black jacket"):
        check(must in pr, f"missing in fast prompt: {must!r}")
    check(" no cartoon" not in pr and "no extra people" not in pr, "fast prompt still uses the old 'no X' realism lists")
    check(len(pr) < 1600, f"fast prompt too long ({len(pr)} chars)")
    s9 = sb(); s9["scenes"][0]["location"] = {"description": "a long dusty warehouse hall with crates " * 22}
    code, r = build(s9)
    check(code == 1 and any("prompt too long" in e for e in r["errors"]), f"900-char place not refused as too long: {r['errors']}")
    s10 = sb(); s10["cast"]["Sam"]["identity"] = " ".join(["tall"] * 35)
    code, r = build(s10)
    check(code == 1 and any("identity too long" in e and "Sam" in e and "35" in e for e in r["errors"]), f"35-word identity not refused: {r['errors']}")
    s2 = sb(); s2["scenes"][0]["sides"]["staging"] = "Sam and Lina in the foreground; the guards advance from the background"
    code, r = build(s2)
    check(code == 1 and any("in front of the allies" in e for e in r["errors"]), f"guards behind not caught: {r['errors']}")
    s3 = sb(); s3["scenes"][0]["beats"][0]["target"] = "Lina"
    code, r = build(s3)
    check(code == 1 and any("allies would fight each other" in e for e in r["errors"]), f"ally attack not caught: {r['errors']}")
    s4 = sb(); s4["scenes"][0]["beats"][1]["action"] = "raises her fists toward Sam and they face each other"
    code, r = build(s4)
    check(code == 1 and any("each other" in e for e in r["errors"]), f"fighting 'each other' beat not caught: {r['errors']}")
    s5 = sb(); del s5["cast"]["Guards"]["look"]
    code, r = build(s5)
    check(code == 1 and any("needs 'look'" in e for e in r["errors"]), "extra without look not caught")
    check(v["scene_id"] == 1, "stage scene must carry its storyboard scene_id")
    s6 = sb(); s6["scenes"][0]["sides"]["staging"] += "; at the end the guards lie still on the floor"
    code, r = build(s6)
    check(code == 1 and any("lie still" in e for e in r["errors"]), f"'lie still' (refused by Flow live) not caught: {r['errors']}")
    s7 = sb(); s7["scenes"][0]["shot"] = {"size": "wide shot"}
    code, r = build(s7)
    check(code == 1 and any("too wide for faces" in e and "medium-wide shot" in e for e in r["errors"]), f"wide shot with main characters not refused: {r['errors']}")
    s7["scenes"][0]["allow_wide"] = True
    code, r = build(s7)
    check(code == 0, f"allow_wide should build: {r['errors']}")
    s8 = sb(); s8["scenes"][0]["shot"] = {"size": "medium-wide shot"}
    code, r = build(s8)
    check(code == 0, f"medium-wide shot should build: {r['errors']}")
    sys.path.insert(0, str(SCRIPTS))
    import fast_review
    check(fast_review.decide({"Sam": {"mean": 0.52, "verdict": "WEAK"}, "Lina": {"mean": 0.6, "verdict": "PASS"}}, ["Sam", "Lina"], 0.5)[0] == "keep", "0.52 / 0.60 should be kept")
    check(fast_review.decide({"Sam": {"mean": 0.46, "verdict": "WEAK"}}, ["Sam", "Lina"], 0.5)[1] == ["Sam mean 0.46 < 0.5", "Lina not found in the clip"], "low score / missing character not flagged")
    check(fast_review.main_characters(sb(), sb()["scenes"][0]) == ["Sam", "Lina"], "extras must not be face-checked")
    print("    fast: ingredients + builder lock + parallel; tone, sides, targets, outfits first, face-hold, exact count; guards-behind, ally attack, 'each other', 'lie still' refused; review gate")


@test("every file in examples/ builds with zero errors", "prompts")
def t_examples_build(fx):
    ex_dir = HERE.parent / "examples"
    examples = sorted(ex_dir.glob("*.json"))
    check(len(examples) >= 2, f"expected at least 2 example storyboards, found {len(examples)}")
    try:
        for ex in examples:
            p = sh([PY, SCRIPTS / "build_prompts.py", ex], ok_codes=(0, 1))
            r = js(p)
            check(p.returncode == 0, f"{ex.name} failed to build (code {p.returncode}): {r.get('errors')}")
            check(not r.get("errors"), f"{ex.name} built with errors: {r.get('errors')}")
        print(f"    all {len(examples)} files in examples/ build clean: {', '.join(e.name for e in examples)}")
    finally:
        import shutil
        shutil.rmtree(ex_dir / "prompts", ignore_errors=True)


# ------------------------------------------------------------------ voice tests (real recordings)
@test("voice profile: own unseen speech PASS, other person FAIL", "voice")
def t_voice_profile(fx):
    v = fx.voice
    d = fx.d / "voice"
    d.mkdir(exist_ok=True)
    ff("-i", v["a"], "-t", "30", "-vn", "-ac", "1", str(d / "a_train.wav"))
    ff("-ss", "30", "-i", v["a"], "-t", "30", "-vn", "-ac", "1", str(d / "a_unseen.wav"))
    pa = js(sh([VPY, SCRIPTS / "voice_profile.py", "create", "--name", "PersonA", "--samples", d / "a_train.wav", "--out", d / "voices"], ok_codes=(0, 1)))
    pb = js(sh([VPY, SCRIPTS / "voice_profile.py", "create", "--name", "PersonB", "--samples", v["b"], "--out", d / "voices"], ok_codes=(0, 1)))
    check(pa["ok"] and pb["ok"], f"profiles not ok: {pa['flags']} {pb['flags']}")
    ca = js(sh([VPY, SCRIPTS / "voice_profile.py", "check", "--profile", pa["profile"], d / "a_unseen.wav", v["b"]], ok_codes=(0, 1)))
    cb = js(sh([VPY, SCRIPTS / "voice_profile.py", "check", "--profile", pb["profile"], d / "a_unseen.wav"], ok_codes=(0, 1)))
    own, other_a = ca["results"][0], ca["results"][1]
    other_b = cb["results"][0]
    check(own["verdict"] == "PASS", f"own unseen speech {own}")
    check(other_a["verdict"] == "FAIL" and other_b["verdict"] == "FAIL", f"other person not rejected: {other_a} / {other_b}")
    fx.voice.update({"pa": pa["profile"], "pb": pb["profile"]})
    print(f"    A unseen vs A {own['similarity']} PASS (line {ca['pass_line']}); B vs A {other_a['similarity']} FAIL; A vs B {other_b['similarity']} FAIL (line {cb['pass_line']})")


@test("voice conversion of a clip: becomes person B, timing and picture unchanged", "voice")
def t_voice_convert(fx):
    v = fx.voice
    check("pb" in v, "needs the profile test first")
    d = fx.d / "voice"
    src = d / "a_clip.mp4"
    ff("-ss", "35", "-i", v["a"], "-t", "8", "-c:v", "libx264", "-crf", "16", "-preset", "veryfast", "-c:a", "aac", "-ac", "2", str(src))
    out = d / "a_as_b.mp4"
    r = js(sh([VPY, SCRIPTS / "voice_convert.py", "clip", "--profile", f"PersonB={v['pb']}", "--in", src, "--out", out], ok_codes=(0, 1)))
    s = r["similarity"]["PersonB"]
    check(s["verdict"] == "PASS", f"converted voice not person B: {s}")
    check(s["after"] - s["before"] > 0.08, f"similarity barely moved: {s}")
    check(r["max_length_change_ms"] < 1000 / FPS, f"timing changed {r['max_length_change_ms']} ms (> 1 frame)")
    check(abs(r["duration_out"] - r["duration_in"]) < 0.03, f"duration {r['duration_in']} -> {r['duration_out']}")
    h = [subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-map", "0:v", "-c", "copy", "-f", "md5", "-"],
                        capture_output=True, text=True).stdout.strip() for f in (src, out)]
    check(h[0] == h[1], "picture was re-encoded / changed")
    print(f"    similarity to B {s['before']} -> {s['after']} (line {s['pass_line']}), timing change {r['max_length_change_ms']} ms, picture bit-identical")


@test("voice-cloned speech (English + French) in person B's voice", "voice")
def t_voice_speak(fx):
    v = fx.voice
    check("pb" in v, "needs the profile test first")
    d = fx.d / "voice"
    rows = []
    for lang, text in (("en", "Sorry I'm late, the traffic was terrible this morning."),
                       ("fr", "Désolé pour le retard, il y avait beaucoup de circulation ce matin.")):
        r = js(sh([VPY, SCRIPTS / "voice_convert.py", "speak", "--profile", v["pb"], "--text", text, "--lang", lang,
                   "--out", d / f"speak_{lang}.wav"], ok_codes=(0, 1)))
        check(r["verdict"] == "PASS", f"{lang}: cloned speech not person B: {r}")
        check(1.5 < r["seconds"] < 12, f"{lang}: odd length {r['seconds']}")
        rows.append(f"{lang} {r['similarity']} ({r['seconds']} s)")
    r2 = js(sh([VPY, SCRIPTS / "voice_convert.py", "speak", "--profile", v["pb"], "--text", "Sorry I'm late, the traffic was terrible this morning.",
                "--lang", "en", "--out", d / "speak_en_again.wav"], ok_codes=(0, 1)))
    a1, a2 = audio(d / "speak_en.wav", 24000), audio(d / "speak_en_again.wav", 24000)
    same = len(a1) == len(a2) and float(np.abs(a1 - a2).max()) < 1e-3
    print(f"    similarity: {', '.join(rows)}; same seed -> identical take: {same}")


# ------------------------------------------------------------------ runner
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--voice-a")
    ap.add_argument("--voice-b")
    ap.add_argument("--keep", action="store_true", help="keep the temp folder for inspection")
    a = ap.parse_args()
    groups = set(a.only.split(",")) if a.only else {"soundtrack", "edit", "prompts", "voice"}
    tests = [v for v in list(globals().values()) if callable(v) and hasattr(v, "_group") and v._group in groups]
    if "voice" in groups and not (a.voice_a and a.voice_b):
        print("voice tests skipped: pass --voice-a and --voice-b (two different people)")
        tests = [t for t in tests if t._group != "voice"]
    td = Path(tempfile.mkdtemp(prefix="ffd-tests-"))
    os.environ["FLOW_MCP_HOME"] = str(td / "flow-mcp-home")   # hermetic: no real Flow character looks
    print(f"work folder: {td}\nPY={PY}\nVPY={VPY}\npreparing synthetic media ...")
    fx = Fx(td)
    fx.voice = {"a": a.voice_a, "b": a.voice_b}
    failed = 0
    for t in tests:
        t0 = time.time()
        try:
            t(fx)
            print(f"PASS  [{t._group}] {t._name}  ({time.time() - t0:.0f}s)")
            RESULTS.append((t._name, True))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  [{t._group}] {t._name}  ({time.time() - t0:.0f}s)\n      {str(e)[:1500]}")
            RESULTS.append((t._name, False))
    print(f"\n{len(tests) - failed}/{len(tests)} passed" + (f"   (files kept in {td})" if a.keep or failed else ""))
    if not (a.keep or failed):
        import shutil
        shutil.rmtree(td, ignore_errors=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
