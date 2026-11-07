"""Build the Agensi Pro zip: the public skill folder + the private Pro scripts, then pre-scan it.

Usage:
  python tools/build_pro_zip.py --pro ..\\flow-film-director-pro --out C:\\Users\\me\\Downloads\\flow-film-director.zip

--pro is a private folder (never committed to the public repo) whose files replace the Community stubs, e.g.
<pro>/scripts/identity_check.py. The zip has SKILL.md at its root, LF line endings, no caches or hidden files.
The zip is written only if tools/agensi_prescan.py finds nothing (edition pro).
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "flow-film-director"
TEXT_EXT = {".md", ".py", ".mjs", ".js", ".json", ".txt", ".patch", ".yaml", ".yml", ".toml"}


def load_prescan():
    spec = importlib.util.spec_from_file_location("agensi_prescan", ROOT / "tools" / "agensi_prescan.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def collect(base: Path) -> dict[str, Path]:
    out = {}
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(base).as_posix()
        if p.is_file() and "__pycache__" not in rel and not any(part.startswith(".") for part in rel.split("/")):
            out[rel] = p
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pro", required=True, type=Path, help="private folder with the real Pro files")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()

    files = collect(SKILL)
    pro = collect(a.pro)
    unknown = [r for r in pro if r not in files]
    if unknown:
        print("Pro files that do not replace a skill file (check the paths):", *unknown, sep="\n  ")
        return 1
    files.update(pro)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_zip = Path(tmp) / "pro.zip"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, src in files.items():
                data = src.read_bytes()
                if src.suffix.lower() in TEXT_EXT:
                    data = data.replace(b"\r\n", b"\n")
                z.writestr(rel, data)
        findings = load_prescan().scan(tmp_zip, "pro")
        if findings:
            print(*findings, sep="\n")
            print(f"{len(findings)} finding(s) - zip NOT written")
            return 1
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_bytes(tmp_zip.read_bytes())
    print(f"wrote {a.out} ({len(files)} files, {len(pro)} Pro overrides, pre-scan clean)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
