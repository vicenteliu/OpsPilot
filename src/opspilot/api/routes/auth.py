"""Auth routes — local login, logout, and whoami (ADR-0020)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ...auth import COOKIE_NAME, Identity, current_identity
from ...auth.store import SESSION_TTL_S

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str
    source: str = "local"  # "local" or "ldap" (oidc uses its own redirect flow)


class MeResponse(BaseModel):
    name: str
    role: str
    is_service: bool


def _login_ldap(store: Any, username: str, password: str) -> dict[str, Any]:
    """Authenticate against LDAP, map the role, and upsert the local User row.

    A directory outage raises LdapError → 401 for this user, but never
    disturbs local / service-token auth (fail-safe, ADR-0020)."""
    from ...auth.ldap_connector import LdapConfig, LdapConnector, LdapError

    cfg = LdapConfig.from_env()
    if cfg is None:
        raise HTTPException(status_code=400, detail="LDAP is not configured")
    try:
        result = LdapConnector(cfg).authenticate(username, password)
    except LdapError as exc:
        store.log_login(username, "ldap", "failure")
        raise HTTPException(status_code=401, detail="LDAP authentication failed") from exc
    # Group → role (highest match), default viewer; an admin override wins.
    mapped = store.resolve_group_role("ldap", result.groups) or "viewer"
    store.apply_directory_role(username, "ldap", mapped)
    store.log_login(username, "ldap", "success")
    user = store.get_user(username)
    assert user is not None
    return dict(user)


@router.post("/auth/login", response_model=MeResponse)
def login(body: LoginRequest, request: Request, response: Response) -> MeResponse:
    store = request.app.state.auth
    if body.source == "ldap":
        user = _login_ldap(store, body.username, body.password)
    else:
        user = store.authenticate_local(body.username, body.password)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid username or password")
    token = store.create_session(user["username"])
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_TTL_S,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return MeResponse(name=user["username"], role=user["role"], is_service=False)


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        request.app.state.auth.revoke_session(token)
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/auth/me", response_model=MeResponse)
def me(identity: Identity = Depends(current_identity)) -> MeResponse:  # noqa: B008
    return MeResponse(name=identity.name, role=identity.role, is_service=identity.is_service)


# ── OIDC SSO (ADR-0020) ─────────────────────────────────────────────────────


def _oidc_connector() -> Any:
    """Build the OIDC connector from env, or None when unconfigured."""
    from ...auth.oidc import OidcConfig, OidcConnector

    cfg = OidcConfig.from_env()
    return OidcConnector(cfg) if cfg is not None else None


@router.get("/auth/oidc/login")
def oidc_login(request: Request) -> RedirectResponse:
    """Start the auth-code+PKCE flow: stash state/nonce/verifier, redirect to IdP."""
    from ...auth.oidc import OidcError, make_pkce, new_state

    connector = _oidc_connector()
    if connector is None:
        raise HTTPException(status_code=404, detail="OIDC is not configured")
    verifier, challenge = make_pkce()
    state, nonce = new_state(), new_state()
    request.app.state.auth.save_oidc_flow(state, verifier, nonce)
    try:
        url = connector.authorization_url(state, challenge, nonce)
    except OidcError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RedirectResponse(url, status_code=302)


@router.get("/auth/oidc/callback")
def oidc_callback(request: Request, code: str, state: str) -> RedirectResponse:
    """Exchange the code, verify the id_token, map the role, seat a session."""
    from ...auth.oidc import OidcError

    store = request.app.state.auth
    connector = _oidc_connector()
    if connector is None:
        raise HTTPException(status_code=404, detail="OIDC is not configured")
    flow = store.take_oidc_flow(state)
    if flow is None:
        raise HTTPException(status_code=400, detail="unknown or expired OIDC state")
    try:
        id_token = connector.exchange_code(code, flow["code_verifier"])
        identity = connector.verify_id_token(id_token, flow["nonce"])
    except OidcError as exc:
        store.log_login("<oidc>", "oidc", "failure")
        raise HTTPException(status_code=401, detail="OIDC authentication failed") from exc
    mapped = store.resolve_group_role("oidc", identity.groups) or "viewer"
    store.apply_directory_role(identity.username, "oidc", mapped)
    store.log_login(identity.username, "oidc", "success")
    token = store.create_session(identity.username)
    # Land back on the app; the SPA re-reads /api/auth/me.
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_TTL_S,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@router.get("/auth/oidc/enabled")
def oidc_enabled() -> dict[str, bool]:
    """Whether the login page should show the SSO button."""
    return {"enabled": _oidc_connector() is not None}
