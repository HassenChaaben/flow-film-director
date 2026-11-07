"""One-time setup: an isolated Python environment for the skill (never touches the user's main Python).

Usage:  python setup_env.py          (any Python 3.10+)
Creates ~/.flow-film/venv with the exact tested versions, downloads the face + pose models, and prints the
interpreter path to use for every skill script (PY). Safe to re-run: it only installs what is missing.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PINNED = ["mediapipe==1.2.2", "opencv-python==5.0.0.93", "numpy==2.5.4"]  # tested together on 2026-11-04
VENV = Path(os.environ.get("FLOW_FILM_HOME", Path.home() / ".flow-film")) / "venv"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main():
    py = venv_python()
    if not py.exists():
        print(f"creating {VENV} ...", flush=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    check = subprocess.run([str(py), "-c", "import mediapipe, cv2, numpy; cv2.FaceDetectorYN; print('ok')"],
                           capture_output=True, text=True)
    if "ok" not in check.stdout:
        subprocess.check_call([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"])
        subprocess.check_call([str(py), "-m", "pip", "install", "-q", *PINNED])
    here = Path(__file__).resolve().parent
    code = (
        "import sys; sys.path.insert(0, r'%s'); from facekit import model_path; from motionkit import PoseTracker; "
        "model_path('yunet'); model_path('sface'); p = PoseTracker(); print('pose', p.available)" % here
    )
    subprocess.check_call([str(py), "-c", code])
    print(f"PY={py}")


if __name__ == "__main__":
    main()
