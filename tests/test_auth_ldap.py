"""LDAP connector + LDAP login path (ADR-0020).

The connector is exercised against a real ldap3 MOCK_SYNC directory (both
binds run), so the search-then-bind flow and group extraction are tested
offline. The login route is tested with the connector patched.
"""

from __future__ import annotations

import os
import sqlite3
from unittest.mock import patch

import ldap3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.admin import router as admin_router
from opspilot.api.routes.auth import router as auth_router
from opspilot.auth import AuthStore
from opspilot.auth.ldap_connector import LdapConfig, LdapConnector, LdapError, LdapUser

_BASE = "dc=corp,dc=io"
_ADMIN_DN = "cn=svc,dc=corp,dc=io"
_OLGA_DN = "uid=olga,ou=people,dc=corp,dc=io"

# Static fixture directory (works for both OpenLDAP uid and AD-style memberOf).
_ENTRIES = {
    _ADMIN_DN: {"userPassword": "svc-pw", "objectClass": "inetOrgPerson"},
    _OLGA_DN: {
        "userPassword": "olga-pw",
        "objectClass": "inetOrgPerson",
        "memberOf": ["cn=IT-Ops,ou=groups,dc=corp,dc=io", "cn=Staff,ou=groups,dc=corp,dc=io"],
    },
}


def _mock_factory(user: str, password: str) -> ldap3.Connection:
    """A MOCK_SYNC connection freshly populated with the fixture directory."""
    server = ldap3.Server("mock")
    conn = ldap3.Connection(server, user=user, password=password, client_strategy=ldap3.MOCK_SYNC)
    for dn, attrs in _ENTRIES.items():
        conn.strategy.add_entry(dn, attrs)
    return conn


def _config(**over: str) -> LdapConfig:
    base = {
        "url": "ldap://mock",
        "base_dn": _BASE,
        "user_filter": "(uid={username})",
        "bind_dn": _ADMIN_DN,
        "bind_password": "svc-pw",
        "group_attr": "memberOf",
    }
    base.update(over)
    return LdapConfig(**base)  # type: ignore[arg-type]


def _connector(**over: str) -> LdapConnector:
    return LdapConnector(_config(**over), connection_factory=_mock_factory)


class TestConnector:
    def test_authenticate_returns_group_cns(self) -> None:
        user = _connector().authenticate("olga", "olga-pw")
        assert isinstance(user, LdapUser)
        assert user.dn == _OLGA_DN
        assert set(user.groups) == {"IT-Ops", "Staff"}  # DN → CN extraction

    def test_bad_password_raises(self) -> None:
        with pytest.raises(LdapError, match="invalid credentials"):
            _connector().authenticate("olga", "wrong")

    def test_empty_password_rejected(self) -> None:
        with pytest.raises(LdapError, match="empty password"):
            _connector().authenticate("olga", "")

    def test_unknown_user_raises(self) -> None:
        with pytest.raises(LdapError, match="not found"):
            _connector().authenticate("ghost", "x")

    def test_filter_injection_escaped(self) -> None:
        # A wildcard in the username must not match everything.
        with pytest.raises(LdapError, match="not found"):
            _connector().authenticate("*", "x")

    def test_test_connection_ok_and_fail(self) -> None:
        _connector().test_connection()  # service-account bind succeeds
        with pytest.raises(LdapError):
            _connector(bind_password="wrong").test_connection()

    def test_from_env_none_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert LdapConfig.from_env() is None


# ── login route integration (connector patched) ─────────────────────────────


def _app() -> tuple[TestClient, AuthStore]:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = AuthStore(conn)
    app.state.auth = store
    app.state.service_token = None
    store.upsert_user("root", role="admin", password="pw-admin")  # local admin stays usable
    return TestClient(app), store


_LDAP_ENV = {"OPSPILOT_LDAP_URL": "ldap://mock", "OPSPILOT_LDAP_BASE_DN": _BASE}


