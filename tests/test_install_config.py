"""The installer must handle empty Antigravity config files and never overwrite invalid ones."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def inst(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ffd_install", ROOT / "install.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setattr(sys, "argv", ["install.py"])
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ANTIGRAVITY_MCP_CFG", tmp_path / "mcp_config.json")
    monkeypatch.setattr(mod, "ANTIGRAVITY_CFG", tmp_path / "config.json")
    return mod


def test_empty_mcp_config_is_filled(inst):
    inst.ANTIGRAVITY_MCP_CFG.write_text("", encoding="utf-8")
    inst.configure_antigravity_voicebox()
    assert "voicebox" in json.loads(inst.ANTIGRAVITY_MCP_CFG.read_text())["mcpServers"]


def test_other_mcp_servers_are_kept(inst):
    inst.ANTIGRAVITY_MCP_CFG.write_text(json.dumps({"mcpServers": {"mine": {"command": "x"}}}), encoding="utf-8")
    inst.configure_antigravity_mcp(Path("flow-mcp"))
    servers = json.loads(inst.ANTIGRAVITY_MCP_CFG.read_text())["mcpServers"]
    assert {"mine", "flow", "voicebox"} <= set(servers)


def test_invalid_mcp_config_is_never_overwritten(inst):
    bad = '{"mcpServers": {"mine": {"command": "x"}}, // my notes\n}'
    inst.ANTIGRAVITY_MCP_CFG.write_text(bad, encoding="utf-8")
    inst.configure_antigravity_mcp(Path("flow-mcp"))
    assert inst.ANTIGRAVITY_MCP_CFG.read_text(encoding="utf-8") == bad


def test_empty_config_json_enables_plugin(inst, tmp_path, monkeypatch):
    inst.ANTIGRAVITY_CFG.write_text("", encoding="utf-8")
    monkeypatch.setattr(inst, "ANTIGRAVITY_PLUGIN", tmp_path / "plugins" / "flow-film-director")
    inst.install_antigravity_plugin()
    assert json.loads(inst.ANTIGRAVITY_CFG.read_text())["plugins"]["flow-film-director"] == {"enabled": True}
