"""The shipped skill folder must pass the local Agensi pre-scan with zero findings."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("agensi_prescan", ROOT / "tools" / "agensi_prescan.py")
prescan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prescan)


def test_skill_folder_is_clean():
    findings = prescan.scan(ROOT / "skills" / "flow-film-director", "community")
    assert findings == [], "\n".join(findings)


def test_scanner_catches_known_bad_patterns(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: flow-film-director\ndescription: x\n---\nsee https://evil.example\n")
    (tmp_path / "a.py").write_text("import os\nk = os.environ['KEY']\nhair = 'curly'\n")
    findings = "\n".join(prescan.scan(tmp_path))
    assert "evil.example" in findings
    assert "os.environ" in findings
    assert "'curl'" in findings


def test_pro_edition_rejects_community_stubs(tmp_path):
    (tmp_path / "SKILL.md").write_text("---\nname: flow-film-director\ndescription: x\n---\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "fast_review.py").write_text('print("[PRO FEATURE] buy")\n')
    assert any("stub" in f for f in prescan.scan(tmp_path, "pro"))
    assert prescan.scan(tmp_path, "community") == []
