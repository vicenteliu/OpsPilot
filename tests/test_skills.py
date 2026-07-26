"""Skill registry — load/parse SKILL.md + catalog + lexical match (issue #119)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opspilot.skills import SkillRegistry, parse_skill_md

_SKILL = """\
---
id: vpn-auth
name: VPN auth failures
trigger: A user cannot authenticate to the VPN.
allowed_tools:
  - kb_search
trust: internal
---

# VPN auth failures

1. Check the account.
2. Check MFA.
"""


def test_parse_skill_md() -> None:
    s = parse_skill_md(_SKILL, fallback_id="x")
    assert s.id == "vpn-auth"
    assert s.name == "VPN auth failures"
    assert s.trigger.startswith("A user cannot authenticate")
    assert s.allowed_tools == ["kb_search"]
    assert s.trust == "internal"
    assert "Check the account" in s.body
    assert not s.body.startswith("---")  # frontmatter stripped


def test_parse_uses_use_when_alias_and_fallback_id() -> None:
    s = parse_skill_md("---\nuse_when: when X happens\n---\n\nbody", fallback_id="fb")
    assert s.id == "fb"
    assert s.name == "fb"  # falls back to id
    assert s.trigger == "when X happens"


def test_parse_rejects_missing_frontmatter() -> None:
    with pytest.raises(ValueError):
        parse_skill_md("no frontmatter here", fallback_id="x")


def _write(base: Path, sid: str, text: str) -> None:
    d = base / sid
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(text, encoding="utf-8")


def test_load_scans_dirs_and_skips_malformed(tmp_path: Path) -> None:
    _write(tmp_path, "vpn-auth", _SKILL)
    _write(tmp_path, "broken", "no frontmatter")  # skipped, not fatal
    _write(tmp_path, "printer", _SKILL.replace("vpn-auth", "printer").replace("VPN", "Printer"))
    reg = SkillRegistry.load(tmp_path)
    assert len(reg) == 2
    assert {e["id"] for e in reg.catalog()} == {"vpn-auth", "printer"}
    assert reg.get("vpn-auth") is not None
    assert reg.get("nope") is None


def test_load_missing_dir_is_empty(tmp_path: Path) -> None:
    reg = SkillRegistry.load(tmp_path / "does-not-exist")
    assert len(reg) == 0
    assert reg.catalog() == []


def test_match_picks_best_overlap_or_none(tmp_path: Path) -> None:
    _write(tmp_path, "vpn-auth", _SKILL)
    reg = SkillRegistry.load(tmp_path)
    assert reg.match("the vpn login keeps failing").id == "vpn-auth"  # "vpn" overlaps
    assert reg.match("how do I order a laptop") is None  # no overlap
    assert reg.match("") is None
