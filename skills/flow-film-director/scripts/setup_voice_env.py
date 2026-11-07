"""One-time setup for character voices: an isolated environment ~/.flow-film/voice-venv with Chatterbox
(Resemble AI, MIT licence) for voice conversion and voice-cloned speech, plus its speaker encoder for measuring
voice similarity. Kept apart from ~/.flow-film/venv because Chatterbox pins numpy<2 and torch 2.6.

Usage:  python setup_voice_env.py      (any Python 3.10-3.12)
Installs torch from PyPI only (Linux wheels include CUDA; on Windows PyPI gives the CPU build - install a CUDA
build of torch 2.6 into this venv yourself if you want the GPU there). Chatterbox downloads ~1.5 GB of model
weights on first use from Hugging Face (ResembleAI/chatterbox).
Prints VPY=<interpreter> for voice_profile.py / voice_convert.py. Safe to re-run.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

VENV = Path.home() / ".flow-film" / "voice-venv"
TORCH = ["torch==2.6.0", "torchaudio==2.6.0"]
CHATTERBOX = "chatterbox-tts==0.1.7"


def py() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main():
    if sys.version_info >= (3, 13):
        sys.exit("Chatterbox 0.1.7 needs Python 3.10-3.12 for its pinned torch 2.6. Run this with a 3.10-3.12 Python.")
    if not py().exists():
        print(f"creating {VENV} ...", flush=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    ok = subprocess.run([str(py()), "-c", "import chatterbox, torch; print('ok', torch.cuda.is_available())"],
                        capture_output=True, text=True)
    if "ok" not in ok.stdout:
        subprocess.check_call([str(py()), "-m", "pip", "install", "-q", "--upgrade", "pip"])
        print("installing torch 2.6 from PyPI ...", flush=True)
        subprocess.check_call([str(py()), "-m", "pip", "install", "-q", *TORCH])
        print("installing chatterbox ...", flush=True)
        subprocess.check_call([str(py()), "-m", "pip", "install", "-q", CHATTERBOX])
    out = subprocess.run([str(py()), "-c", "import torch, chatterbox; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"],
                         capture_output=True, text=True)
    print(out.stdout.strip() or out.stderr[-2000:])
    print(f"VPY={py()}")


if __name__ == "__main__":
    main()