class TestLdapLogin:
    def _patched_connector(self, groups: list[str]):
        class _C:
            def __init__(self, *a: object, **k: object) -> None: ...
            def authenticate(self, username: str, password: str) -> LdapUser:
                if password != "olga-pw":
                    raise LdapError("invalid credentials")
                return LdapUser(username=username, dn=_OLGA_DN, groups=groups)

        return _C

    def test_group_maps_to_role_and_upserts_user(self) -> None:
        client, store = _app()
        store.set_group_role("ldap", "IT-Ops", "operator")
        with (
            patch.dict(os.environ, _LDAP_ENV, clear=False),
            patch(
                "opspilot.auth.ldap_connector.LdapConnector", self._patched_connector(["IT-Ops"])
            ),
        ):
            res = client.post(
                "/api/auth/login",
                json={"username": "olga", "password": "olga-pw", "source": "ldap"},
            )
        assert res.status_code == 200
        assert res.json() == {"name": "olga", "role": "operator", "is_service": False}
        row = store.get_user("olga")
        assert row["auth_source"] == "ldap" and row["role"] == "operator"

    def test_unmapped_group_defaults_viewer(self) -> None:
        client, _ = _app()
        with (
            patch.dict(os.environ, _LDAP_ENV, clear=False),
            patch(
                "opspilot.auth.ldap_connector.LdapConnector", self._patched_connector(["Nobody"])
            ),
        ):
            res = client.post(
                "/api/auth/login",
                json={"username": "olga", "password": "olga-pw", "source": "ldap"},
            )
        assert res.json()["role"] == "viewer"

    def test_per_user_override_wins_over_group(self) -> None:
        client, store = _app()
        store.set_group_role("ldap", "IT-Ops", "operator")
        # First login lands as operator, admin promotes, next login keeps admin.
        with (
            patch.dict(os.environ, _LDAP_ENV, clear=False),
            patch(
                "opspilot.auth.ldap_connector.LdapConnector", self._patched_connector(["IT-Ops"])
            ),
        ):
            client.post(
                "/api/auth/login",
                json={"username": "olga", "password": "olga-pw", "source": "ldap"},
            )
            store.set_role("olga", "admin")
            res = client.post(
                "/api/auth/login",
                json={"username": "olga", "password": "olga-pw", "source": "ldap"},
            )
        assert res.json()["role"] == "admin"

    def test_bad_ldap_credentials_401(self) -> None:
        client, _ = _app()
        with (
            patch.dict(os.environ, _LDAP_ENV, clear=False),
            patch(
                "opspilot.auth.ldap_connector.LdapConnector", self._patched_connector(["IT-Ops"])
            ),
        ):
            res = client.post(
                "/api/auth/login",
                json={"username": "olga", "password": "wrong", "source": "ldap"},
            )
        assert res.status_code == 401

    def test_ldap_outage_does_not_break_local_login(self) -> None:
        client, _ = _app()

        class _Boom:
            def __init__(self, *a: object, **k: object) -> None: ...
            def authenticate(self, u: str, p: str) -> LdapUser:
                raise LdapError("directory unreachable")

        with (
            patch.dict(os.environ, _LDAP_ENV, clear=False),
            patch("opspilot.auth.ldap_connector.LdapConnector", _Boom),
        ):
            assert (
                client.post(
                    "/api/auth/login",
                    json={"username": "olga", "password": "x", "source": "ldap"},
                ).status_code
                == 401
            )
            # Local admin login is unaffected by the LDAP outage.
            assert (
                client.post(
                    "/api/auth/login", json={"username": "root", "password": "pw-admin"}
                ).status_code
                == 200
            )

    def test_ldap_login_when_unconfigured_400(self) -> None:
        client, _ = _app()
        with patch.dict(os.environ, {}, clear=True):
            res = client.post(
                "/api/auth/login",
                json={"username": "olga", "password": "x", "source": "ldap"},
            )
        assert res.status_code == 400
