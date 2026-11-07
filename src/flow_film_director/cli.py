"""Command Line Interface for Flow Film Director."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def get_version() -> str:
    from . import __version__
    return __version__


def cmd_setup(args: argparse.Namespace) -> int:
    """Run interactive or automated environment setup."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    installer = repo_root / "install.py"
    if not installer.exists():
        print(f"Error: installer script not found at {installer}")
        return 1

    cmd = [sys.executable, str(installer)]
    if args.yes:
        cmd.append("--yes")
    if args.target:
        cmd.extend(["--target", args.target])
    return subprocess.run(cmd).returncode


def cmd_audit(args: argparse.Namespace) -> int:
    """Run voice engine audit."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    script = repo_root / "skills" / "flow-film-director" / "scripts" / "setup_voice_engine.py"
    if not script.exists():
        print(f"Error: setup_voice_engine.py not found at {script}")
        return 1
    return subprocess.run([sys.executable, str(script), "--audit"]).returncode


def cmd_test(args: argparse.Namespace) -> int:
    """Run offline synthetic media test suite."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    runner = repo_root / "tests" / "run_tests.py"
    if not runner.exists():
        print(f"Error: test runner not found at {runner}")
        return 1
    return subprocess.run([sys.executable, str(runner)]).returncode


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="flow-film-director",
        description="🎬 Flow Film Director: The AI Film Crew for Google Flow & Programmatic Video Engineering",
    )
    parser.add_argument("--version", "-v", action="version", version=f"%(prog)s {get_version()}")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # setup
    p_setup = subparsers.add_parser("setup", help="Configure environment and agent skills")
    p_setup.add_argument("--yes", "-y", action="store_true", help="Non-interactive setup")
    p_setup.add_argument("--target", choices=["antigravity", "claude", "both"], default="both", help="Target assistant")
    p_setup.set_defaults(func=cmd_setup)

    # audit-voices
    p_audit = subparsers.add_parser("audit-voices", help="Audit local Voicebox and voice engines")
    p_audit.set_defaults(func=cmd_audit)

    # test
    p_test = subparsers.add_parser("test", help="Run offline synthetic media verification tests")
    p_test.set_defaults(func=cmd_test)

    args = parser.parse_args()
    if hasattr(args, "func"):
        sys.exit(args.func(args))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
