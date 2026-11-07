"""Audit a character's reference photos and build an identity gallery.

Usage:
  python ref_audit.py --char Sam="C:/.../pictures/Sam" --char Lina="C:/.../pictures/Lina" --out film/bible

For every photo: faces found, which face is the character (the one most similar to the rest of the set),
face size, sharpness, brightness, head pose (frontal / three-quarter / profile), and how much it agrees
with the other photos. Flags: no face, several faces, tiny face, blurry, dark, outlier (different person,
heavy beauty filter, old photo, AI-edited). Picks the best references per pose.

Writes to --out:
  audit.md, audit.json                      human + machine report
  gallery.json + <Name>.embeddings.npy      identity gallery used by identity_check.py
  <Name>/crops/*.jpg                        aligned face crops (look at them: this is what the model sees)
  <Name>/sheet.jpg                          contact sheet of all photos with scores
  <Name>/best/*                             copies of the chosen best references (upload THESE to Flow)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402

from facekit import IMAGE_EXT, SAME_PERSON, FaceKit, cos, grid, score_against, imread, imwrite, label, list_media, log, save_gallery  # noqa: E402

MIN_FACE_PX = 160
MIN_SHARP = 60.0


def pick_identity_faces(per_image):
    """per_image: [(path, faces)]. Choose for each image the face that best matches the majority identity."""
    # seed: largest face in each single-face image (or every image if none single)
    seeds = [f[0]["embedding"] for _, f in per_image if len(f) == 1] or [f[0]["embedding"] for _, f in per_image if f]
    if not seeds:
        return {}
    centroid = np.mean(seeds, axis=0)
    centroid /= np.linalg.norm(centroid) + 1e-9
    chosen = {}
    for path, faces in per_image:
        if faces:
            chosen[path] = max(faces, key=lambda f: cos(f["embedding"], centroid))
    # refine once with the chosen faces
    centroid = np.mean([f["embedding"] for f in chosen.values()], axis=0)
    centroid /= np.linalg.norm(centroid) + 1e-9
    for path, faces in per_image:
        if faces:
            chosen[path] = max(faces, key=lambda f: cos(f["embedding"], centroid))
    return chosen


def audit_character(kit, name, folder, out):
    files = list_media([folder], IMAGE_EXT)
    if not files:
        log(f"{name}: no images in {folder}")
        return None, []
    per_image = []
    for p in files:
        try:
            img = imread(p)
        except Exception as e:  # noqa: BLE001
            log(f"skip {p}: {e}")
            continue
        per_image.append((p, kit.faces(img), img))
    chosen = pick_identity_faces([(p, f) for p, f, _ in per_image])
    embs = {p: f["embedding"] for p, f in chosen.items()}
    if not embs:
        log(f"{name}: no face found in any photo of {folder}")
        rows = [{"file": p.name, "path": str(p), "image_px": f"{img.shape[1]}x{img.shape[0]}", "faces": 0,
                 "flags": ["NO FACE"]} for p, _, img in per_image]
        return None, rows

    rows = []
    for p, faces, img in per_image:
        row = {"file": p.name, "path": str(p), "image_px": f"{img.shape[1]}x{img.shape[0]}", "faces": len(faces), "flags": []}
        if max(img.shape[0] / img.shape[1], img.shape[1] / img.shape[0]) >= 1.9:
            row["flags"].append("PHONE SCREENSHOT: crop the app UI with prep_refs.py before uploading")
        if p not in chosen:
            row["flags"].append("NO FACE")
            rows.append(row)
            continue
        f = chosen[p]
        others = [e for q, e in embs.items() if q != p]
        agree = float(np.median([cos(f["embedding"], e) for e in others])) if others else 1.0
        m = f["metrics"]
        row.update(m)
        row["agreement"] = round(agree, 3)
        if len(faces) > 1:
            row["flags"].append(f"{len(faces)} FACES (picked the one matching the set)")
        if m["face_px"] < MIN_FACE_PX:
            row["flags"].append(f"SMALL FACE {m['face_px']}px")
        if m["sharpness"] < MIN_SHARP:
            row["flags"].append("BLURRY")
        if m["brightness"] < 60:
            row["flags"].append("DARK")
        if m["brightness"] > 215:
            row["flags"].append("OVEREXPOSED")
        if others and agree < SAME_PERSON:
            row["flags"].append("OUTLIER: may be another person, heavy filter/edit, or very different age/lighting")
        elif others and agree < 0.45:
            row["flags"].append("WEAK MATCH: filter, angle or lighting changes the face a lot")
        quality = (
            min(m["face_px"], 600) / 600 * 0.35
            + min(m["sharpness"], 400) / 400 * 0.25
            + max(0.0, agree) * 0.4
            - 0.15 * ("OUTLIER" in " ".join(row["flags"]))
        )
        row["quality"] = round(quality, 3)
        crop_path = out / name / "crops" / f"{p.stem}.jpg"
        imwrite(crop_path, f["aligned"])
        row["crop"] = str(crop_path)
        rows.append(row)

    def has(r, *keys):
        return any(k in f for f in r["flags"] for k in keys)

    good = [r for r in rows if "quality" in r and not has(r, "OUTLIER", "NO FACE")]
    good.sort(key=lambda r: (-r["quality"], r["file"]))
    # Upload-worthy: one clear, big, well-lit face. Group photos, blur, tiny faces never go to Flow.
    usable = [r for r in good if not has(r, "SMALL FACE", "BLURRY", "DARK", "OVEREXPOSED", "FACES")] or good
    best = []
    for pose in ("frontal", "three-quarter", "profile"):
        best += [r for r in usable if r.get("pose") == pose][:2]
    for r in usable:  # fill to at least 3
        if len(best) >= 3:
            break
        if r not in best:
            best.append(r)
    best_dir = out / name / "best"
    if best_dir.exists():
        shutil.rmtree(best_dir)
    best_dir.mkdir(parents=True)
    for i, r in enumerate(best, 1):
        dst = best_dir / f"{i:02d}-{r['pose']}-{Path(r['path']).name}"
        shutil.copy2(r["path"], dst)
        r["best_rank"] = i
        r["best_copy"] = str(dst)

    # Identity gallery: sharp, big-enough faces (group photos are fine: the right face was picked).
    # agreement < 0.55 = probably a cartoon, a heavy AI edit or another era: never part of the measuring gallery
    gal_rows = [r for r in good if not has(r, "SMALL FACE", "BLURRY") and r.get("agreement", 1) >= 0.55] or good
    gallery_embs = [embs[Path(r["path"])] for r in gal_rows] or list(embs.values())
    # Baseline uses the SAME statistic identity_check uses (top-3 mean), leave-one-out, so thresholds are comparable.
    # near-duplicates (same shoot, re-edits of one photo) would inflate the baseline: count each look once
    distinct = []
    for e in gallery_embs:
        if all(cos(e, d) < 0.92 for d in distinct):
            distinct.append(e)
    loo = [score_against(e, distinct[:i] + distinct[i + 1 :]) for i, e in enumerate(distinct)] if len(distinct) > 1 else []
    baseline = float(np.median(loo)) if loo else 0.6

    tiles = []
    for p, faces, img in per_image:
        r = next(x for x in rows if x["path"] == str(p))
        t = img
        if p in chosen:
            x, y, bw, bh = chosen[p]["box"]
            t = img.copy()
            import cv2

            cv2.rectangle(t, (x, y), (x + bw, y + bh), (0, 255, 0), max(2, img.shape[1] // 300))
        txt = f"{p.name[:28]}\nagree {r.get('agreement', '-')} q {r.get('quality', '-')} {r.get('pose', '')}"
        if r["flags"]:
            txt += "\n" + "; ".join(r["flags"])[:60]
        tiles.append(label(t, txt, bg=(0, 0, 120) if r["flags"] else (0, 0, 0)))
    imwrite(out / name / "sheet.jpg", grid(tiles, cols=4, tile_w=360))

    entry = {
        "embeddings": gallery_embs,
        "baseline": round(baseline, 3),
        "refs": [r["path"] for r in gal_rows],
        "best": [r["best_copy"] for r in best],
    }
    return entry, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--char", action="append", required=True, help='Name="folder"')
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    kit = FaceKit()
    gallery, report = {}, {}
    for spec in a.char:
        name, folder = spec.split("=", 1)
        entry, rows = audit_character(kit, name.strip(), Path(folder.strip().strip('"')), out)
        if entry:
            gallery[name.strip()] = entry
            report[name.strip()] = {"baseline": entry["baseline"], "best": entry["best"], "photos": rows}
    save_gallery(out / "gallery.json", gallery)

    names = list(gallery)
    cross = {}
    for i, n1 in enumerate(names):
        for n2 in names[i + 1 :]:
            sims = [cos(x, y) for x in gallery[n1]["embeddings"] for y in gallery[n2]["embeddings"]]
            cross[f"{n1}~{n2}"] = round(float(np.max(sims)), 3) if sims else None
    report["_cross_similarity"] = cross
    (out / "audit.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    md = ["# Reference audit", ""]
    for n in names:
        r = report[n]
        md += [f"## {n}", f"- identity baseline (median ref-to-ref similarity): **{r['baseline']}**",
               f"- sheet: `{out / n / 'sheet.jpg'}`", "- best references (upload these):"]
        md += [f"  - `{b}`" for b in r["best"]]
        md += ["", "| file | px | faces | face px | pose | sharp | agree | quality | flags |", "|---|---|---|---|---|---|---|---|---|"]
        for p in r["photos"]:
            md.append(
                f"| {p['file']} | {p['image_px']} | {p['faces']} | {p.get('face_px', '-')} | {p.get('pose', '-')} | "
                f"{p.get('sharpness', '-')} | {p.get('agreement', '-')} | {p.get('quality', '-')} | {'; '.join(p['flags']) or 'ok'} |"
            )
        md.append("")
    md += ["## Cross-character similarity (max)", ""]
    for k, v in cross.items():
        warn = "  <-- TOO CLOSE: the model may blend these two; describe their differences loudly" if v and v > 0.40 else ""
        md.append(f"- {k}: {v}{warn}")
    (out / "audit.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"audit_md": str(out / "audit.md"), "gallery": str(out / "gallery.json"),
                      "baselines": {n: gallery[n]["baseline"] for n in names}, "cross": cross}, indent=2))


if __name__ == "__main__":
    main()
