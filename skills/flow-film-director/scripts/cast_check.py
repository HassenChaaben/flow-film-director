"""Gate for the picture a Flow character is built from (run BEFORE flow_character, and again on the portrait Flow saved
in <output>/_cast/<Name>.* afterwards).

Usage (skill venv python):
  python cast_check.py --gallery film/<slug>/bible/gallery.json --name Sam <picture> [<picture> ...]

Passes a picture only when it shows exactly one face, that face is the named person (identity_check PASS) and the face
is big enough for Flow to learn it: face height >= --min-share (default 0.18) of the picture height and >= --min-face-px
(default 100) pixels. Share, not raw pixels, because Flow hands portraits back as small 512 px previews. Measured
2026-11-06: One person's Flow character had been built from a full-body night photo (face share 0.10-0.13); every video
then gave him a rounder, heavier face and a fuller beard. Rebuilt from a daylight selfie (share 0.46) the portrait
scored 0.94 instead of 0.74. The other person's character (share 0.23) was fine.
Also remember (not measurable here): a front-camera selfie is often MIRRORED (text reads backwards) - flip it first,
or moles, partings and scars land on the wrong side.
Exit 0 = at least one picture passes (the best is printed first), 1 = none passes.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

import cv2

import identity_check



def run_identity_check(args: list[str]) -> str:
    """Run identity_check in this process (no second file needed) and return what it printed."""
    buf, old = io.StringIO(), sys.argv
    sys.argv = ["identity_check.py", *args]
    try:
        with contextlib.redirect_stdout(buf):
            identity_check.main()
    except SystemExit:
        pass
    finally:
        sys.argv = old
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gallery", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--min-face-px", type=int, default=100)
    ap.add_argument("--min-share", type=float, default=0.18)
    ap.add_argument("pictures", nargs="+")
    a = ap.parse_args()
    out = run_identity_check([*a.pictures, "--gallery", a.gallery, "--expect", a.name])
    try:
        results = json.loads(out)["results"]
    except (ValueError, KeyError):
        print(json.dumps({"error": "identity_check failed: " + out[-400:]}))
        return 1
    rows = []
    for r in results:
        c = (r.get("chars") or {}).get(a.name) or {}
        why = []
        if r.get("faces", 0) != 1:
            why.append(f"{r.get('faces', 0)} faces in the picture (need exactly 1)")
        if c.get("verdict") != "PASS":
            why.append(f"not recognised as {a.name} ({c.get('verdict')}, score {c.get('score')})")
        img = cv2.imread(str(r.get("file")))
        share = round((c.get("face_px") or 0) / img.shape[0], 3) if img is not None else 0
        if share < a.min_share or (c.get("face_px") or 0) < a.min_face_px:
            why.append(f"face too small: {c.get('face_px')} px, {share} of the picture height (need >= {a.min_share} and "
                       f">= {a.min_face_px} px): use a closer head-and-shoulders photo")
        rows.append({"file": r.get("file"), "score": c.get("score"), "face_px": c.get("face_px"), "share": share, "pose": c.get("pose"),
                     "ok": not why, "why": why})
    rows.sort(key=lambda x: (not x["ok"], -(x["score"] or 0), -(x["face_px"] or 0)))
    print(json.dumps({"name": a.name, "best": rows[0]["file"] if rows and rows[0]["ok"] else None, "pictures": rows}, indent=2))
    return 0 if rows and rows[0]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
