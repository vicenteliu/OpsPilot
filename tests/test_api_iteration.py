"""Tests for GET /api/iteration/lineage (PR-28)."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.iteration import router

EXAMPLE_LINEAGE = (
    Path(__file__).parents[1] / "examples" / "itr_ticket_summary_zh_v1_3_0" / "lineage"
)


def _make_app(home: Path) -> FastAPI:
    """Build a minimal FastAPI app with cfg.home pointing at home."""
    app = FastAPI()
    app.state.cfg = SimpleNamespace(home=home)
    app.include_router(router, prefix="/api")
    return app


def _home_with_lineage(tmp_path: Path, src: Path) -> Path:
    """Set up tmp_path/skills/lineage/ from src directory."""
    dest = tmp_path / "skills" / "lineage"
    shutil.copytree(src, dest)
    return tmp_path


def test_lineage_returns_skill(tmp_path: Path):
    home = _home_with_lineage(tmp_path, EXAMPLE_LINEAGE)
    with TestClient(_make_app(home)) as client:
        resp = client.get("/api/iteration/lineage")
    assert resp.status_code == 200
    lineages = resp.json()["lineages"]
    assert len(lineages) >= 1
    assert lineages[0]["skill_name"] == "ticket_summary_zh"
    assert len(lineages[0]["versions"]) >= 4


def test_lineage_version_fields(tmp_path: Path):
    home = _home_with_lineage(tmp_path, EXAMPLE_LINEAGE)
    with TestClient(_make_app(home)) as client:
        resp = client.get("/api/iteration/lineage")
    versions = resp.json()["lineages"][0]["versions"]
    latest = versions[-1]
    assert latest["version"] == "1.4.0"
    assert "summary" in latest
    assert isinstance(latest["rolled_back"], bool)


def test_lineage_empty_dir(tmp_path: Path):
    (tmp_path / "skills" / "lineage").mkdir(parents=True)
    with TestClient(_make_app(tmp_path)) as client:
        resp = client.get("/api/iteration/lineage")
    assert resp.status_code == 200
    assert resp.json()["lineages"] == []


def test_lineage_missing_dir(tmp_path: Path):
    # Don't create skills/lineage at all
    with TestClient(_make_app(tmp_path)) as client:
        resp = client.get("/api/iteration/lineage")
    assert resp.status_code == 200
    assert resp.json()["lineages"] == []
