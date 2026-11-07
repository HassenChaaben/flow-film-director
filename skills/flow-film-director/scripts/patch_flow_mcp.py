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


def find_flow_mcp(hint: str | None = None) -> Path | None:
    cands = [Path(hint)] if hint else []
    cands += [Path(os.environ["FLOW_MCP_DIR"])] if os.environ.get("FLOW_MCP_DIR") else []
    cands += [Path.cwd() / "flow-mcp", Path.cwd().parent / "flow-mcp", Path.home() / "tools" / "flow-mcp", Path.home() / "flow-mcp"]
    for c in cands:
        if (c / "src" / "flow.ts").exists():
            return c.resolve()
    return None


def git_apply(root: Path, patch: Path, *flags: str) -> bool:
    p = subprocess.run(["git", "apply", "--whitespace=nowarn", "--ignore-whitespace", *flags, str(patch)],
                       cwd=root, capture_output=True, text=True)
    return p.returncode == 0


def main():
    args = [a for a in sys.argv[1:] if a != "--check"]
    check = "--check" in sys.argv[1:]
    root = find_flow_mcp(args[0] if args else None)
    if not root:
        print("Could not find flow-mcp. Pass the folder: python patch_flow_mcp.py <path_to_flow_mcp> (or set FLOW_MCP_DIR)")
        sys.exit(1)
    if not shutil.which("git"):
        print("git is needed to apply the patches")
        sys.exit(1)
    patches = sorted(PATCH_DIR.glob("*.patch"))
    missing = []
    for p in patches:
        if git_apply(root, p, "--reverse", "--check"):
            print(f"  applied  {p.name}")
        elif git_apply(root, p, "--check"):
            print(f"  missing  {p.name}")
            missing.append(p)
        else:
            base = (PATCH_DIR / "BASE.txt").read_text(encoding="utf-8").strip() if (PATCH_DIR / "BASE.txt").exists() else ""
            print(f"  CONFLICT {p.name} (flow-mcp changed here; apply it by hand or update flow-mcp)")
            if base:
                print("  " + base)
            missing.append(p)
    if not missing:
        print(f"flow-mcp at {root} has every flow-film-director patch.")
        sys.exit(0)
    if check:
        print(f"{len(missing)} patch(es) to apply: run patch_flow_mcp.py without --check")
        sys.exit(3)
    for p in missing:
        if not git_apply(root, p):
            print(f"failed to apply {p.name}; stopping (nothing after it was applied)")
            sys.exit(1)
        print(f"  applied {p.name}")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    b = subprocess.run([npm, "run", "build"], cwd=root, capture_output=True, text=True)
    if b.returncode != 0:
        print("npm run build failed:\n" + (b.stderr or b.stdout)[-3000:])
        sys.exit(1)
    print("flow-mcp rebuilt - restart your agent (or the flow MCP server) to load it.")


if __name__ == "__main__":
    main()
