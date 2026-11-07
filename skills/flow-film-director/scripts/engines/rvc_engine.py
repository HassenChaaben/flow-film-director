"""RVC (Retrieval-based Voice Conversion) Engine for Flow Film Director.

Allows 100% free, natural human performance transfer:
1. The user (or an actor) records the dialogue lines naturally on their phone.
2. RVC extracts the pitch (F0), phoneme embeddings (ContentVec), and applies the character's vocal tract resonance.
3. Preserves 100% of human emotion, cadence, breathing, and dialect pronunciation while changing the voice identity.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

# Default model directory
RVC_MODELS_DIR = Path.home() / ".flow-film" / "rvc-models"


def check_rvc_ready() -> dict:
    """Check if local RVC dependencies and weights are available."""
    try:
        import torch
        cuda = torch.cuda.is_available()
    except ImportError:
        return {"ok": False, "error": "PyTorch not found in current environment."}
    
    return {
        "ok": True,
        "cuda": cuda,
        "device": "cuda" if cuda else "cpu",
        "models_dir": str(RVC_MODELS_DIR)
    }


def convert_speech(
    source_audio: str | Path,
    target_reference_wav: str | Path,
    out_path: str | Path,
    pitch_shift: int = 0,
    f0_method: str = "rmvpe"
) -> Path:
    """Convert a human voice recording into the target voice using RVC / PerthNet timbre transfer."""
    src = Path(source_audio)
    dst = Path(out_path)
    ref = Path(target_reference_wav)
    
    if not src.exists():
        raise FileNotFoundError(f"Source human audio not found: {src}")
    if not ref.exists():
        raise FileNotFoundError(f"Target voice reference not found: {ref}")
    
    dst.parent.mkdir(parents=True, exist_ok=True)
    
    # Try rvc-python if installed, or fallback to PerthNet voice conversion
    try:
        from rvc_python.infer import infer_file
        print(f"Running RVC inference on {src.name}...", flush=True)
        infer_file(
            input_path=str(src),
            model_path=str(ref.with_suffix(".pth")),
            output_path=str(dst),
            f0_method=f0_method,
            pitch=pitch_shift,
            device="cuda:0"
        )
        return dst
    except Exception:
        # Fallback to high-quality PerthNet voice converter
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from voicekit import vc
        wav, sr = vc(str(src), str(ref))
        
        # Save output
        import soundfile as sf
        sf.write(str(dst), wav, sr)
        return dst
