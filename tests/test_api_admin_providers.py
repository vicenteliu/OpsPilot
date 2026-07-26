"""Admin providers status + team default model (ADR-0020, env-only keys).

The providers page reports which keys are configured (from env) and never
stores them; the default-model setting persists a non-secret choice.
"""

from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.admin import router as admin_router
from opspilot.api.routes.auth import router as auth_router
from opspilot.auth import AuthStore
from opspilot.settings_store import SettingsStore


def _playbook() -> SimpleNamespace:
    return SimpleNamespace(
        model=SimpleNamespace(provider_id="anthropic", name="claude-haiku-4-5-20251001"),
        extra_models=[SimpleNamespace(provider_id="ollama-local", name="gemma4:e4b")],
    )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = AuthStore(conn)
    app.state.auth = store
    app.state.settings = SettingsStore(conn)
    app.state.playbook = _playbook()
    app.state.cfg = SimpleNamespace(anthropic_api_key=None)
    app.state.service_token = None
    store.upsert_user("root", role="admin", password="pw")
    store.upsert_user("olga", role="operator", password="pw")
    return TestClient(app)


def _admin(c: TestClient) -> TestClient:
    c.post("/api/auth/login", json={"username": "root", "password": "pw"})
    return c


class TestProviders:
    def test_status_reflects_env_and_never_returns_keys(self) -> None:
        c = _admin(_client())
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-secret"}, clear=False):
            body = c.get("/api/admin/providers").json()["providers"]
        by_id = {p["id"]: p for p in body}
        assert by_id["anthropic"]["configured"] is True
        assert by_id["anthropic"]["env_var"] == "ANTHROPIC_API_KEY"
        assert by_id["ollama-local"]["configured"] is True  # local, no key
        # The secret value never appears anywhere in the response.
        assert "sk-secret" not in c.get("/api/admin/providers").text

    def test_unconfigured_provider_reported_false(self) -> None:
        c = _admin(_client())
        with patch.dict(os.environ, {}, clear=True):
            by_id = {p["id"]: p for p in c.get("/api/admin/providers").json()["providers"]}
        assert by_id["openai"]["configured"] is False

    def test_test_provider_unconfigured_reports_env_var(self) -> None:
        c = _admin(_client())
        with patch.dict(os.environ, {}, clear=True):
            res = c.post("/api/admin/providers/openai/test").json()
        assert res["ok"] is False and "OPENAI_API_KEY" in res["detail"]

    def test_test_provider_runs_health_probe(self) -> None:
        c = _admin(_client())
        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-x"}, clear=False),
            patch(
                "opspilot.providers.registry.make_provider",
                return_value=SimpleNamespace(health_probe=lambda: True),
            ),
        ):
            res = c.post("/api/admin/providers/anthropic/test").json()
        assert res["ok"] is True and res["detail"] == "reachable"

    def test_operator_forbidden(self) -> None:
        c = _client()
        c.post("/api/auth/login", json={"username": "olga", "password": "pw"})
        assert c.get("/api/admin/providers").status_code == 403


class TestDefaultModel:
    def test_set_valid_get_and_clear(self) -> None:
        c = _admin(_client())
        assert c.get("/api/admin/default-model").json() == {"model_id": None}
        res = c.put("/api/admin/default-model", json={"model_id": "ollama-local/gemma4:e4b"})
        assert res.status_code == 200
        assert c.get("/api/admin/default-model").json() == {"model_id": "ollama-local/gemma4:e4b"}
        # Clear.
        assert c.put("/api/admin/default-model", json={"model_id": None}).json() == {
            "model_id": None
        }

    def test_reject_model_not_offered(self) -> None:
        c = _admin(_client())
        assert (
            c.put("/api/admin/default-model", json={"model_id": "openai/gpt-9"}).status_code == 422
        )

    def test_operator_forbidden(self) -> None:
        c = _client()
        c.post("/api/auth/login", json={"username": "olga", "password": "pw"})
        assert c.put("/api/admin/default-model", json={"model_id": "x"}).status_code == 403
