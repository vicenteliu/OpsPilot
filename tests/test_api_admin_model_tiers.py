"""Admin model tiers — designate cheap/thinking models (issue #117)."""

from __future__ import annotations

import sqlite3
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.admin import router as admin_router
from opspilot.api.routes.auth import router as auth_router
from opspilot.auth import AuthStore
from opspilot.settings_store import SettingsStore


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = AuthStore(conn)
    app.state.auth = store
    app.state.service_token = None
    app.state.settings = SettingsStore(conn)
    app.state.playbook = types.SimpleNamespace(
        model=types.SimpleNamespace(provider_id="anthropic", name="haiku"),
        extra_models=[types.SimpleNamespace(provider_id="anthropic", name="opus")],
    )
    store.upsert_user("root", role="admin", password="pw")
    store.upsert_user("olga", role="operator", password="pw")
    return TestClient(app)


def _login(c: TestClient, user: str) -> None:
    c.post("/api/auth/login", json={"username": user, "password": "pw"})


def test_defaults_are_null_then_set_and_reflected() -> None:
    c = _client()
    _login(c, "root")
    assert c.get("/api/admin/model-tiers").json() == {
        "cheap_model_id": None,
        "thinking_model_id": None,
    }
    r = c.put(
        "/api/admin/model-tiers",
        json={"cheap_model_id": "anthropic/haiku", "thinking_model_id": "anthropic/opus"},
    )
    assert r.status_code == 200
    assert r.json() == {"cheap_model_id": "anthropic/haiku", "thinking_model_id": "anthropic/opus"}
    assert c.get("/api/admin/model-tiers").json()["thinking_model_id"] == "anthropic/opus"


def test_null_clears_a_tier() -> None:
    c = _client()
    _login(c, "root")
    c.put(
        "/api/admin/model-tiers",
        json={"cheap_model_id": "anthropic/haiku", "thinking_model_id": "anthropic/opus"},
    )
    c.put(
        "/api/admin/model-tiers",
        json={"cheap_model_id": "anthropic/haiku", "thinking_model_id": None},
    )
    assert c.get("/api/admin/model-tiers").json() == {
        "cheap_model_id": "anthropic/haiku",
        "thinking_model_id": None,
    }


def test_unknown_model_rejected_without_partial_write() -> None:
    c = _client()
    _login(c, "root")
    r = c.put(
        "/api/admin/model-tiers",
        json={"cheap_model_id": "anthropic/haiku", "thinking_model_id": "ghost/model"},
    )
    assert r.status_code == 422
    # The valid cheap tier must NOT have been persisted (validate-before-write).
    assert c.get("/api/admin/model-tiers").json()["cheap_model_id"] is None


def test_operator_forbidden() -> None:
    c = _client()
    _login(c, "olga")
    assert c.get("/api/admin/model-tiers").status_code == 403


def test_anonymous_401() -> None:
    assert _client().get("/api/admin/model-tiers").status_code == 401
