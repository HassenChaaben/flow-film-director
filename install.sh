#!/usr/bin/env bash
# Flow Film Director — Master One-Click Installer for macOS / Linux.
# Automatically sets up Google Antigravity, Claude Code, flow-mcp bridge, Remotion video editing,
# character voices, and isolated Python environments.
#
# Usage:
#   ./install.sh                  # Interactive menu
#   ./install.sh --yes            # Non-interactive with defaults
#   ./install.sh --antigravity-only
#   ./install.sh --claude-only
#   ./install.sh --with-voices

set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

py="$(command -v python3 || command -v python || true)"
[ -n "$py" ] || { echo "Python 3.10+ not found on PATH. Please install Python and re-run."; exit 1; }

py_script="$here/install.py"
[ -f "$py_script" ] || { echo "Installer script not found: $py_script"; exit 1; }

pass_args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --antigravity-only) pass_args+=(--target antigravity); shift ;;
    --claude-only) pass_args+=(--target claude); shift ;;
    --target) pass_args+=(--target "$2"); shift 2 ;;
    --flow-mcp-path) pass_args+=(--flow-mcp-path "$2"); shift 2 ;;
    *) pass_args+=("$1"); shift ;;
  esac
done

exec "$py" "$py_script" "${pass_args[@]}"
