"""OIDC SSO connector — authorization code + PKCE (ADR-0020).

The only SSO protocol OpsPilot speaks (SAML rejected). Works against any
OIDC IdP (Entra ID, Keycloak, Google, Okta, Authentik): fetch discovery,
build the auth-code+PKCE redirect, exchange the code, and verify the
id_token's RS256 signature against the IdP's JWKS before trusting any
claim. Client secret and config come from the environment only.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient


class OidcError(Exception):
    """Discovery, token exchange, or id_token verification failed."""


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    client_id: str
    client_secret: str
    redirect_url: str
    role_claim: str  # claim holding the group/role values, e.g. "groups" or "roles"
    scopes: str = "openid profile email"

    @classmethod
    def from_env(cls) -> OidcConfig | None:
        issuer = os.environ.get("OPSPILOT_OIDC_ISSUER", "")
        client_id = os.environ.get("OPSPILOT_OIDC_CLIENT_ID", "")
        if not issuer or not client_id:
            return None
        return cls(
            issuer=issuer.rstrip("/"),
            client_id=client_id,
            client_secret=os.environ.get("OPSPILOT_OIDC_CLIENT_SECRET", ""),
            redirect_url=os.environ.get("OPSPILOT_OIDC_REDIRECT_URL", ""),
            role_claim=os.environ.get("OPSPILOT_OIDC_ROLE_CLAIM", "groups"),
            scopes=os.environ.get("OPSPILOT_OIDC_SCOPES", "openid profile email"),
        )


@dataclass(frozen=True)
class OidcIdentity:
    username: str
    groups: list[str]


def make_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for S256 PKCE."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def new_state() -> str:
    return secrets.token_urlsafe(24)


class OidcConnector:
    """Discovery-driven OIDC client; ``http`` is injected in tests."""

    def __init__(self, config: OidcConfig, http: httpx.Client | None = None) -> None:
        self._cfg = config
        self._http = http or httpx.Client(timeout=15.0)
        self._discovery: dict[str, Any] | None = None

    def discover(self) -> dict[str, Any]:
        if self._discovery is None:
            url = f"{self._cfg.issuer}/.well-known/openid-configuration"
            try:
                res = self._http.get(url)
                res.raise_for_status()
                self._discovery = dict(res.json())
            except (httpx.HTTPError, ValueError) as exc:
                raise OidcError(f"OIDC discovery failed: {exc}") from exc
        return self._discovery

    def authorization_url(self, state: str, code_challenge: str, nonce: str) -> str:
        endpoint = self.discover()["authorization_endpoint"]
        params = {
            "response_type": "code",
            "client_id": self._cfg.client_id,
            "redirect_uri": self._cfg.redirect_url,
            "scope": self._cfg.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{endpoint}?{httpx.QueryParams(params)}"

    def exchange_code(self, code: str, code_verifier: str) -> str:
        """Exchange the auth code for the raw id_token (JWT)."""
        endpoint = self.discover()["token_endpoint"]
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._cfg.redirect_url,
            "client_id": self._cfg.client_id,
            "client_secret": self._cfg.client_secret,
            "code_verifier": code_verifier,
        }
        try:
            res = self._http.post(endpoint, data=data)
            res.raise_for_status()
            payload = res.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError(f"token exchange failed: {exc}") from exc
        id_token = payload.get("id_token")
        if not id_token:
            raise OidcError("no id_token in token response")
        return str(id_token)

    def verify_id_token(self, id_token: str, nonce: str) -> OidcIdentity:
        """Verify the RS256 signature against the JWKS and check core claims."""
        jwks_uri = self.discover()["jwks_uri"]
        try:
            signing_key = self._jwk_client(jwks_uri).get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._cfg.client_id,
                issuer=self._cfg.issuer,
            )
        except jwt.InvalidTokenError as exc:
            raise OidcError(f"id_token verification failed: {exc}") from exc
        if claims.get("nonce") != nonce:
            raise OidcError("nonce mismatch")
        username = claims.get("preferred_username") or claims.get("email") or claims.get("sub")
        if not username:
            raise OidcError("id_token has no usable identity claim")
        raw = claims.get(self._cfg.role_claim, [])
        groups = [str(g) for g in raw] if isinstance(raw, list) else [str(raw)] if raw else []
        return OidcIdentity(username=str(username), groups=groups)

    def _jwk_client(self, jwks_uri: str) -> PyJWKClient:
        # Extracted for test injection; PyJWKClient fetches + caches the JWKS.
        return PyJWKClient(jwks_uri)
