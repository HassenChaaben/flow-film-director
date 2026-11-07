"""Clean reference photos before anything goes to Flow (phone screenshots, borders, UI bars).

Flow copies whatever is in a reference image - a story's status bar, "Send message" box, profile icon or caption
becomes part of the scene. Every reference (people, products, places) must show only the subject.

Usage:
  python prep_refs.py <folder or images...> --out <clean folder> [--crop-top 0.26 --crop-bottom 0.12] [--crop-left 0 --crop-right 0]
  python prep_refs.py <folder> --out <clean folder> --auto
--auto trims flat bands (status/navigation bars, letterboxing) from all four sides. Overlays drawn ON the photo
(story captions, icons, stickers) are not removable automatically: look at the sheet, then re-run with --crop-* or
exclude the photo. Writes clean copies (originals untouched), a sheet (before | after) and report.json.
A photo is reported as a phone screenshot when its height/width >= 1.9 (or width/height >= 1.9).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cv2  # noqa: E402
import numpy as np  # noqa: E402

from facekit import IMAGE_EXT, grid, imread, imwrite, label, list_media  # noqa: E402


def flat_band(gray, axis_len, rows, flat_std=6.0, max_frac=0.3):
    """Count leading rows (in the given order) that are flat (one colour, e.g. a UI bar)."""
    n = 0
    for r in rows[: int(axis_len * max_frac)]:
        if float(np.std(r)) < flat_std:
            n += 1
        else:
            break
    return n


def auto_box(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    top = flat_band(g, h, [g[i] for i in range(h)])
    bottom = flat_band(g, h, [g[h - 1 - i] for i in range(h)])
    left = flat_band(g, w, [g[:, i] for i in range(w)])
    right = flat_band(g, w, [g[:, w - 1 - i] for i in range(w)])
    return top, h - bottom, left, w - right


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--auto", action="store_true")
    for side in ("top", "bottom", "left", "right"):
        ap.add_argument(f"--crop-{side}", type=float, default=0.0, help="fraction of the height/width to cut")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report, tiles = [], []
    for p in list_media(a.inputs, IMAGE_EXT):
        img = imread(p)
        h, w = img.shape[:2]
        y0, y1, x0, x1 = int(h * a.crop_top), h - int(h * a.crop_bottom), int(w * a.crop_left), w - int(w * a.crop_right)
        if a.auto:
            t, b, l, r = auto_box(img[y0:y1, x0:x1])
            y0, y1, x0, x1 = y0 + t, y0 + b, x0 + l, x0 + r
        if y1 - y0 < 64 or x1 - x0 < 64:
            report.append({"file": str(p), "error": "crop leaves less than 64 px"})
            continue
        clean = img[y0:y1, x0:x1]
        dst = out / (p.stem + ".png")
        imwrite(dst, clean)
        ratio = max(h / w, w / h)
        notes = []
        if ratio >= 1.9:
            notes.append("PHONE SCREENSHOT: check that no app UI, caption or icon is left in the clean copy")
        report.append({"file": str(p), "clean": str(dst), "box": [x0, y0, x1, y1], "from": f"{w}x{h}",
                       "to": f"{x1 - x0}x{y1 - y0}", "notes": notes})
        tiles += [label(img, f"BEFORE {p.name[:30]}"), label(clean, f"AFTER {x1 - x0}x{y1 - y0}", bg=(0, 90, 0))]
    imwrite(out / "_sheet.jpg", grid(tiles, cols=4, tile_w=360))
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"cleaned": sum(1 for r in report if "clean" in r), "sheet": str(out / "_sheet.jpg"),
                      "screenshots": [r["file"] for r in report if r.get("notes")],
                      "errors": [r for r in report if "error" in r]}, indent=2))


if __name__ == "__main__":
    main()
