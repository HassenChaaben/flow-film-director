"""Deterministic audio analysis (numpy + ffmpeg): decode, speech regions, pitch, tempo and beats.
Used by assemble.py (beat-snapped cuts) and voice_profile.py (sample quality, pitch, closest Flow voice)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from editkit import ffmpeg


def load(path, sr=22050, start=None, dur=None) -> np.ndarray:
    """Decode any audio/video file to mono float32 at `sr` Hz."""
    args = [ffmpeg(), "-hide_banner", "-nostdin", "-v", "error"]
    if start is not None:
        args += ["-ss", f"{start:.6f}"]
    args += ["-i", str(path)]
    if dur is not None:
        args += ["-t", f"{dur:.6f}"]
    args += ["-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    p = subprocess.run(args, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode(errors="replace")[-1500:])
    return np.frombuffer(p.stdout, dtype=np.float32).copy()


def save_wav(path, y, sr):
    import wave
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(y, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def frames(y, n, hop):
    if len(y) < n:
        y = np.pad(y, (0, n - len(y)))
    count = 1 + (len(y) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(count)[:, None]
    return y[idx]


def rms_db(y, sr, win=0.03):
    n = int(sr * win)
    f = frames(y, n, n // 2)
    return 20 * np.log10(np.sqrt((f ** 2).mean(axis=1)) + 1e-9)


def speech_regions(y, sr, min_len=0.25, gap=0.3):
    """Energy VAD: frames louder than (noise floor + 12 dB) and above -45 dBFS. Returns [(start, end)] seconds."""
    db = rms_db(y, sr)
    hop = 0.015
    floor = np.percentile(db, 10)
    voiced = db > max(floor + 12, -45)
    regions, start = [], None
    for i, v in enumerate(voiced):
        t = i * hop
        if v and start is None:
            start = t
        if not v and start is not None:
            regions.append([start, t])
            start = None
    if start is not None:
        regions.append([start, len(voiced) * hop])
    merged = []
    for r in regions:
        if merged and r[0] - merged[-1][1] < gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(round(a, 3), round(b, 3)) for a, b in merged if b - a >= min_len]


def snr_db(y, sr):
    db = rms_db(y, sr)
    return float(np.percentile(db, 95) - np.percentile(db, 10))


def pitch_hz(y, sr, fmin=60, fmax=400):
    """Median F0 of voiced frames by normalised autocorrelation (robust enough to pick a voice register)."""
    n, hop = int(sr * 0.04), int(sr * 0.01)
    f = frames(y, n, hop)
    f = f - f.mean(axis=1, keepdims=True)
    energy = (f ** 2).sum(axis=1)
    keep = energy > np.percentile(energy, 60)
    lo, hi = int(sr / fmax), int(sr / fmin)
    out = []
    for fr in f[keep]:
        ac = np.correlate(fr, fr, "full")[n - 1:]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] > 0.35:
            out.append(sr / lag)
    return float(np.median(out)) if out else None


HOP, NFFT = 512, 2048
LAG = 0.77  # flux peaks ~0.77 window-lengths before the hit; calibrated with tests/run_tests.py (was -71 ms at 22.05 kHz)


def onset_envelope(y, sr, hop=HOP, n=NFFT, fmax=None):
    """Spectral flux of the log magnitude; with fmax only the band below fmax Hz (kick / bass)."""
    win = np.hanning(n)
    f = frames(y, n, hop) * win
    mag = np.abs(np.fft.rfft(f, axis=1))
    if fmax:
        mag = mag[:, : max(2, int(fmax * n / sr))]
    logm = np.log1p(10 * mag)
    flux = np.maximum(0, np.diff(logm, axis=0)).sum(axis=1)
    flux = np.concatenate([[0], flux])
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")  # remove slow trend
    return np.maximum(flux, 0), sr / hop


def tempo_and_beats(y, sr, bpm_min=60, bpm_max=180):
    """Tempo from the onset autocorrelation, beats from the best phase of that grid (refined to local peaks).
    Deterministic. Returns (bpm, [beat times in seconds])."""
    env, fr = onset_envelope(y, sr)
    if env.max() <= 0:
        return None, []
    env = env / env.max()
    ac = np.correlate(env, env, "full")[len(env) - 1:]
    lags = np.arange(len(ac))
    lo, hi = int(fr * 60 / bpm_max), int(fr * 60 / bpm_min)
    cand = lags[lo:hi + 1]
    # prefer tempi near 120 slightly (perceptual weighting), and reward the double lag (metre consistency)
    w = np.exp(-0.5 * (np.log2((60 * fr / cand) / 120) / 1.0) ** 2)
    # A beat period is rarely a whole number of analysis frames (120 BPM = 21.5 frames), which splits its peak.
    # Score each lag by the best value within +-1 frame so every tempo competes at full strength.
    acs = ac.copy()
    acs[1:-1] = np.maximum(ac[1:-1], np.maximum(ac[:-2], ac[2:]))
    score = acs[lo:hi + 1] * w + 0.5 * np.array([acs[min(2 * c, len(acs) - 1)] for c in cand])
    period = cand[int(np.argmax(score))]
    period = period - 1 + int(np.argmax(ac[period - 1:period + 2]))   # the real peak next to it
    # parabolic refinement of the period
    i = period
    if 1 <= i < len(ac) - 1:
        a, b, c = ac[i - 1], ac[i], ac[i + 1]
        d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
        period_f = i + float(np.clip(d, -0.5, 0.5))
    else:
        period_f = float(i)
    # Precision: measure the lag of k whole beats (k = 8, 4 or 2) and divide - the frame rounding error is k times
    # smaller, so the beat grid does not slide over a long song (0.6 % error = 2/3 of a beat after 110 beats).
    for k in (8, 4, 2):
        j = int(round(k * period_f))
        if j + 2 < len(ac) and j < len(env) / 3:
            seg = ac[j - 2:j + 3]
            m = j - 2 + int(np.argmax(seg))
            if 1 <= m < len(ac) - 1:
                a_, b_, c_ = ac[m - 1], ac[m], ac[m + 1]
                den = a_ - 2 * b_ + c_
                dm = 0.5 * (a_ - c_) / den if den != 0 else 0.0
                period_f = (m + float(np.clip(dm, -0.5, 0.5))) / k
            break
    bpm = 60 * fr / period_f
    # Phase: the beat is where the LOW band (kick, bass) hits - hi-hats on the off-beats must not win.
    low, _ = onset_envelope(y, sr, fmax=200)
    low = low / low.max() if low.max() > 0 else env
    env = 0.75 * low + 0.25 * env
    # a kick's low-band onset is spread over several frames; a hi-hat is a 1-frame spike. Compare grid
    # positions by the best value within +-1 frame so a smeared kick is not beaten by a sharp off-beat hat.
    envd = env.copy()
    envd[1:-1] = np.maximum(env[1:-1], np.maximum(env[:-2], env[2:]))
    best_phase, best = 0, -1.0
    first = min(len(env), int(period_f * 32) + 1)          # first 32 beats: no time for any drift
    for ph in range(int(np.ceil(period_f))):
        idx = np.arange(ph, first, period_f).round().astype(int)
        idx = idx[idx < len(env)]
        s = envd[idx].sum()
        if s > best:
            best, best_phase = s, ph
    beats = []
    t = float(best_phase)
    rad = max(1, int(period_f * 0.1))
    while t < len(env):
        k = int(round(t))
        a, b = max(0, k - rad), min(len(env), k + rad + 1)
        k2 = a + int(np.argmax(env[a:b])) if b > a else k
        beats.append(k2 / fr + LAG * NFFT / sr)
        # step from the beat just found (not from the start), so a tiny tempo error never accumulates;
        # if no real hit was there (weak envelope), keep the grid position
        t = (k2 if low[k2] > 0.3 else t) + period_f       # re-anchor only on a real kick/bass hit
    return round(float(bpm), 2), [round(x, 3) for x in beats]
