"""Build the zip you email to a Pro buyer: the whole project (with the one-click installer) + the Pro scripts.

    python tools/build_client_zip.py --pro ..\\flow-film-director-pro --out C:\\Users\\me\\Downloads\\flow-film-director-pro-installer.zip

The buyer unzips it and runs `python install.py` (or install.ps1 / install.sh): skills, agent, flow-mcp,
Python environments and MCP registration for Claude Code and Antigravity are all set up in one step.
This zip is for direct delivery only. The Agensi upload stays the skill-only zip from build_pro_zip.py.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_SCRIPTS = "skills/flow-film-director/scripts/"
PREFIX = "flow-film-director-pro/"
TEXT_EXT = {".md", ".py", ".mjs", ".js", ".json", ".txt", ".patch", ".yaml", ".yml", ".toml", ".sh"}

README = """FLOW FILM DIRECTOR PRO - INSTALL
================================

Thank you for buying Flow Film Director Pro!

1. Unzip this folder anywhere (for example your Documents folder).
2. Open a terminal in the unzipped "flow-film-director-pro" folder.
3. Run ONE of these:
     Windows:        .\\install.ps1          (or: python install.py)
     macOS / Linux:  ./install.sh           (or: python3 install.py)
4. Answer the questions (or add -y to accept the defaults).

The installer sets up everything: the skills and the video-creator agent for
Claude Code and Google Antigravity, flow-mcp, the Python environments and the
MCP servers. Your other Antigravity and Claude settings are kept as they are.

Then restart Claude Code / Antigravity and say:
  "Use flow-film-director to make a 20-second ad for my product"

Check the Pro features are active:
  python ~/.claude/skills/flow-film-director/scripts/identity_check.py --help
(it must NOT print "[PRO FEATURE]").

Requirements: Python 3.10+, Node.js 22+, Git. Optional: ffmpeg, Voicebox.
Help: reply to the email you received this zip with, or message the author on Agensi.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pro", required=True, type=Path, help="private folder with the real Pro files")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()

    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True)
    files = {f: ROOT / f for f in tracked.stdout.splitlines()
             if not f.startswith(("examples/showcase/", ".github/", "tools/", "tests/")) and (ROOT / f).is_file()}
    overrides = 0
    for p in sorted(a.pro.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            rel = p.relative_to(a.pro).as_posix()
            target = "skills/flow-film-director/" + rel
            if target not in files:
                print(f"Pro file does not replace a project file: {rel}")
                return 1
            files[target] = p
            overrides += 1

    a.out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, src in sorted(files.items()):
            data = src.read_bytes()
            if src.suffix.lower() in TEXT_EXT:
                data = data.replace(b"\r\n", b"\n")
            z.writestr(PREFIX + rel, data)
        z.writestr(PREFIX + "INSTALL-PRO.txt", README)
    stubs = [n for n in files if n.startswith(SKILL_SCRIPTS) and b"[PRO FEATURE]" in files[n].read_bytes()]
    if stubs:
        print("WARNING: Community stubs still inside:", *stubs, sep="\n  ")
        return 1
    print(f"wrote {a.out} ({len(files) + 1} files, {overrides} Pro scripts, no Community stubs left)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
