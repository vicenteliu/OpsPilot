"""Lineage + variant registry — file I/O for lineage.yaml and variant meta.yaml."""

from __future__ import annotations

import hashlib
import shutil
from datetime import UTC
from pathlib import Path

import yaml

from ..timeutil import now_rfc3339
from .types import LineageEntry


def read_lineage(lineage_file: Path) -> dict:
    return yaml.safe_load(lineage_file.read_text(encoding="utf-8")) or {}


def append_lineage_entry(lineage_file: Path, entry: LineageEntry) -> None:
    data = read_lineage(lineage_file)
    versions: list = data.setdefault("versions", [])
    versions.append(entry.model_dump(exclude_none=False))
    lineage_file.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def compute_skill_checksum(skill_md: Path) -> str:
    digest = hashlib.sha256(skill_md.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def read_variant_meta(variants_dir: Path, variant_id: str) -> dict:
    meta_file = variants_dir / variant_id / "meta.yaml"
    return yaml.safe_load(meta_file.read_text(encoding="utf-8")) or {}


def verify_variant_checksum(variants_dir: Path, variant_id: str) -> bool:
    """Return True if meta.yaml checksum matches sha256 of SKILL.md."""
    skill_md = variants_dir / variant_id / "SKILL.md"
    meta = read_variant_meta(variants_dir, variant_id)
    expected = meta.get("checksum", "")
    return expected == compute_skill_checksum(skill_md)


def promote_variant(
    *,
    iteration_dir: Path,
    variant_id: str,
    losing_variant_ids: list[str],
    new_version: str,
    actor: str,
    iteration_id: str,
    summary: str,
    rollback_days: int = 30,
    lineage_file: Path | None = None,
) -> None:
    """Copy winning SKILL.md to promoted/, write lineage entry."""
    src_skill = iteration_dir / "variants" / variant_id / "SKILL.md"
    promoted_dir = iteration_dir / "promoted"
    promoted_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_skill, promoted_dir / "SKILL.md")

    # Compute rollback window (30 days from now)
    from datetime import datetime, timedelta, timezone

    window_until = (datetime.now(tz=UTC) + timedelta(days=rollback_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    if lineage_file is not None and lineage_file.exists():
        existing = read_lineage(lineage_file)
        versions = existing.get("versions", [])
        parent = versions[-1]["version"] if versions else None

        entry = LineageEntry(
            version=new_version,
            parent=parent,
            iteration=iteration_id,
            promoted_at=now_rfc3339(),
            promoted_by=actor,
            summary=summary,
            promoted_variant_id=variant_id,
            losing_variant_ids=losing_variant_ids,
            rollback_window_until=window_until,
        )
        append_lineage_entry(lineage_file, entry)
