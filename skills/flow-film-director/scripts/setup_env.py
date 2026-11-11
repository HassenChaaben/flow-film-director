"""One-time setup: an isolated Python environment for the skill (never touches the user's main Python).

Usage:  python setup_env.py          (any Python 3.10+)
Creates ~/.flow-film/venv with the exact tested versions, downloads the face + pose models into
~/.flow-film/models, and prints the interpreter path to use for every skill script (PY). Safe to re-run: it only
installs and downloads what is missing.

Network use (this is the only skill script that downloads anything, and it reads no user files):
  - pip packages from PyPI (mediapipe, opencv-python, numpy)
  - OpenCV Zoo public model files from github.com (YuNet face detector, SFace face recogniser)
  - Google MediaPipe public pose model from storage.googleapis.com
"""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from pathlib import Path

PINNED = ["mediapipe==1.2.2", "opencv-python==5.0.0.93", "numpy==2.5.4"]  # tested together on 2026-11-04
HOME = Path.home() / ".flow-film"
VENV = HOME / "venv"
MODEL_DIR = HOME / "models"
MODEL_FILES = {
    "face_detection_yunet_2023mar.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    "pose_landmarker_full.task":
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
}


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def download_models() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in MODEL_FILES.items():
        p = MODEL_DIR / name
        if p.exists() and p.stat().st_size >= 50_000:
            continue
        print(f"downloading {name} ...", flush=True)
        tmp = p.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        if tmp.stat().st_size < 50_000:
            tmp.unlink()
            sys.exit(f"download of {name} looks wrong (too small). Fetch it by hand into {MODEL_DIR}")
        tmp.replace(p)


NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}


def probe() -> None:
    """Run by the venv Python: are the packages importable?"""
    import cv2
    import mediapipe  # noqa: F401
    import numpy  # noqa: F401
    assert cv2.FaceDetectorYN
    print("ok")


def selfcheck() -> None:
    """Run by the venv Python: the models load and pose tracking works."""
    from facekit import model_path
    from motionkit import PoseTracker
    model_path("yunet")
    model_path("sface")
    print("pose", PoseTracker().available)


def main():
    if "--probe" in sys.argv[1:]:
        return probe()
    if "--selfcheck" in sys.argv[1:]:
        return selfcheck()
    py = venv_python()
    if not py.exists():
        print(f"creating {VENV} ...", flush=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)], **NO_WINDOW)
    me = str(Path(__file__).resolve())
    check = subprocess.run([str(py), me, "--probe"], capture_output=True, text=True, **NO_WINDOW)
    if "ok" not in check.stdout:
        subprocess.check_call([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"], **NO_WINDOW)
        subprocess.check_call([str(py), "-m", "pip", "install", "-q", *PINNED], **NO_WINDOW)
    download_models()
    subprocess.check_call([str(py), me, "--selfcheck"], **NO_WINDOW)
    print(f"PY={py}")


if __name__ == "__main__":
    main()
