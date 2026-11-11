"""Build the Agensi package: SKILL.md + references + one self-contained file per script, then pre-scan it.

Agensi delivers skills through its MCP server and runs each script alone from a temporary file, so every script
must work without the other files of the skill. This bundles each entry script with the modules it imports
(tools/bundle_scoped.py), embeds the flow-mcp patch text into patch_flow_mcp.py, and refuses to write the zip if
the pre-scan finds anything.

    python tools/build_agensi.py --pro ..\\flow-film-director-pro --out C:\\Users\\me\\Downloads\\flow-film-director-AGENSI.zip
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
SCRIPTS = SKILL / "scripts"
LIBRARIES = {"facekit", "motionkit", "audiokit", "editkit", "voicekit"}   # imported by the scripts, never run alone
MARKER = "EMBEDDED_PATCHES: dict = {}"
NOTE = ("  Each script is one self-contained file (the helper modules it needs are bundled inside it), so it runs "
        "exactly as shipped, even when copied alone to a temporary folder.\n")


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def entries() -> list[str]:
    return sorted(f.stem for f in SCRIPTS.glob("*.py") if f.stem not in LIBRARIES)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pro", required=True, type=Path, help="private folder with the real Pro files (<pro>/scripts/*.py)")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    bundler = load("bundle_scoped", ROOT / "tools" / "bundle_scoped.py").Bundler([a.pro / "scripts", SCRIPTS])

    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "agensi.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            skill = (SKILL / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
            anchor = "- **Scripts** (`<skill_dir>/scripts/`, run with the skill's own Python `PY` from Phase 0):\n"
            if anchor not in skill:
                print("SKILL.md: the Scripts line moved; update NOTE anchor in build_agensi.py")
                return 1
            z.writestr("SKILL.md", skill.replace(anchor, anchor + NOTE))
            for ref in sorted((SKILL / "references").glob("*.md")):
                z.writestr(f"references/{ref.name}", ref.read_text(encoding="utf-8").replace("\r\n", "\n"))
            z.writestr("scripts/run_stage.mjs", (SCRIPTS / "run_stage.mjs").read_text(encoding="utf-8").replace("\r\n", "\n"))
            for name in entries():
                code = bundler.build(name, f"Flow Film Director - {name}.py")
                if name == "patch_flow_mcp":
                    patches = {p.name: p.read_text(encoding="utf-8").replace("\r\n", "\n")
                               for p in sorted((SKILL / "flow-mcp-patches").iterdir()) if p.is_file()}
                    if code.count(MARKER) != 1:
                        print("patch_flow_mcp.py: embed marker not found")
                        return 1
                    code = code.replace(MARKER, "EMBEDDED_PATCHES: dict = " + repr(patches))
                z.writestr(f"scripts/{name}.py", code)
                print(f"  scripts/{name}.py  {len(code.encode()) // 1024} KB")

        findings = load("agensi_prescan", ROOT / "tools" / "agensi_prescan.py").scan(zpath, "pro")
        if findings:
            print(*findings, sep="\n")
            print(f"{len(findings)} finding(s) - zip NOT written")
            return 1
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_bytes(zpath.read_bytes())
    print(f"wrote {a.out} (pre-scan clean)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
