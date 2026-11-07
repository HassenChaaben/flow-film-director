<#
  Flow Film Director — Master One-Click Installer for Windows.
  Automatically sets up Google Antigravity, Claude Code, flow-mcp bridge, Remotion video editing,
  character voices, and isolated Python environments.

  Usage:
    powershell -ExecutionPolicy Bypass -File install.ps1                    # Interactive menu
    powershell -ExecutionPolicy Bypass -File install.ps1 -Yes               # Non-interactive with defaults
    powershell -ExecutionPolicy Bypass -File install.ps1 -AntigravityOnly   # Install to Antigravity only
    powershell -ExecutionPolicy Bypass -File install.ps1 -ClaudeOnly        # Install to Claude Code only
    powershell -ExecutionPolicy Bypass -File install.ps1 -WithVoices        # Include local voice cloning runtime (~3-4 GB)
#>
param(
    [string]$Target,
    [switch]$ClaudeOnly,
    [switch]$AntigravityOnly,
    [switch]$WithVoices,
    [switch]$SkipFlowMcp,
    [switch]$SetupFlowMcp,
    [switch]$SkipRemotion,
    [switch]$SkipPython,
    [switch]$Yes,
    [string]$FlowMcpPath
)

$ErrorActionPreference = "Stop"

$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { $py = (Get-Command python3 -ErrorAction SilentlyContinue) }
if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue) }
if (-not $py) {
    throw "Python 3.10+ not found on PATH. Please install Python from https://www.python.org/ and re-run."
}

$pyScript = Join-Path $PSScriptRoot "install.py"
if (-not (Test-Path $pyScript)) {
    throw "Installer script not found: $pyScript"
}

$passArgs = @()
if ($Target) { $passArgs += @("--target", $Target) }
if ($ClaudeOnly) { $passArgs += @("--target", "claude") }
if ($AntigravityOnly) { $passArgs += @("--target", "antigravity") }
if ($WithVoices) { $passArgs += "--with-voices" }
if ($SkipFlowMcp) { $passArgs += "--skip-flow-mcp" }
if ($SetupFlowMcp) { $passArgs += "--setup-flow-mcp" }
if ($SkipRemotion) { $passArgs += "--skip-remotion" }
if ($SkipPython) { $passArgs += "--skip-python" }
if ($Yes) { $passArgs += "--yes" }
if ($FlowMcpPath) { $passArgs += @("--flow-mcp-path", $FlowMcpPath) }

& $py.Source $pyScript @passArgs
exit $LASTEXITCODE
