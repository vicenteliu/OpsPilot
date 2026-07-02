"""Bearer-token auth middleware + fail-closed remote-binding guard (ADR-0011).

The middleware is tested standalone on a minimal FastAPI app (the real app
enables it at import time only when a token is configured, which is awkward
to toggle per-test); the binding guard is a pure function.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.middleware import AuthMiddleware
from opspilot.cli import _remote_binding_error

# ── AuthMiddleware ─────────────────────────────────────────────────────────


def _client(token: str = "sekrit-token") -> TestClient:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/thing")
    def thing() -> dict[str, str]:
        return {"ok": "yes"}

    app.add_middleware(AuthMiddleware, token=token)
    return TestClient(app)


class TestAuthMiddleware:
    def test_missing_header_rejected(self) -> None:
        res = _client().get("/api/thing")
        assert res.status_code == 401
        assert res.headers["www-authenticate"] == "Bearer"

    def test_wrong_token_rejected(self) -> None:
        res = _client().get("/api/thing", headers={"Authorization": "Bearer nope"})
        assert res.status_code == 401

    def test_malformed_scheme_rejected(self) -> None:
        res = _client().get("/api/thing", headers={"Authorization": "Basic sekrit-token"})
        assert res.status_code == 401

    def test_correct_token_accepted(self) -> None:
        res = _client().get("/api/thing", headers={"Authorization": "Bearer sekrit-token"})
        assert res.status_code == 200
        assert res.json() == {"ok": "yes"}

    def test_bearer_scheme_case_insensitive(self) -> None:
        res = _client().get("/api/thing", headers={"Authorization": "bearer sekrit-token"})
        assert res.status_code == 200

    def test_health_exempt(self) -> None:
        res = _client().get("/health")
        assert res.status_code == 200

    def test_metrics_not_exempt(self) -> None:
        app = FastAPI()

        @app.get("/metrics")
        def metrics() -> dict[str, str]:
            return {"m": "x"}

        app.add_middleware(AuthMiddleware, token="t")
        assert TestClient(app).get("/metrics").status_code == 401


# ── Fail-closed remote-binding guard ───────────────────────────────────────


class TestRemoteBindingGuard:
    def test_loopback_without_token_ok(self) -> None:
        assert _remote_binding_error("127.0.0.1", None) is None
        assert _remote_binding_error("localhost", None) is None
        assert _remote_binding_error("::1", None) is None

    def test_wildcard_without_token_refused(self) -> None:
        err = _remote_binding_error("0.0.0.0", None)
        assert err is not None
        assert "OPSPILOT_API_TOKEN" in err

    def test_lan_address_without_token_refused(self) -> None:
        assert _remote_binding_error("192.168.1.5", None) is not None

    def test_remote_with_token_ok(self) -> None:
        assert _remote_binding_error("0.0.0.0", "some-token") is None

    def test_loopback_with_token_ok(self) -> None:
        assert _remote_binding_error("127.0.0.1", "some-token") is None
