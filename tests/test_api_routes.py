"""Tests for /api/sessions and /api/models routes (PR-32 coverage)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.models import router as models_router
from opspilot.api.routes.sessions import router as sessions_router


# ── Helpers ───────────────────────────────────────────────────────────────


def _sessions_app(tmp_path: Path, session_mgr=None) -> FastAPI:
    app = FastAPI()
    app.state.session_mgr = session_mgr or _empty_mgr()
    app.include_router(sessions_router, prefix="/api")
    return app


def _empty_mgr():
    mgr = MagicMock()
    mgr.list.return_value = []
    return mgr


def _models_app(playbook) -> FastAPI:
    app = FastAPI()
    app.state.playbook = playbook
    app.include_router(models_router, prefix="/api")
    return app


def _mock_playbook(extra_models=None):
    from opspilot.session.types import Model

    primary = Model(
        provider_id="anthropic",
        kind="anthropic",
        name="claude-haiku-4-5",
        version="2026-04",
        params={},
    )

    class FakeRetrieval:
        mode = "prefetch"

    pb = SimpleNamespace(
        model=primary,
        extra_models=extra_models or [],
        retrieval=FakeRetrieval(),
    )
    return pb


# ── /api/sessions ─────────────────────────────────────────────────────────


def test_list_sessions_empty():
    with TestClient(_sessions_app(Path("/tmp"))) as client:
        resp = client.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.json()["sessions"] == []


def test_list_sessions_returns_rows(tmp_path: Path):
    from opspilot.session.manager import SessionManager
    from opspilot.session.types import Model, Playbook

    sm = SessionManager(home=tmp_path)
    pb = Playbook(id="pb_test", version="1.0.0")
    model = Model(provider_id="ollama-local", kind="ollama", name="test", version="1", params={})
    sess = sm.create(owner="test", playbook=pb, model=model)

    with TestClient(_sessions_app(tmp_path, session_mgr=sm)) as client:
        resp = client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["sessions"]) >= 1
    assert data["sessions"][0]["session_id"] == sess.id


def test_list_sessions_skips_broken_sessions():
    mgr = MagicMock()
    mgr.list.return_value = ["sess_broken"]
    mgr.load.side_effect = RuntimeError("corrupted")

    with TestClient(_sessions_app(Path("/tmp"), session_mgr=mgr)) as client:
        resp = client.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.json()["sessions"] == []


def test_get_session_not_found():
    mgr = MagicMock()
    mgr.load.side_effect = KeyError("not found")
    app = FastAPI()
    app.state.session_mgr = mgr
    app.include_router(sessions_router, prefix="/api")
    resp = TestClient(app).get("/api/sessions/sess_nonexistent")
    assert resp.status_code == 404


def test_get_session_no_artifact(tmp_path: Path):
    from opspilot.session.manager import SessionManager
    from opspilot.session.types import Model, Playbook

    sm = SessionManager(home=tmp_path)
    pb = Playbook(id="pb_test", version="1.0.0")
    model = Model(provider_id="ollama-local", kind="ollama", name="test", version="1", params={})
    sess = sm.create(owner="test", playbook=pb, model=model)

    app = FastAPI()
    app.state.session_mgr = sm
    app.include_router(sessions_router, prefix="/api")

    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{sess.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["artifact_id"] is None
    assert data["error"] is not None


def test_get_session_with_artifact(tmp_path: Path):
    from opspilot.session.manager import SessionManager
    from opspilot.session.types import Model, Playbook

    sm = SessionManager(home=tmp_path)
    pb = Playbook(id="pb_test", version="1.0.0")
    model = Model(provider_id="ollama-local", kind="ollama", name="test", version="1", params={})
    sess = sm.create(owner="test", playbook=pb, model=model)
    import json as _json
    art_store = sm.artifacts(sess.id)
    meta = art_store.put(
        _json.dumps({"summary": "ok"}),
        kind="application/json",
        source="test",
    )
    art_id = meta.artifact_id
    sm.transition(sess.id, "active")
    sm.transition(sess.id, "archived")

    app = FastAPI()
    app.state.session_mgr = sm
    app.include_router(sessions_router, prefix="/api")

    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{sess.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["artifact_id"] == art_id
    assert data["result"]["summary"] == "ok"


# ── /api/models ───────────────────────────────────────────────────────────


def test_get_models_returns_primary():
    pb = _mock_playbook()
    with TestClient(_models_app(pb)) as client:
        resp = client.get("/api/models")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["models"]) == 1
    assert data["models"][0]["provider_id"] == "anthropic"


def test_get_models_includes_extra():
    from opspilot.session.types import Model

    extra = Model(
        provider_id="openrouter",
        kind="openai",
        name="google/gemini-2.0-flash",
        version="2025-01",
        params={},
    )
    pb = _mock_playbook(extra_models=[extra])
    with TestClient(_models_app(pb)) as client:
        resp = client.get("/api/models")
    data = resp.json()
    assert len(data["models"]) == 2
    ids = [m["provider_id"] for m in data["models"]]
    assert "openrouter" in ids


def test_get_models_ollama_extra_uses_prefetch():
    from opspilot.session.types import Model

    extra = Model(
        provider_id="ollama-local",
        kind="ollama",
        name="gemma4:e4b",
        version="2026-04",
        params={},
    )
    pb = _mock_playbook(extra_models=[extra])
    with TestClient(_models_app(pb)) as client:
        resp = client.get("/api/models")
    data = resp.json()
    ollama_model = next(m for m in data["models"] if m["provider_id"] == "ollama-local")
    assert ollama_model["retrieval_mode"] == "prefetch"


def test_get_models_default_id():
    pb = _mock_playbook()
    with TestClient(_models_app(pb)) as client:
        resp = client.get("/api/models")
    data = resp.json()
    assert data["default_id"] == "anthropic/claude-haiku-4-5"
