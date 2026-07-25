"""Admin module — users, role overrides, group→role mappings, status, audit (ADR-0020).

Admin-only enforcement plus the governance operations. Real AuthStore over
in-memory SQLite; login via the auth router to get an admin cookie.
"""

from __future__ import annotations

import os
import sqlite3
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.admin import router as admin_router
from opspilot.api.routes.auth import router as auth_router
from opspilot.auth import AuthStore


def _client() -> tuple[TestClient, AuthStore]:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = AuthStore(conn)
    app.state.auth = store
    app.state.service_token = None
    store.upsert_user("root", role="admin", password="pw-admin")
    store.upsert_user("olga", role="operator", password="pw-operator")
    return TestClient(app), store


def _as(client: TestClient, user: str, pw: str) -> TestClient:
    assert (
        client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200
    )
    return client


class TestAdminOnly:
    def test_operator_gets_403_everywhere(self) -> None:
        client, _ = _client()
        _as(client, "olga", "pw-operator")
        for path in (
            "/api/admin/users",
            "/api/admin/group-roles",
            "/api/admin/auth-status",
            "/api/admin/login-audit",
        ):
            assert client.get(path).status_code == 403, path

    def test_anonymous_401(self) -> None:
        client, _ = _client()
        assert client.get("/api/admin/users").status_code == 401


class TestUserManagement:
    def test_list_create_and_role_takes_effect(self) -> None:
        client, _ = _client()
        _as(client, "root", "pw-admin")
        assert {u["username"] for u in client.get("/api/admin/users").json()["users"]} == {
            "root",
            "olga",
        }
        created = client.post(
            "/api/admin/users", json={"username": "new", "password": "pw", "role": "viewer"}
        )
        assert created.status_code == 201
        assert created.json()["role"] == "viewer"
        # Promote and confirm the new role is what the store returns.
        up = client.patch("/api/admin/users/new/role", json={"role": "operator"})
        assert up.status_code == 200 and up.json()["role"] == "operator"

    def test_duplicate_user_409_and_bad_role_422(self) -> None:
        client, _ = _client()
        _as(client, "root", "pw-admin")
        assert (
            client.post("/api/admin/users", json={"username": "olga", "password": "x"}).status_code
            == 409
        )
        assert client.patch("/api/admin/users/olga/role", json={"role": "root"}).status_code == 422

    def test_disable_user_blocks_their_login(self) -> None:
        client, _ = _client()
        _as(client, "root", "pw-admin")
        assert (
            client.patch("/api/admin/users/olga/enabled", json={"enabled": False}).status_code
            == 200
        )
        fresh = TestClient(client.app)  # separate cookie jar
        assert (
            fresh.post(
                "/api/auth/login", json={"username": "olga", "password": "pw-operator"}
            ).status_code
            == 401
        )


class TestGroupRoleMappings:
    def test_put_list_delete(self) -> None:
        client, _ = _client()
        _as(client, "root", "pw-admin")
        assert (
            client.put(
                "/api/admin/group-roles",
                json={"source": "ldap", "group_name": "IT-Admins", "role": "admin"},
            ).status_code
            == 200
        )
        client.put(
            "/api/admin/group-roles",
            json={"source": "oidc", "group_name": "ops", "role": "operator"},
        )
        mappings = client.get("/api/admin/group-roles").json()["mappings"]
        assert {(m["source"], m["group_name"], m["role"]) for m in mappings} == {
            ("ldap", "IT-Admins", "admin"),
            ("oidc", "ops", "operator"),
        }
        assert client.delete("/api/admin/group-roles/ldap/IT-Admins").status_code == 204
        assert len(client.get("/api/admin/group-roles").json()["mappings"]) == 1

    def test_bad_source_rejected(self) -> None:
        client, _ = _client()
        _as(client, "root", "pw-admin")
        assert (
            client.put(
                "/api/admin/group-roles",
                json={"source": "local", "group_name": "x", "role": "admin"},
            ).status_code
            == 422
        )


class TestAuthStatusAndAudit:
    def test_status_reflects_env(self) -> None:
        client, _ = _client()
        _as(client, "root", "pw-admin")
        with patch.dict(os.environ, {"OPSPILOT_LDAP_URL": "ldap://x"}, clear=False):
            sources = {
                s["source"]: s["configured"]
                for s in client.get("/api/admin/auth-status").json()["sources"]
            }
        assert sources["local"] is True
        assert sources["ldap"] is True

    def test_test_connection_reports_without_storing(self) -> None:
        client, _ = _client()
        _as(client, "root", "pw-admin")
        res = client.post("/api/admin/auth-status/ldap/test").json()
        assert res["ok"] is False  # not configured in this test env
        assert "OPSPILOT_LDAP_URL" in res["detail"]

    def test_login_audit_records_attempts(self) -> None:
        client, _ = _client()
        _as(client, "root", "pw-admin")
        client_2 = TestClient(client.app)
        client_2.post("/api/auth/login", json={"username": "root", "password": "wrong"})
        events = client.get("/api/admin/login-audit").json()["events"]
        outcomes = [e["outcome"] for e in events]
        assert "success" in outcomes and "failure" in outcomes
