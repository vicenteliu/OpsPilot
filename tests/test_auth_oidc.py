"""OIDC SSO — PKCE, code exchange, real id_token JWKS verification (ADR-0020).

The connector runs against a mocked IdP (httpx.MockTransport for discovery
and token endpoints) and a real RS256-signed id_token whose signing key is
injected as the JWKS — so signature verification, audience/issuer/nonce
checks all actually execute offline.
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Any
from unittest.mock import patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.auth import router as auth_router
from opspilot.auth import AuthStore
from opspilot.auth.oidc import OidcConfig, OidcConnector, OidcError, make_pkce

_ISSUER = "https://idp.example"
_CLIENT_ID = "opspilot-app"
_REDIRECT = "https://opspilot.example/api/auth/oidc/callback"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _config(**over: str) -> OidcConfig:
    base: dict[str, Any] = {
        "issuer": _ISSUER,
        "client_id": _CLIENT_ID,
        "client_secret": "shh",
        "redirect_url": _REDIRECT,
        "role_claim": "groups",
        "scopes": "openid profile email",
    }
    base.update(over)
    return OidcConfig(**base)


def _sign_id_token(**claims: Any) -> str:
    payload = {
        "iss": _ISSUER,
        "aud": _CLIENT_ID,
        "sub": "u-123",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        **claims,
    }
    return jwt.encode(payload, _KEY, algorithm="RS256", headers={"kid": "test-key"})


def _discovery() -> dict[str, Any]:
    return {
        "issuer": _ISSUER,
        "authorization_endpoint": f"{_ISSUER}/authorize",
        "token_endpoint": f"{_ISSUER}/token",
        "jwks_uri": f"{_ISSUER}/jwks",
    }


class _StubSigningKey:
    key = _KEY.public_key()


def _connector(handler: Any) -> OidcConnector:
    conn = OidcConnector(_config(), http=httpx.Client(transport=httpx.MockTransport(handler)))
    # Inject a JWKS client that returns our real public key — signature
    # verification still runs, only the network fetch is stubbed.
    conn._jwk_client = lambda jwks_uri: type(  # type: ignore[method-assign]
        "K", (), {"get_signing_key_from_jwt": staticmethod(lambda t: _StubSigningKey())}
    )()
    return conn


def _discovery_only_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/openid-configuration"):
        return httpx.Response(200, json=_discovery())
    raise AssertionError(f"unexpected call {request.url}")


class TestPkce:
    def test_challenge_is_s256_of_verifier(self) -> None:
        import base64
        import hashlib

        verifier, challenge = make_pkce()
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        assert challenge == expected


class TestConnector:
    def test_authorization_url_has_pkce_and_state(self) -> None:
        url = _connector(_discovery_only_handler).authorization_url("st8", "chal", "non5")
        assert f"{_ISSUER}/authorize?" in url
        for frag in (
            "code_challenge=chal",
            "code_challenge_method=S256",
            "state=st8",
            "nonce=non5",
            f"client_id={_CLIENT_ID}",
            "response_type=code",
        ):
            assert frag in url, frag

    def test_full_exchange_and_verify(self) -> None:
        id_token = _sign_id_token(nonce="non5", preferred_username="olga", groups=["IT-Ops"])

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/openid-configuration"):
                return httpx.Response(200, json=_discovery())
            if request.url.path.endswith("/token"):
                assert b"code_verifier=" in request.content
                return httpx.Response(200, json={"id_token": id_token})
            raise AssertionError(request.url)

        conn = _connector(handler)
        raw = conn.exchange_code("the-code", "the-verifier")
        identity = conn.verify_id_token(raw, "non5")
        assert identity.username == "olga"
        assert identity.groups == ["IT-Ops"]

    def test_nonce_mismatch_rejected(self) -> None:
        id_token = _sign_id_token(nonce="attacker", preferred_username="olga")
        with pytest.raises(OidcError, match="nonce"):
            _connector(_discovery_only_handler).verify_id_token(id_token, "expected")

    def test_wrong_audience_rejected(self) -> None:
        id_token = jwt.encode(
            {
                "iss": _ISSUER,
                "aud": "someone-else",
                "sub": "x",
                "exp": int(time.time()) + 300,
                "nonce": "n",
            },
            _KEY,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )
        with pytest.raises(OidcError):
            _connector(_discovery_only_handler).verify_id_token(id_token, "n")

    def test_tampered_signature_rejected(self) -> None:
        id_token = _sign_id_token(nonce="n", preferred_username="olga")
        tampered = id_token[:-4] + ("aaaa" if not id_token.endswith("aaaa") else "bbbb")
        with pytest.raises(OidcError):
            _connector(_discovery_only_handler).verify_id_token(tampered, "n")

    def test_from_env_none_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert OidcConfig.from_env() is None


# ── route integration ───────────────────────────────────────────────────────

_OIDC_ENV = {"OPSPILOT_OIDC_ISSUER": _ISSUER, "OPSPILOT_OIDC_CLIENT_ID": _CLIENT_ID}


def _app() -> tuple[TestClient, AuthStore]:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = AuthStore(conn)
    app.state.auth = store
    app.state.service_token = None
    store.upsert_user("root", role="admin", password="pw-admin")
    return TestClient(app, follow_redirects=False), store


class TestOidcRoutes:
    def test_enabled_flag_reflects_config(self) -> None:
        client, _ = _app()
        assert client.get("/api/auth/oidc/enabled").json() == {"enabled": False}
        with patch.dict(os.environ, _OIDC_ENV, clear=False):
            assert client.get("/api/auth/oidc/enabled").json() == {"enabled": True}

    def test_login_redirects_and_stashes_flow(self) -> None:
        client, store = _app()

        class _C:
            def __init__(self, *a: object, **k: object) -> None: ...
            def authorization_url(self, state: str, challenge: str, nonce: str) -> str:
                return f"{_ISSUER}/authorize?state={state}"

        with (
            patch.dict(os.environ, _OIDC_ENV, clear=False),
            patch("opspilot.auth.oidc.OidcConnector", _C),
        ):
            res = client.get("/api/auth/oidc/login")
        assert res.status_code == 302
        assert res.headers["location"].startswith(f"{_ISSUER}/authorize")

    def test_login_404_when_unconfigured(self) -> None:
        client, _ = _app()
        with patch.dict(os.environ, {}, clear=True):
            assert client.get("/api/auth/oidc/login").status_code == 404

    def test_callback_maps_role_and_seats_session(self) -> None:
        client, store = _app()
        store.set_group_role("oidc", "IT-Ops", "operator")

        class _C:
            def __init__(self, *a: object, **k: object) -> None: ...
            def exchange_code(self, code: str, verifier: str) -> str:
                return "raw-id-token"

            def verify_id_token(self, tok: str, nonce: str):
                from opspilot.auth.oidc import OidcIdentity

                return OidcIdentity(username="olga", groups=["IT-Ops"])

        with (
            patch.dict(os.environ, _OIDC_ENV, clear=False),
            patch("opspilot.auth.oidc.OidcConnector", _C),
        ):
            store.save_oidc_flow("st8", "verifier", "non5")
            res = client.get("/api/auth/oidc/callback", params={"code": "c", "state": "st8"})
        assert res.status_code == 302
        assert "opspilot_session" in res.cookies
        row = store.get_user("olga")
        assert row["auth_source"] == "oidc" and row["role"] == "operator"

    def test_callback_unknown_state_400(self) -> None:
        client, _ = _app()
        with patch.dict(os.environ, _OIDC_ENV, clear=False):
            res = client.get(
                "/api/auth/oidc/callback", params={"code": "c", "state": "never-issued"}
            )
        assert res.status_code == 400

    def test_state_is_single_use(self) -> None:
        _, store = _app()
        store.save_oidc_flow("st8", "v", "n")
        assert store.take_oidc_flow("st8") is not None
        assert store.take_oidc_flow("st8") is None  # consumed
