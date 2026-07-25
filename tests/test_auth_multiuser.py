"""Multi-user auth — login, sessions, role enforcement, Service token (ADR-0020).

Real AuthStore + InventoryStore over in-memory SQLite; the inventory routes
are the enforcement surface (viewer reads, operator writes).
"""

from __future__ import annotations

import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.auth import router as auth_router
from opspilot.api.routes.inventory import router as inventory_router
from opspilot.auth import AuthStore
from opspilot.auth.store import hash_password, role_at_least, verify_password
from opspilot.inventory import InventoryStore

_ASSET = {"category": "laptop", "brand_model": "T14", "serial_number": "SN-1"}


def _client(service_token: str | None = None, seed: bool = True) -> tuple[TestClient, AuthStore]:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.include_router(inventory_router, prefix="/api")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    app.state.inventory = InventoryStore(conn)
    store = AuthStore(conn)
    app.state.auth = store
    app.state.service_token = service_token
    if seed:
        store.upsert_user("vera", role="viewer", password="pw-viewer")
        store.upsert_user("olga", role="operator", password="pw-operator")
        store.upsert_user("root", role="admin", password="pw-admin")
    return TestClient(app), store


def _login(client: TestClient, user: str, pw: str) -> None:
    assert (
        client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200
    )


class TestPasswordHashing:
    def test_round_trip_and_reject(self) -> None:
        h = hash_password("s3cret")
        assert verify_password("s3cret", h)
        assert not verify_password("wrong", h)
        assert h != hash_password("s3cret")  # salted

    def test_role_ordering(self) -> None:
        assert role_at_least("admin", "operator")
        assert role_at_least("operator", "operator")
        assert not role_at_least("viewer", "operator")


class TestLoginLifecycle:
    def test_login_sets_cookie_me_and_logout_revokes(self) -> None:
        client, _ = _client()
        assert client.get("/api/auth/me").status_code == 401  # anonymous (users exist)
        res = client.post("/api/auth/login", json={"username": "olga", "password": "pw-operator"})
        assert res.status_code == 200
        assert res.json() == {"name": "olga", "role": "operator", "is_service": False}
        assert client.get("/api/auth/me").json()["name"] == "olga"
        client.post("/api/auth/logout")
        assert client.get("/api/auth/me").status_code == 401

    def test_wrong_password_401(self) -> None:
        client, _ = _client()
        res = client.post("/api/auth/login", json={"username": "root", "password": "nope"})
        assert res.status_code == 401
        assert "opspilot_session" not in res.cookies

    def test_disabled_user_cannot_login(self) -> None:
        client, store = _client()
        store.set_enabled("olga", False)
        assert (
            client.post(
                "/api/auth/login", json={"username": "olga", "password": "pw-operator"}
            ).status_code
            == 401
        )


class TestRoleEnforcement:
    def test_viewer_reads_but_cannot_write(self) -> None:
        client, _ = _client()
        _login(client, "vera", "pw-viewer")
        assert client.get("/api/inventory").status_code == 200
        assert client.post("/api/inventory", json=_ASSET).status_code == 403

    def test_operator_can_write(self) -> None:
        client, _ = _client()
        _login(client, "olga", "pw-operator")
        assert client.post("/api/inventory", json=_ASSET).status_code == 201

    def test_anonymous_blocked_when_users_exist(self) -> None:
        client, _ = _client()
        assert client.get("/api/inventory").status_code == 401


class TestServiceToken:
    def test_bearer_authorizes_as_operator(self) -> None:
        client, _ = _client(service_token="svc-secret")
        headers = {"Authorization": "Bearer svc-secret"}
        me = client.get("/api/auth/me", headers=headers).json()
        assert me["role"] == "operator"
        assert me["is_service"] is True
        assert client.post("/api/inventory", json=_ASSET, headers=headers).status_code == 201

    def test_wrong_bearer_rejected(self) -> None:
        client, _ = _client(service_token="svc-secret")
        assert (
            client.get("/api/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401
        )


class TestAuditIdentity:
    def test_asset_event_actor_carries_the_user(self) -> None:
        client, _ = _client()
        _login(client, "olga", "pw-operator")
        aid = client.post("/api/inventory", json={**_ASSET, "actor": "olga"}).json()["asset_id"]
        events = client.get(f"/api/inventory/{aid}").json()["events"]
        assert events[0]["actor"] == "olga"


class TestBootstrap:
    def test_bootstrap_only_when_empty(self) -> None:
        store = AuthStore(sqlite3.connect(":memory:", check_same_thread=False))
        store.bootstrap_admin("first", "pw")
        assert store.get_user("first")["role"] == "admin"
        store.bootstrap_admin("second", "pw")  # table non-empty → no-op
        assert store.get_user("second") is None

    def test_local_dev_fallback_when_no_users_no_token(self) -> None:
        client, _ = _client(seed=False)
        # No users + no token → operator fallback keeps loopback dev usable.
        assert client.post("/api/inventory", json=_ASSET).status_code == 201
