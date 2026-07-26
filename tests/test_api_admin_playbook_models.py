"""Admin playbook model-list editor — edits playbook.yaml in place (ADR-0021)."""

from __future__ import annotations

import sqlite3
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.admin import router as admin_router
from opspilot.api.routes.auth import router as auth_router
from opspilot.auth import AuthStore
from opspilot.orchestrator.types import load_playbook
from opspilot.playbook_models import write_playbook_models
from opspilot.settings_store import SettingsStore

_YAML = """\
# Header comment — must survive.
id: "pb_test"
version: "1.0.0"
system_prompt: "prompt.md"
output_schema: "incident_summary_v1"

# Primary model.
model:
  provider_id: "anthropic"
  kind: "anthropic"
  name: "claude-haiku-4-5-old"
  version: "2025-01"
  params:
    temperature: 0.2
    max_tokens: 4096

# Additional selectable models.
extra_models:
  - provider_id: "openrouter"
    kind: "openai"
    name: "google/gemini-2.0-flash-001"
    version: "2025-01"

# Loop bounds.
limits:
  max_turns: 8
"""


def _playbook_dir(tmp_path: Path) -> Path:
    d = tmp_path / "pb_test"
    d.mkdir()
    (d / "playbook.yaml").write_text(_YAML, encoding="utf-8")
    (d / "prompt.md").write_text("system prompt", encoding="utf-8")
    return d


# ── unit: comment-preserving write ───────────────────────────────────────────


def test_write_preserves_comments_and_updates(tmp_path: Path) -> None:
    d = _playbook_dir(tmp_path)
    write_playbook_models(
        d,
        {
            "provider_id": "anthropic",
            "kind": "anthropic",
            "name": "claude-haiku-4-5-new",
            "version": "2025-06",
            "params": {"temperature": 0.2, "max_tokens": 4096},
        },
        [
            {
                "provider_id": "openrouter",
                "kind": "openai",
                "name": "google/gemini-2.5",
                "version": "2025-06",
            }
        ],
    )
    text = (d / "playbook.yaml").read_text(encoding="utf-8")
    # Every hand-written comment survives.
    for c in (
        "# Header comment",
        "# Primary model.",
        "# Additional selectable models.",
        "# Loop bounds.",
    ):
        assert c in text, c
    pb = load_playbook(d)
    assert (pb.model.name, pb.model.version) == ("claude-haiku-4-5-new", "2025-06")
    assert [m.name for m in pb.extra_models] == ["google/gemini-2.5"]


def test_write_can_empty_the_extras(tmp_path: Path) -> None:
    d = _playbook_dir(tmp_path)
    write_playbook_models(
        d,
        {"provider_id": "anthropic", "kind": "anthropic", "name": "x", "version": "1"},
        [],
    )
    pb = load_playbook(d)
    assert pb.extra_models == []
    assert "# Loop bounds." in (d / "playbook.yaml").read_text(encoding="utf-8")


# ── route ────────────────────────────────────────────────────────────────────


def _client(tmp_path: Path) -> tuple[TestClient, Path, FastAPI]:
    d = _playbook_dir(tmp_path)
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = AuthStore(conn)
    app.state.auth = store
    app.state.service_token = None
    app.state.playbook = load_playbook(d)
    app.state.cfg = types.SimpleNamespace(anthropic_api_key=None)
    app.state.settings = SettingsStore(conn)
    app.state.active_model_ref = ""
    app.state.chat_provider = None
    store.upsert_user("root", role="admin", password="pw")
    store.upsert_user("olga", role="operator", password="pw")
    return TestClient(app), d, app


def _login(c: TestClient, user: str) -> None:
    c.post("/api/auth/login", json={"username": user, "password": "pw"})


