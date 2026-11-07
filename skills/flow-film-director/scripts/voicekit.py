"""Shared helpers for character voices (run with the VOICE venv: ~/.flow-film/voice-venv, see setup_voice_env.py).

- clean():   any audio/video -> mono 24 kHz wav, high-pass, light denoise, loudness -20 LUFS (deterministic ffmpeg)
- Encoder:   Chatterbox's speaker encoder -> one voice fingerprint per recording; cosine similarity between voices
- vc()/tts(): Chatterbox voice conversion (keeps the words and timing, changes the voice) and voice-cloned speech
Models download once from Hugging Face (ResembleAI/chatterbox) into the normal HF cache.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audiokit import load, speech_regions  # noqa: E402
from editkit import run  # noqa: E402

REPO = "ResembleAI/chatterbox"
SR = 24000          # Chatterbox output rate
ENC_SR = 16000      # speaker encoder rate


def device():
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def clean(src, dst, sr=SR):
    """Deterministic clean-up of a voice sample: mono, 24 kHz, rumble removed, light denoise, -20 LUFS."""
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    run(["-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr),
         "-af", "highpass=f=70,afftdn=nr=10:nf=-40,loudnorm=I=-20:TP=-2:LRA=11", "-c:a", "pcm_s16le", str(dst)])
    return dst


def speech_chunks(y, sr, min_len=1.5, max_len=4.0):
    """Cut the speech regions into 1.5-4 s pieces (one fingerprint each)."""
    out = []
    for a, b in speech_regions(y, sr):
        t = a
        while b - t >= min_len:
            e = min(b, t + max_len)
            out.append(y[int(t * sr):int(e * sr)])
            t = e
    return out


class Encoder:
    def __init__(self):
        import torch
        from chatterbox.models.voice_encoder import VoiceEncoder
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        self.ve = VoiceEncoder()
        self.ve.load_state_dict(load_file(hf_hub_download(REPO, "ve.safetensors")))
        self.ve.to(device()).eval()
        self.torch = torch

    def embed_chunks(self, chunks, sr):
        if not chunks:
            return np.zeros((0, 256), np.float32)
        return self.ve.embeds_from_wavs([c.astype(np.float32) for c in chunks], sample_rate=sr, as_spk=False)

    def fingerprint(self, path_or_wave, sr=ENC_SR, start=None, dur=None):
        """(speaker embedding, per-chunk embeddings, seconds of speech used) for a file or a wave array."""
        if isinstance(path_or_wave, np.ndarray):
            y = path_or_wave.astype(np.float32)
            if sr != ENC_SR:  # the encoder works at 16 kHz; resample here (soxr) so it never needs resampy
                import librosa
                y = librosa.resample(y, orig_sr=sr, target_sr=ENC_SR)
        else:
            y = load(path_or_wave, sr=ENC_SR, start=start, dur=dur)
        sr = ENC_SR
        chunks = speech_chunks(y, sr)
        if not chunks and len(y) >= sr:  # very short line: use it whole
            chunks = [y]
        utt = self.embed_chunks(chunks, sr)
        if len(utt) == 0:
            return None, utt, 0.0
        spk = utt.mean(axis=0)
        spk /= np.linalg.norm(spk) + 1e-9
        return spk, utt, round(sum(len(c) for c in chunks) / sr, 2)


def cos(a, b):
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9))


_vc = None
_tts = {}


def vc(src_wav, target_ref_wav):
    """Voice conversion: same words, same timing, target voice. Returns (wave float32, SR)."""
    global _vc
    if _vc is None:
        from chatterbox.vc import ChatterboxVC
        _vc = ChatterboxVC.from_pretrained(device())
    wav = _vc.generate(str(src_wav), target_voice_path=str(target_ref_wav))
    return wav.squeeze(0).cpu().numpy().astype(np.float32), _vc.sr


def tts(text, target_ref_wav, lang="en", exaggeration=0.5, cfg_weight=0.5, seed=7):
    """Speech in the target voice. English uses ChatterboxTTS, other languages the multilingual model.
    Seeded so the same text + voice + settings gives the same take."""
    import torch
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    key = "en" if lang == "en" else "mtl"
    if key not in _tts:
        if key == "en":
            from chatterbox.tts import ChatterboxTTS
            _tts[key] = ChatterboxTTS.from_pretrained(device())
        else:
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            _tts[key] = ChatterboxMultilingualTTS.from_pretrained(device())
    m = _tts[key]
    kw = {"audio_prompt_path": str(target_ref_wav), "exaggeration": exaggeration, "cfg_weight": cfg_weight}
    wav = m.generate(text, **kw) if key == "en" else m.generate(text, language_id=lang, **kw)
    return wav.squeeze(0).cpu().numpy().astype(np.float32), m.sr
