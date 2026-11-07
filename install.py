#!/usr/bin/env python3
"""
Flow Film Director — Master One-Click All-in-One Installer
==========================================================
Installs and configures everything needed for Flow Film Director:
  1. The autonomous 'video-creator' agent in Google Antigravity and/or Claude Code.
  2. All core skills: flow-film-director, voice-cloning, edit-voice, and Remotion suite.
  3. The Google Flow MCP bridge (flow-mcp): clones, builds, patches, and registers the server.
  4. Remotion agent skills pack (remotion-dev/skills).
  5. Isolated Python runtime environments (~/.flow-film/venv and optional voice-venv).

Usage:
  python install.py                                  # Interactive menu with smart defaults
  python install.py --yes                            # Non-interactive with recommended defaults
  python install.py --target antigravity             # Install to Google Antigravity only
  python install.py --target claude                  # Install to Claude Code only
  python install.py --target both                    # Install to both Antigravity & Claude Code
  python install.py --with-voices                    # Include local PyTorch/CUDA voice cloning venv
  python install.py --flow-mcp-path "C:/path/flow-mcp" # Use existing flow-mcp checkout
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Configure stdout/stderr for utf-8 on Windows consoles to prevent cp1252 crash
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass



REPO_ROOT = Path(__file__).resolve().parent
SKILLS_SRC = REPO_ROOT / "skills"
AGENT_SRC = REPO_ROOT / "agents" / "video-creator.md"
PATCH_SCRIPT = SKILLS_SRC / "flow-film-director" / "scripts" / "patch_flow_mcp.py"
ENV_SCRIPT = SKILLS_SRC / "flow-film-director" / "scripts" / "setup_env.py"
VOICE_ENV_SCRIPT = SKILLS_SRC / "flow-film-director" / "scripts" / "setup_voice_env.py"

HOME = Path.home()
FLOW_FILM_DIR = HOME / ".flow-film"
FLOW_MCP_DEFAULT_DIR = FLOW_FILM_DIR / "flow-mcp"

# Antigravity paths
GEMINI_DIR = HOME / ".gemini"
ANTIGRAVITY_SKILLS = GEMINI_DIR / "config" / "skills"
ANTIGRAVITY_AGENTS = GEMINI_DIR / "config" / "agents"
ANTIGRAVITY_PLUGIN = GEMINI_DIR / "config" / "plugins" / "flow-film-director"
ANTIGRAVITY_MCP_CFG = GEMINI_DIR / "config" / "mcp_config.json"
ANTIGRAVITY_CFG = GEMINI_DIR / "config" / "config.json"

# Claude Code paths
CLAUDE_DIR = HOME / ".claude"
CLAUDE_SKILLS = CLAUDE_DIR / "skills"
CLAUDE_AGENTS = CLAUDE_DIR / "agents"


def color(text: str, code: str) -> str:
    if os.environ.get("NO_COLOR") or platform.system() == "Windows" and not os.environ.get("WT_SESSION"):
        # Basic Windows console fallback without ANSI escape issues
        try:
            os.system("")  # Enable VT100 on modern Windows terminal
            return f"\033[{code}m{text}\033[0m"
        except Exception:
            return text
    return f"\033[{code}m{text}\033[0m"


def green(text: str) -> str:
    return color(text, "32")


def cyan(text: str) -> str:
    return color(text, "36")


def yellow(text: str) -> str:
    return color(text, "33")


def red(text: str) -> str:
    return color(text, "31")


def bold(text: str) -> str:
    return color(text, "1")


def check_tool(name: str) -> str | None:
    path = shutil.which(name)
    return path


def run_cmd(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)


def prompt_choice(prompt: str, choices: list[str], default: str) -> str:
    choices_lower = [c.lower() for c in choices]
    while True:
        resp = input(f"{prompt} (default: {default}): ").strip().lower()
        if not resp:
            return default.lower()
        if resp in choices_lower:
            return resp
        print(f"Please enter one of: {', '.join(choices)}")


def prompt_yes_no(prompt: str, default: bool = True) -> bool:
    default_str = "Y/n" if default else "y/N"
    resp = input(f"{prompt} [{default_str}]: ").strip().lower()
    if not resp:
        return default
    return resp in ["y", "yes", "true", "1"]


def locate_existing_flow_mcp(hint_path: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if hint_path:
        candidates.append(Path(hint_path))
    if os.environ.get("FLOW_MCP_DIR"):
        candidates.append(Path(os.environ["FLOW_MCP_DIR"]))

    # Look in working dirs and home folders
    candidates += [
        FLOW_MCP_DEFAULT_DIR,
        REPO_ROOT.parent / "flow-mcp",
        REPO_ROOT / "flow-mcp",
        HOME / "tools" / "flow-mcp",
        HOME / "flow-mcp",
        Path.cwd() / "flow-mcp",
        Path.cwd().parent / "flow-mcp",
    ]

    # Look inside Antigravity's mcp_config.json if it exists
    if ANTIGRAVITY_MCP_CFG.exists():
        try:
            mcp_data = json.loads(ANTIGRAVITY_MCP_CFG.read_text(encoding="utf-8"))
            flow_entry = mcp_data.get("mcpServers", {}).get("flow", {})
            args = flow_entry.get("args", [])
            for arg in args:
                if "index.js" in arg:
                    cand = Path(arg).resolve().parent.parent
                    candidates.append(cand)
        except Exception:
            pass

    for c in candidates:
        if (c / "package.json").exists() and (c / "src" / "flow.ts").exists():
            return c.resolve()

    return None


def setup_flow_mcp(target_dir: Path) -> Path:
    print(cyan(f"  Cloning flow-mcp into {target_dir} ..."))
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if not target_dir.exists():
        subprocess.run(["git", "clone", "https://github.com/GTAI-1/flow-mcp.git", str(target_dir)], check=True)
    else:
        print(f"  Using existing directory at {target_dir}")

    npm_bin = shutil.which("npm") or "npm"
    print(cyan("  Installing flow-mcp npm dependencies ..."))
    subprocess.run([npm_bin, "install"], cwd=target_dir, check=True)

    print(cyan("  Building flow-mcp TypeScript bundle ..."))
    subprocess.run([npm_bin, "run", "build"], cwd=target_dir, check=True)

    dist_index = target_dir / "dist" / "index.js"
    if not dist_index.exists():
        raise RuntimeError(f"flow-mcp build failed: {dist_index} was not generated.")

    print(green(f"  ✓ flow-mcp successfully built at {dist_index}"))
    return target_dir


def patch_flow_mcp(flow_mcp_dir: Path) -> None:
    if not PATCH_SCRIPT.exists():
        return
    print(cyan("  Applying Flow Film Director character attachment patch to flow-mcp ..."))
    py_bin = sys.executable
    res = subprocess.run([py_bin, str(PATCH_SCRIPT), str(flow_mcp_dir)], capture_output=True, text=True)
    if res.returncode == 0:
        print(green("  ✓ flow-mcp patch verified and applied."))
    else:
        print(yellow(f"  Notice: patch status returned {res.returncode}. (May already be applied)."))


def configure_antigravity_voicebox() -> None:
    ANTIGRAVITY_MCP_CFG.parent.mkdir(parents=True, exist_ok=True)
    cfg_data = {"mcpServers": {}}
    if ANTIGRAVITY_MCP_CFG.exists():
        try:
            cfg_data = json.loads(ANTIGRAVITY_MCP_CFG.read_text(encoding="utf-8"))
        except Exception:
            cfg_data = {"mcpServers": {}}

    mcp_servers = cfg_data.setdefault("mcpServers", {})
    mcp_servers["voicebox"] = {
        "url": "http://127.0.0.1:17493/mcp",
        "transport": "http",
        "disabled": False,
    }
    ANTIGRAVITY_MCP_CFG.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
    print(green(f"  ✓ Configured 'voicebox' MCP server in Antigravity ({ANTIGRAVITY_MCP_CFG})"))


def configure_claude_voicebox() -> None:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return
    res_vb = subprocess.run([
        claude_bin, "mcp", "add", "--scope", "user", "voicebox", "--", "npx", "-y", "mcp-remote", "http://127.0.0.1:17493/mcp"
    ], capture_output=True, text=True)
    if res_vb.returncode == 0:
        print(green("  ✓ Registered 'voicebox' MCP server in Claude Code."))


def configure_antigravity_mcp(flow_mcp_dir: Path) -> None:
    ANTIGRAVITY_MCP_CFG.parent.mkdir(parents=True, exist_ok=True)
    cfg_data = {"mcpServers": {}}
    if ANTIGRAVITY_MCP_CFG.exists():
        try:
            cfg_data = json.loads(ANTIGRAVITY_MCP_CFG.read_text(encoding="utf-8"))
        except Exception:
            cfg_data = {"mcpServers": {}}

    dist_index = (flow_mcp_dir / "dist" / "index.js").resolve()
    node_bin = shutil.which("node") or "node"

    # Configure server
    mcp_servers = cfg_data.setdefault("mcpServers", {})
    mcp_servers["flow"] = {
        "command": node_bin,
        "args": [str(dist_index)],
        "disabled": False,
        "timeoutSeconds": 600,
    }
    mcp_servers["voicebox"] = {
        "url": "http://127.0.0.1:17493/mcp",
        "transport": "http",
        "disabled": False,
    }

    ANTIGRAVITY_MCP_CFG.write_text(json.dumps(cfg_data, indent=2), encoding="utf-8")
    print(green(f"  ✓ Registered 'flow' & 'voicebox' MCP servers in Antigravity ({ANTIGRAVITY_MCP_CFG})"))


def configure_claude_mcp(flow_mcp_dir: Path) -> None:
    dist_index = (flow_mcp_dir / "dist" / "index.js").resolve()
    claude_bin = shutil.which("claude")
    if not claude_bin:
        print(yellow("  'claude' CLI not found on PATH. Claude Code MCP server can be added via:"))
        print(f"    claude mcp add --scope user flow -- node \"{dist_index}\"")
        return

    print(cyan(f"  Registering 'flow' in Claude Code with: claude mcp add --scope user flow ..."))
    res = subprocess.run([
        claude_bin, "mcp", "add", "--scope", "user", "flow", "--", "node", str(dist_index)
    ], capture_output=True, text=True)
    if res.returncode == 0:
        print(green("  ✓ Registered 'flow' MCP server in Claude Code."))
    else:
        print(yellow(f"  Claude Code registration message: {res.stderr or res.stdout}"))

    # Also register Voicebox MCP in Claude Code
    configure_claude_voicebox()


def copy_skills(dest_root: Path, label: str) -> None:
    dest_root.mkdir(parents=True, exist_ok=True)
    installed_count = 0
    for item in SKILLS_SRC.iterdir():
        if item.is_dir() and (item / "SKILL.md").exists():
            target_skill = dest_root / item.name
            if target_skill.exists():
                shutil.rmtree(target_skill)
            shutil.copytree(
                item,
                target_skill,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git")
            )
            installed_count += 1
    print(green(f"  ✓ Installed {installed_count} skills into [{label}] ({dest_root})"))


def install_agent(dest_dir: Path, label: str) -> None:
    if not AGENT_SRC.exists():
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    target_agent = dest_dir / "video-creator.md"
    shutil.copy2(AGENT_SRC, target_agent)
    print(green(f"  ✓ Installed 'video-creator' agent into [{label}] ({target_agent})"))


def install_antigravity_plugin() -> None:
    ANTIGRAVITY_PLUGIN.mkdir(parents=True, exist_ok=True)
    plugin_agents = ANTIGRAVITY_PLUGIN / "agents"
    plugin_skills = ANTIGRAVITY_PLUGIN / "skills"
    plugin_agents.mkdir(parents=True, exist_ok=True)
    plugin_skills.mkdir(parents=True, exist_ok=True)

    manifest_src = REPO_ROOT / "plugin.json"
    if manifest_src.exists():
        shutil.copy2(manifest_src, ANTIGRAVITY_PLUGIN / "plugin.json")

    if AGENT_SRC.exists():
        shutil.copy2(AGENT_SRC, plugin_agents / "video-creator.md")

    for item in SKILLS_SRC.iterdir():
        if item.is_dir() and (item / "SKILL.md").exists():
            target_skill = plugin_skills / item.name
            if target_skill.exists():
                shutil.rmtree(target_skill)
            shutil.copytree(
                item,
                target_skill,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git")
            )

    # Enable in config.json
    if ANTIGRAVITY_CFG.exists():
        try:
            cfg = json.loads(ANTIGRAVITY_CFG.read_text(encoding="utf-8"))
            plugins = cfg.setdefault("plugins", {})
            if "flow-film-director" not in plugins:
                plugins["flow-film-director"] = {"enabled": True}
                ANTIGRAVITY_CFG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
                print(green("  ✓ Enabled plugin 'flow-film-director' in Antigravity config.json"))
        except Exception:
            pass

    print(green(f"  ✓ Antigravity plugin package registered at {ANTIGRAVITY_PLUGIN}"))


def install_remotion_global() -> None:
    npx_bin = shutil.which("npx")
    if not npx_bin:
        print(yellow("  Notice: npx not found on PATH. Remotion global skill install skipped."))
        return

    print(cyan("  Installing Remotion Agent Skills globally via npx skills@latest ..."))
    cmd = [npx_bin, "-y", "skills@latest", "add", "remotion-dev/skills", "-g", "-y"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        print(green("  ✓ Official Remotion Agent Skills installed into ~/.agents/skills/"))
    else:
        print(yellow("  Notice: global npx skill install completed with message: " + (res.stdout or res.stderr)[:100]))


def setup_python_environments(with_voices: bool) -> None:
    py_bin = sys.executable
    if ENV_SCRIPT.exists():
        print(cyan("  Preparing isolated Python runtime (~/.flow-film/venv) ..."))
        res = subprocess.run([py_bin, str(ENV_SCRIPT)])
        if res.returncode == 0:
            print(green("  ✓ Flow Film Director Python venv is ready with face & pose models."))
        else:
            print(red(f"  Warning: setup_env.py exited with code {res.returncode}."))

    if with_voices:
        if VOICE_ENV_SCRIPT.exists():
            print(cyan("  Preparing isolated character-voice environment (~/.flow-film/voice-venv, ~3-4 GB) ..."))
            res = subprocess.run([py_bin, str(VOICE_ENV_SCRIPT)])
            if res.returncode == 0:
                print(green("  ✓ Voice cloning environment ready (PyTorch from PyPI)."))
            else:
                print(red(f"  Warning: setup_voice_env.py exited with code {res.returncode}."))
    else:
        print(cyan("  Skipping local voice cloning venv (Voicebox desktop app still works without it)."))


def main() -> int:
    parser = argparse.ArgumentParser(description="Master One-Click Installer for Flow Film Director")
    parser.add_argument("--target", choices=["antigravity", "claude", "both"], default=None,
                        help="Target assistant platform to install into")
    parser.add_argument("--flow-mcp-path", type=str, default=None,
                        help="Path to an existing flow-mcp checkout")
    parser.add_argument("--setup-flow-mcp", action="store_true",
                        help="Automatically clone, build, patch, and register flow-mcp")
    parser.add_argument("--skip-flow-mcp", action="store_true",
                        help="Skip flow-mcp build and MCP registration")
    parser.add_argument("--with-remotion", action="store_true", default=True,
                        help="Install Remotion agent skills pack (default: True)")
    parser.add_argument("--skip-remotion", action="store_true",
                        help="Skip Remotion agent skills installation")
    parser.add_argument("--with-voices", action="store_true",
                        help="Install local character voice environment (~3-4 GB, PyTorch CUDA)")
    parser.add_argument("--skip-python", action="store_true",
                        help="Skip Python venv setup")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Run non-interactively using defaults")

    args = parser.parse_args()

    print()
    print(bold("========================================================================="))
    print(bold("  🎬 Flow Film Director — Master One-Click All-in-One Installer"))
    print(bold("========================================================================="))
    print()

    # System diagnosis
    node_v = check_tool("node")
    npm_v = check_tool("npm")
    py_v = check_tool("python") or check_tool("python3") or sys.executable
    git_v = check_tool("git")
    ffmpeg_v = check_tool("ffmpeg")
    claude_v = check_tool("claude")

    print(cyan("System Environment Check:"))
    print(f"  • OS:         {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"  • Python:     {sys.version.split()[0]} ({py_v})")
    print(f"  • Node.js:    {'Found (' + node_v + ')' if node_v else yellow('Missing (required for flow-mcp)')}")
    print(f"  • npm:        {'Found' if npm_v else yellow('Missing')}")
    print(f"  • Git:        {'Found' if git_v else yellow('Missing')}")
    print(f"  • FFmpeg:     {'Found' if ffmpeg_v else yellow('Missing (install for video rendering)')}")
    print(f"  • Claude CLI: {'Found' if claude_v else 'Not installed (optional for Claude Code)'}")
    print()

    # Interactive prompts if not specified and not --yes
    if args.yes:
        target = args.target or "both"
        do_flow_mcp = not args.skip_flow_mcp
        do_remotion = not args.skip_remotion
        with_voices = args.with_voices
    else:
        # Prompt target
        if args.target:
            target = args.target
        else:
            print(bold("[1/4] Select Target Assistant Platform:"))
            print("  1) Google Antigravity")
            print("  2) Claude Code")
            print("  3) Both (Google Antigravity & Claude Code)  [Recommended]")
            c = prompt_choice("Select target [1/2/3]", ["1", "2", "3", "antigravity", "claude", "both"], default="3")
            target = "antigravity" if c in ["1", "antigravity"] else "claude" if c in ["2", "claude"] else "both"

        # Prompt flow-mcp
        if args.skip_flow_mcp:
            do_flow_mcp = False
        elif args.setup_flow_mcp:
            do_flow_mcp = True
        else:
            print()
            print(bold("[2/4] Google Flow MCP Bridge (flow-mcp):"))
            print("  Automatically install, build, patch, and register flow-mcp in your assistant?")
            do_flow_mcp = prompt_yes_no("Configure flow-mcp bridge?", default=True)

        # Prompt remotion
        if args.skip_remotion:
            do_remotion = False
        else:
            print()
            print(bold("[3/4] Programmatic Video Editing (Remotion):"))
            print("  Install the official Remotion agent skills for declarative React timeline video editing?")
            do_remotion = prompt_yes_no("Install Remotion skills?", default=True)

        # Prompt voice models
        if args.with_voices:
            with_voices = True
        else:
            print()
            print(bold("[4/4] Local Voice Cloning Suite:"))
            print("  Install the local PyTorch / CUDA voice cloning runtime (~3-4 GB)?")
            print("  (Note: the Voicebox desktop app works without these local models).")
            with_voices = prompt_yes_no("Install local PyTorch voice models?", default=False)

    print()
    print(bold("Executing installation plan..."))
    print("-" * 60)

    # 1. Install Skills and Agent
    if target in ["antigravity", "both"]:
        print(bold("▶ Step 1: Installing into Google Antigravity..."))
        copy_skills(ANTIGRAVITY_SKILLS, "Antigravity")
        install_agent(ANTIGRAVITY_AGENTS, "Antigravity")
        install_antigravity_plugin()
        configure_antigravity_voicebox()

    if target in ["claude", "both"]:
        print(bold("▶ Step 2: Installing into Claude Code..."))
        copy_skills(CLAUDE_SKILLS, "Claude Code")
        install_agent(CLAUDE_AGENTS, "Claude Code")
        configure_claude_voicebox()

    # 2. Remotion Global Skills
    if do_remotion:
        print(bold("▶ Step 3: Installing Remotion Agent Skills..."))
        install_remotion_global()

    # 3. flow-mcp Setup & Configuration
    if do_flow_mcp:
        print(bold("▶ Step 4: Configuring Google Flow MCP Bridge..."))
        existing_flow = locate_existing_flow_mcp(args.flow_mcp_path)
        if existing_flow:
            print(green(f"  ✓ Located existing flow-mcp installation at: {existing_flow}"))
            flow_dir = existing_flow
        else:
            flow_dir = setup_flow_mcp(FLOW_MCP_DEFAULT_DIR)

        # Apply patch
        patch_flow_mcp(flow_dir)

        # Configure assistant MCP files
        if target in ["antigravity", "both"]:
            configure_antigravity_mcp(flow_dir)
        if target in ["claude", "both"]:
            configure_claude_mcp(flow_dir)

    # 4. Python Environment
    if not args.skip_python:
        print(bold("▶ Step 5: Preparing Isolated Python Environments..."))
        setup_python_environments(with_voices)

    print()
    print(bold("========================================================================="))
    print(green(bold("  🎉 All Installations & Configurations Completed Successfully!")))
    print(bold("========================================================================="))
    print()
    print("Next steps:")
    if do_flow_mcp:
        flow_path = locate_existing_flow_mcp(args.flow_mcp_path) or FLOW_MCP_DEFAULT_DIR
        print(f"  1. Sign in to Google Flow in your browser:")
        print(cyan(f"     cd \"{flow_path}\" && npm run login"))
    print("  2. Restart your AI Assistant (Google Antigravity and/or Claude Code).")
    print("  3. Direct your film:")
    if target in ["antigravity", "both"]:
        print(f"     • In {bold('Antigravity')}: Select '{cyan('video-creator')}' from the Agents dropdown (bottom bar).")
    if target in ["claude", "both"]:
        print(f"     • In {bold('Claude Code')}: Ask {cyan('Check my Flow session')} or invoke {cyan('/flow-film-director')}.")
    print("  4. Local Voice Studio (Jamie Pine's Voicebox):")
    print(f"     • Voicebox runs 100% free locally: {cyan('https://github.com/jamiepine/voicebox')}")
    print(f"     • Keep Voicebox open to enable instant local voice cloning & speech via MCP (port 17493).")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