def test_get_returns_primary_and_extras(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "root")
    body = c.get("/api/admin/playbook-models").json()
    assert body["playbook_id"] == "pb_test"
    assert body["models"][0]["primary"] is True
    assert body["models"][0]["name"] == "claude-haiku-4-5-old"
    assert [m["name"] for m in body["models"][1:]] == ["google/gemini-2.0-flash-001"]


def test_put_writes_reloads_and_rebuilds(tmp_path: Path) -> None:
    c, d, app = _client(tmp_path)
    _login(c, "root")
    # Local (ollama) primary builds offline — no API key needed in CI.
    payload = {
        "models": [
            {
                "provider_id": "ollama-local",
                "kind": "ollama",
                "name": "gemma4:e4b",
                "version": "2026-06",
                "params": {"temperature": 0.2},
                "primary": True,
            },
        ]
    }
    r = c.put("/api/admin/playbook-models", json=payload)
    assert r.status_code == 200
    assert [m["name"] for m in r.json()["models"]] == ["gemma4:e4b"]
    # File on disk updated + comments intact.
    text = (d / "playbook.yaml").read_text(encoding="utf-8")
    assert "gemma4:e4b" in text and "# Loop bounds." in text
    # Live reload: state.playbook, active_model_ref, chat_provider all refreshed.
    assert app.state.playbook.model.name == "gemma4:e4b"
    assert app.state.active_model_ref == "ollama-local/gemma4:e4b@2026-06"
    assert app.state.chat_provider is not None  # rebuilt (was None)


def test_put_survives_unbuildable_primary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A primary whose provider can't be built (no key) still saves; no 500."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c, d, app = _client(tmp_path)  # cfg.anthropic_api_key is None
    _login(c, "root")
    r = c.put(
        "/api/admin/playbook-models",
        json={
            "models": [
                {
                    "provider_id": "anthropic",
                    "kind": "anthropic",
                    "name": "claude-haiku-4-5-new",
                    "version": "2025-06",
                    "primary": True,
                }
            ]
        },
    )
    assert r.status_code == 200
    assert app.state.playbook.model.name == "claude-haiku-4-5-new"  # reloaded despite provider fail
    assert "claude-haiku-4-5-new" in (d / "playbook.yaml").read_text(encoding="utf-8")


def test_put_clears_stale_default(tmp_path: Path) -> None:
    c, _, app = _client(tmp_path)
    _login(c, "root")
    app.state.settings.set("default_model_id", "openrouter/google/gemini-2.0-flash-001")
    # Drop the extra that the default pointed at.
    c.put(
        "/api/admin/playbook-models",
        json={
            "models": [
                {
                    "provider_id": "anthropic",
                    "kind": "anthropic",
                    "name": "x",
                    "version": "1",
                    "primary": True,
                }
            ]
        },
    )
    assert app.state.settings.get("default_model_id") is None


def test_put_rejects_unknown_provider(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "root")
    r = c.put(
        "/api/admin/playbook-models",
        json={
            "models": [{"provider_id": "bogus", "kind": "anthropic", "name": "x", "version": "1"}]
        },
    )
    assert r.status_code == 422


def test_put_rejects_unbuildable_kind(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "root")
    # 'gemini' is a valid session-Model kind but the provider factory can't build it.
    r = c.put(
        "/api/admin/playbook-models",
        json={"models": [{"provider_id": "gemini", "kind": "gemini", "name": "x", "version": "1"}]},
    )
    assert r.status_code == 422


def test_put_rejects_empty_name(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "root")
    r = c.put(
        "/api/admin/playbook-models",
        json={
            "models": [
                {"provider_id": "anthropic", "kind": "anthropic", "name": "  ", "version": "1"}
            ]
        },
    )
    assert r.status_code == 422


def test_put_rejects_empty_list(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "root")
    assert c.put("/api/admin/playbook-models", json={"models": []}).status_code == 422


def test_operator_forbidden(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "olga")
    assert c.get("/api/admin/playbook-models").status_code == 403


def test_anonymous_401(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    assert c.get("/api/admin/playbook-models").status_code == 401
