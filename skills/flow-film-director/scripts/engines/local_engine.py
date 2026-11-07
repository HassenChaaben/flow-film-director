"""Local Open-Source Engine for Flow Film Director.

100% free, local zero-shot TTS and Voice Conversion using Chatterbox (Resemble AI)
and PerthNet on local NVIDIA GPU (CUDA).
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from voicekit import vc, tts, Encoder, cos, SR


def speak(text: str, reference_wav: str | Path, out_path: str | Path, lang: str = "en", seed: int = 7) -> Path:
    """Generate local zero-shot speech in character voice."""
    wav, sr = tts(text, target_ref_wav=str(reference_wav), lang=lang, seed=seed)
    
    import soundfile as sf
    dst = Path(out_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dst), wav, sr)
    return dst


def convert(source_wav: str | Path, reference_wav: str | Path, out_path: str | Path) -> Path:
    """Perform local voice conversion."""
    wav, sr = vc(str(source_wav), str(reference_wav))
    
    import soundfile as sf
    dst = Path(out_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dst), wav, sr)
    return dst
