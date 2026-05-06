"""GET /api/iteration/lineage route (PR-28)."""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import APIRouter, Request

from ..types import ApiLineageListResponse, ApiLineageVersion, ApiSkillLineage

router = APIRouter()


@router.get("/iteration/lineage", response_model=ApiLineageListResponse)
def get_lineage(request: Request) -> ApiLineageListResponse:
    """Return lineage history for all skills found in the configured lineage directory."""
    cfg = request.app.state.cfg
    lineage_dir: Path = cfg.home / "skills" / "lineage"

    lineages = _read_lineage_dir(lineage_dir)
    return ApiLineageListResponse(lineages=lineages)


def _read_lineage_dir(lineage_dir: Path) -> list[ApiSkillLineage]:
    if not lineage_dir.exists():
        return []

    results = []
    for yaml_file in sorted(lineage_dir.glob("*.yaml")):
        skill_name = yaml_file.stem
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            continue

        versions = []
        for v in data.get("versions", []):
            versions.append(
                ApiLineageVersion(
                    version=v.get("version", ""),
                    parent=v.get("parent"),
                    iteration=v.get("iteration"),
                    promoted_at=v.get("promoted_at", ""),
                    promoted_by=v.get("promoted_by", ""),
                    summary=v.get("summary", ""),
                    promoted_variant_id=v.get("promoted_variant_id"),
                    losing_variant_ids=v.get("losing_variant_ids", []),
                    rollback_window_until=v.get("rollback_window_until"),
                    rolled_back=v.get("rolled_back", False),
                )
            )
        results.append(ApiSkillLineage(skill_name=skill_name, versions=versions))
    return results
