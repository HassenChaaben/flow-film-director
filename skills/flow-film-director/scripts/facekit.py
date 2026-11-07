"""Shared face helpers for flow-film-director.

Uses OpenCV's YuNet (detection + 5 landmarks) and SFace (128-d identity embedding).
Models live in ~/.flow-film/models; scripts/setup_env.py downloads them once. This file never uses the network.
SFace cosine similarity: >= 0.363 is OpenCV's "same person" threshold. Real photos of the
same person usually score 0.55-0.85. Generated frames that "look like a cousin" land around 0.30-0.45.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

MODELS = {"yunet": "face_detection_yunet_2023mar.onnx", "sface": "face_recognition_sface_2021dec.onnx"}
MODEL_DIR = Path.home() / ".flow-film" / "models"
SAME_PERSON = 0.363  # OpenCV SFace cosine threshold
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def model_path(key: str) -> str:
    p = MODEL_DIR / MODELS[key]
    if not p.exists() or p.stat().st_size < 50_000:
        raise RuntimeError(f"{p.name} is missing in {MODEL_DIR}. Run scripts/setup_env.py once (it downloads the models).")
    return str(p)


def imread(path: str | Path):
    """Unicode-safe image read (Windows paths with spaces/accents)."""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot read image {path}")
    return img


def imwrite(path: str | Path, img) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ext = Path(path).suffix or ".jpg"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise ValueError(f"cannot encode {path}")
    buf.tofile(str(path))


class FaceKit:
    def __init__(self, score_threshold: float = 0.75):
        self.det = cv2.FaceDetectorYN.create(model_path("yunet"), "", (320, 320), score_threshold, 0.3, 5000)
        self.rec = cv2.FaceRecognizerSF.create(model_path("sface"), "")

    def faces(self, img, max_side: int = 1600):
        """Return list of dicts: box, landmarks, det_score, embedding, crop, metrics. Coordinates in original image."""
        h, w = img.shape[:2]
        scale = min(1.0, max_side / max(h, w))
        small = cv2.resize(img, (int(w * scale), int(h * scale))) if scale < 1 else img
        self.det.setInputSize((small.shape[1], small.shape[0]))
        _, found = self.det.detect(small)
        out = []
        if found is None:
            return out
        for f in found:
            f = f.copy()
            f[:14] /= scale
            aligned = self.rec.alignCrop(img, f)
            emb = self.rec.feature(aligned).flatten()
            emb = emb / (np.linalg.norm(emb) + 1e-9)
            x, y, bw, bh = [int(v) for v in f[:4]]
            lm = f[4:14].reshape(5, 2)  # right eye, left eye, nose, right mouth, left mouth
            out.append(
                {
                    "box": [x, y, bw, bh],
                    "landmarks": lm.tolist(),
                    "det_score": float(f[14]),
                    "embedding": emb,
                    "aligned": aligned,
                    "metrics": face_metrics(img, f),
                }
            )
        out.sort(key=lambda d: d["box"][2] * d["box"][3], reverse=True)
        return out


def face_metrics(img, f):
    h, w = img.shape[:2]
    x, y, bw, bh = [int(v) for v in f[:4]]
    lm = f[4:14].reshape(5, 2)
    eye_r, eye_l, nose = lm[0], lm[1], lm[2]
    eye_mid = (eye_r + eye_l) / 2
    eye_dist = float(np.linalg.norm(eye_l - eye_r)) + 1e-6
    # yaw proxy: nose horizontal offset from eye midpoint, relative to eye distance (0 frontal, ~0.5+ profile)
    yaw = float((nose[0] - eye_mid[0]) / eye_dist)
    roll = float(np.degrees(np.arctan2(eye_l[1] - eye_r[1], eye_l[0] - eye_r[0])))
    x0, y0 = max(0, x), max(0, y)
    crop = img[y0 : min(h, y + bh), x0 : min(w, x + bw)]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.size else None
    if gray is not None and gray.size:
        gray = cv2.resize(gray, (256, 256), interpolation=cv2.INTER_AREA)  # size-independent sharpness
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var()) if gray is not None and gray.size else 0.0
    bright = float(gray.mean()) if gray is not None and gray.size else 0.0
    pose = "frontal" if abs(yaw) < 0.12 else ("three-quarter" if abs(yaw) < 0.35 else "profile")
    return {
        "face_px": int(min(bw, bh)),
        "face_ratio": round(float(bw * bh) / float(w * h), 4),
        "yaw": round(yaw, 3),
        "roll_deg": round(roll, 1),
        "pose": pose,
        "sharpness": round(sharp, 1),
        "brightness": round(bright, 1),
    }


def cos(a, b) -> float:
    return float(np.dot(a, b))


def score_against(emb, gallery_embs) -> float:
    """Mean of the top-3 similarities to the gallery (robust to one odd reference)."""
    sims = sorted((cos(emb, g) for g in gallery_embs), reverse=True)
    top = sims[:3] if sims else [0.0]
    return float(np.mean(top))


def save_gallery(path: Path, data: dict) -> None:
    """data: {name: {"embeddings": [np.array], "baseline": float, "refs": [...]}}"""
    path.parent.mkdir(parents=True, exist_ok=True)
    serial = {}
    for name, d in data.items():
        npy = path.parent / f"{name}.embeddings.npy"
        np.save(npy, np.stack(d["embeddings"]))
        serial[name] = {k: v for k, v in d.items() if k != "embeddings"}
        serial[name]["embeddings_file"] = npy.name
    path.write_text(json.dumps(serial, indent=2), encoding="utf-8")


def load_gallery(path: str | Path) -> dict:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    for name, d in data.items():
        d["embeddings"] = list(np.load(path.parent / d["embeddings_file"]))
    return data


def label(img, text, color=(255, 255, 255), bg=(0, 0, 0), width=480):
    """Downscale to `width` first, then draw readable text on top."""
    if img.shape[1] != width:
        img = cv2.resize(img, (width, max(1, int(img.shape[0] * width / img.shape[1]))), interpolation=cv2.INTER_AREA)
    else:
        img = img.copy()
    lines = text.split("\n")
    th = 20
    cv2.rectangle(img, (0, 0), (img.shape[1], th * len(lines) + 6), bg, -1)
    for i, line in enumerate(lines):
        cv2.putText(img, line, (4, th * (i + 1)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    return img


def grid(tiles, cols=4, tile_w=320):
    """tiles: list of BGR images. Returns one sheet image."""
    if not tiles:
        return np.zeros((10, 10, 3), np.uint8)
    rs = []
    for t in tiles:
        s = tile_w / t.shape[1]
        rs.append(cv2.resize(t, (tile_w, max(1, int(t.shape[0] * s)))))
    rows = []
    for i in range(0, len(rs), cols):
        row = rs[i : i + cols]
        hmax = max(r.shape[0] for r in row)
        row = [cv2.copyMakeBorder(r, 0, hmax - r.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(30, 30, 30)) for r in row]
        while len(row) < cols:
            row.append(np.full((hmax, tile_w, 3), 30, np.uint8))
        rows.append(np.hstack(row))
    return np.vstack(rows)


def list_media(paths, exts):
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out += sorted(q for q in p.iterdir() if q.suffix.lower() in exts)
        elif p.suffix.lower() in exts:
            out.append(p)
    return out
