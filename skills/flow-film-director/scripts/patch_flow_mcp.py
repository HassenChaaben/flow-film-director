"""Bring a flow-mcp checkout up to what flow-film-director needs, from the patch files in ../flow-mcp-patches.

flow-film-director.patch (made against github.com/GTAI-1/flow-mcp main, src/ only) adds:
  - exact character name match when attaching asset:<Name> (no prefix collisions), Characters tab first
  - parallel batches (scene option `parallel`), human-paced submits (20-40 s apart, batches of 3),
    Flow's "unusual activity" refusal reported
  - `builder_lock` (the prompt owns the identity text), per-character lock wording
  - 3-15 s durations, word-by-word model matching

Usage:
  python patch_flow_mcp.py --check [path_to_flow_mcp]     report only (exit 0 = all applied, 3 = something to apply)
  python patch_flow_mcp.py [path_to_flow_mcp]             apply what is missing, then `npm run build`
Uses `git apply` (works in any folder) and never touches anything outside flow-mcp/src.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PATCH_DIR = Path(__file__).resolve().parent.parent / "flow-mcp-patches"
# Filled in by the Agensi build (one self-contained script, no patch folder next to it): {file name: text}.
EMBEDDED_PATCHES: dict = {}
NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}


def load_patches() -> tuple[list[tuple[str, str]], str]:
    """(name, text) of every patch in order, plus the BASE note; folder first, embedded copy second."""
    if PATCH_DIR.is_dir() and any(PATCH_DIR.glob("*.patch")):
        files = {f.name: f.read_text(encoding="utf-8") for f in PATCH_DIR.iterdir() if f.is_file()}
    else:
        files = dict(EMBEDDED_PATCHES)
    patches = sorted((n, t) for n, t in files.items() if n.endswith(".patch"))
    return patches, files.get("BASE.txt", "").strip()


def find_flow_mcp(hint: str | None = None) -> Path | None:
    cands = [Path(hint)] if hint else []
    cands += [Path.cwd() / "flow-mcp", Path.cwd().parent / "flow-mcp", Path.home() / "tools" / "flow-mcp", Path.home() / "flow-mcp"]
    for c in cands:
        if (c / "src" / "flow.ts").exists():
            return c.resolve()
    return None


def git_apply(root: Path, patch: str, *flags: str) -> bool:
    p = subprocess.run(["git", "apply", "--whitespace=nowarn", "--ignore-whitespace", *flags],
                       cwd=root, input=patch, capture_output=True, text=True, encoding="utf-8", **NO_WINDOW)
    return p.returncode == 0


def main():
    args = [a for a in sys.argv[1:] if a != "--check"]
    check = "--check" in sys.argv[1:]
    root = find_flow_mcp(args[0] if args else None)
    if not root:
        print("Could not find flow-mcp. Pass the folder: python patch_flow_mcp.py <path_to_flow_mcp>")
        sys.exit(1)
    if not shutil.which("git"):
        print("git is needed to apply the patches")
        sys.exit(1)
    patches, base = load_patches()
    if not patches:
        print("No patch files found (flow-mcp-patches folder missing).")
        sys.exit(1)
    missing = []
    for name, text in patches:
        if git_apply(root, text, "--reverse", "--check"):
            print(f"  applied  {name}")
        elif git_apply(root, text, "--check"):
            print(f"  missing  {name}")
            missing.append((name, text))
        else:
            print(f"  CONFLICT {name} (flow-mcp changed here; apply it by hand or update flow-mcp)")
            if base:
                print("  " + base)
            missing.append((name, text))
    if not missing:
        print(f"flow-mcp at {root} has every flow-film-director patch.")
        sys.exit(0)
    if check:
        print(f"{len(missing)} patch(es) to apply: run patch_flow_mcp.py without --check")
        sys.exit(3)
    for name, text in missing:
        if not git_apply(root, text):
            print(f"failed to apply {name}; stopping (nothing after it was applied)")
            sys.exit(1)
        print(f"  applied {name}")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    b = subprocess.run([npm, "run", "build"], cwd=root, capture_output=True, text=True, **NO_WINDOW)
    if b.returncode != 0:
        print("npm run build failed:\n" + (b.stderr or b.stdout)[-3000:])
        sys.exit(1)
    print("flow-mcp rebuilt - restart your agent (or the flow MCP server) to load it.")


if __name__ == "__main__":
    main()
