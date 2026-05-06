"""Tests for iteration/registry.py — lineage I/O and promote_variant."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from opspilot.iteration.registry import (
    append_lineage_entry,
    compute_skill_checksum,
    promote_variant,
    read_lineage,
    read_variant_meta,
    verify_variant_checksum,
)
from opspilot.iteration.types import LineageEntry


def _entry(**kwargs) -> LineageEntry:
    defaults = dict(
        version="1.1.0",
        parent="1.0.0",
        iteration="iter_001",
        promoted_at="2026-05-05T00:00:00Z",
        promoted_by="ci",
        summary="improved accuracy",
        promoted_variant_id="v_winner",
        losing_variant_ids=["v_loser"],
    )
    defaults.update(kwargs)
    return LineageEntry(**defaults)


# ── read_lineage ───────────────────────────────────────────────────────────


def test_read_lineage_empty_file(tmp_path: Path):
    f = tmp_path / "lineage.yaml"
    f.write_text("", encoding="utf-8")
    assert read_lineage(f) == {}


def test_read_lineage_with_versions(tmp_path: Path):
    f = tmp_path / "lineage.yaml"
    f.write_text(yaml.dump({"versions": [{"version": "1.0.0"}]}), encoding="utf-8")
    data = read_lineage(f)
    assert data["versions"][0]["version"] == "1.0.0"


# ── append_lineage_entry ───────────────────────────────────────────────────


def test_append_lineage_entry_creates_versions_key(tmp_path: Path):
    f = tmp_path / "lineage.yaml"
    f.write_text("", encoding="utf-8")
    append_lineage_entry(f, _entry())
    data = read_lineage(f)
    assert len(data["versions"]) == 1
    assert data["versions"][0]["version"] == "1.1.0"


def test_append_lineage_entry_accumulates(tmp_path: Path):
    f = tmp_path / "lineage.yaml"
    f.write_text("", encoding="utf-8")
    append_lineage_entry(f, _entry(version="1.0.0", parent=None))
    append_lineage_entry(f, _entry(version="1.1.0", parent="1.0.0"))
    data = read_lineage(f)
    assert len(data["versions"]) == 2


# ── compute_skill_checksum ─────────────────────────────────────────────────


def test_compute_skill_checksum_deterministic(tmp_path: Path):
    skill = tmp_path / "SKILL.md"
    skill.write_text("# Skill\nDo something.", encoding="utf-8")
    c1 = compute_skill_checksum(skill)
    c2 = compute_skill_checksum(skill)
    assert c1 == c2
    assert c1.startswith("sha256:")


def test_compute_skill_checksum_changes_with_content(tmp_path: Path):
    skill = tmp_path / "SKILL.md"
    skill.write_text("version A", encoding="utf-8")
    c1 = compute_skill_checksum(skill)
    skill.write_text("version B", encoding="utf-8")
    c2 = compute_skill_checksum(skill)
    assert c1 != c2


# ── read_variant_meta ──────────────────────────────────────────────────────


def test_read_variant_meta(tmp_path: Path):
    variant_dir = tmp_path / "v_winner"
    variant_dir.mkdir()
    (variant_dir / "meta.yaml").write_text(
        yaml.dump({"id": "v_winner", "score": 0.95}), encoding="utf-8"
    )
    meta = read_variant_meta(tmp_path, "v_winner")
    assert meta["id"] == "v_winner"
    assert meta["score"] == 0.95


# ── verify_variant_checksum ────────────────────────────────────────────────


def test_verify_variant_checksum_passes(tmp_path: Path):
    variant_dir = tmp_path / "v_ok"
    variant_dir.mkdir()
    skill = variant_dir / "SKILL.md"
    skill.write_text("correct content", encoding="utf-8")
    checksum = compute_skill_checksum(skill)
    (variant_dir / "meta.yaml").write_text(
        yaml.dump({"checksum": checksum}), encoding="utf-8"
    )
    assert verify_variant_checksum(tmp_path, "v_ok") is True


def test_verify_variant_checksum_fails_on_mismatch(tmp_path: Path):
    variant_dir = tmp_path / "v_bad"
    variant_dir.mkdir()
    skill = variant_dir / "SKILL.md"
    skill.write_text("original", encoding="utf-8")
    (variant_dir / "meta.yaml").write_text(
        yaml.dump({"checksum": "sha256:wronghash"}), encoding="utf-8"
    )
    assert verify_variant_checksum(tmp_path, "v_bad") is False


# ── promote_variant ────────────────────────────────────────────────────────


def _setup_variant(iteration_dir: Path, variant_id: str, content: str = "# Skill") -> Path:
    vd = iteration_dir / "variants" / variant_id
    vd.mkdir(parents=True)
    skill = vd / "SKILL.md"
    skill.write_text(content, encoding="utf-8")
    return skill


def test_promote_variant_copies_skill_md(tmp_path: Path):
    iter_dir = tmp_path / "iter_001"
    _setup_variant(iter_dir, "v_winner", "# Winner skill")

    promote_variant(
        iteration_dir=iter_dir,
        variant_id="v_winner",
        losing_variant_ids=["v_loser"],
        new_version="1.1.0",
        actor="ci",
        iteration_id="iter_001",
        summary="better accuracy",
    )

    promoted = iter_dir / "promoted" / "SKILL.md"
    assert promoted.exists()
    assert "Winner skill" in promoted.read_text()


def test_promote_variant_writes_lineage_entry(tmp_path: Path):
    iter_dir = tmp_path / "iter_002"
    _setup_variant(iter_dir, "v_winner")
    lineage_file = tmp_path / "lineage.yaml"
    lineage_file.write_text(yaml.dump({"versions": [{"version": "1.0.0"}]}), encoding="utf-8")

    promote_variant(
        iteration_dir=iter_dir,
        variant_id="v_winner",
        losing_variant_ids=[],
        new_version="1.1.0",
        actor="ci",
        iteration_id="iter_002",
        summary="test promote",
        lineage_file=lineage_file,
    )

    data = read_lineage(lineage_file)
    assert len(data["versions"]) == 2
    last = data["versions"][-1]
    assert last["version"] == "1.1.0"
    assert last["parent"] == "1.0.0"
    assert last["promoted_by"] == "ci"


def test_promote_variant_no_lineage_file(tmp_path: Path):
    iter_dir = tmp_path / "iter_003"
    _setup_variant(iter_dir, "v_winner")

    # No lineage_file argument — should not raise
    promote_variant(
        iteration_dir=iter_dir,
        variant_id="v_winner",
        losing_variant_ids=[],
        new_version="2.0.0",
        actor="human",
        iteration_id="iter_003",
        summary="first version",
    )
    assert (iter_dir / "promoted" / "SKILL.md").exists()


def test_promote_variant_lineage_file_not_exists(tmp_path: Path):
    iter_dir = tmp_path / "iter_004"
    _setup_variant(iter_dir, "v_winner")
    missing_lineage = tmp_path / "does_not_exist.yaml"

    # lineage_file provided but doesn't exist → skip lineage write
    promote_variant(
        iteration_dir=iter_dir,
        variant_id="v_winner",
        losing_variant_ids=[],
        new_version="1.0.0",
        actor="ci",
        iteration_id="iter_004",
        summary="init",
        lineage_file=missing_lineage,
    )
    assert not missing_lineage.exists()
