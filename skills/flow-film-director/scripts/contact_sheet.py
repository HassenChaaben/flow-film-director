"""Side-by-side sheet for visual review: references next to generated stills/frames.

Usage:
  python contact_sheet.py --out review.jpg --cols 4 --title "REF" ref1.jpg ref2.jpg --title "GEN" gen1.png gen2.png
  python contact_sheet.py --out frames.jpg --video clip.mp4 --at 0,25,50,75,100     (percent points of the clip)
Each --title starts a labelled group. Read the output image and compare feature by feature.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cv2  # noqa: E402

from facekit import grid, imread, imwrite, label  # noqa: E402


def video_frames(path, points):
    """Sequential decode (exact, and works when the container reports no frame count)."""
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    n = 0
    while cap.grab():
        n += 1
    cap.release()
    if n == 0:
        raise SystemExit(f"cannot read frames from {path}")
    wanted = {min(n - 1, max(0, int(round((n - 1) * p / 100)))): p for p in points}
    out, cap, i = [], cv2.VideoCapture(str(path)), 0
    while cap.grab():
        if i in wanted:
            ok, img = cap.retrieve()
            if ok:
                out.append(label(img, f"{Path(path).name} {wanted[i]}% t={i / fps:.2f}s"))
        i += 1
    cap.release()
    return out


def main():
    # Hand-parsed: "--title X" may appear many times between image paths, which argparse cannot keep in order.
    opts = {"--out": None, "--cols": "4", "--video": None, "--at": "0,20,40,60,80,100"}
    items, title, argv, i = [], "", sys.argv[1:], 0
    while i < len(argv):
        tok = argv[i]
        if tok in opts:
            opts[tok] = argv[i + 1]
            i += 2
        elif tok == "--title":
            title = argv[i + 1]
            i += 2
        else:
            items.append((title, Path(tok)))
            i += 1
    if not opts["--out"]:
        sys.exit("usage: contact_sheet.py --out sheet.jpg [--cols N] [--video clip.mp4 --at 0,50,100] [--title REF] img ... [--title GEN] img ...")
    tiles = []
    if opts["--video"]:
        tiles += video_frames(opts["--video"], [float(x) for x in opts["--at"].split(",")])
    for t, p in items:
        tiles.append(label(imread(p), f"{t} {p.name}"[:60], bg=(90, 0, 0) if t.upper().startswith("REF") else (0, 0, 0)))
    imwrite(opts["--out"], grid(tiles, cols=int(opts["--cols"]), tile_w=480))
    print(opts["--out"])


if __name__ == "__main__":
    main()
