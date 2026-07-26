"""Admin module routes — user & mapping governance (ADR-0020).

Admin-role only. Manages people and group→role mappings, and reports auth
source status — it never stores connection secrets (those are env-only).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ...auth import require_role
from ...auth.store import ROLES

router = APIRouter()

_admin = Depends(require_role("admin"))


class AdminUser(BaseModel):
    username: str
    role: str
    auth_source: str
    enabled: bool


class UserListResponse(BaseModel):
    users: list[AdminUser]


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class RoleUpdate(BaseModel):
    role: str


class EnabledUpdate(BaseModel):
    enabled: bool


class GroupRole(BaseModel):
    source: str
    group_name: str
    role: str


class GroupRoleListResponse(BaseModel):
    mappings: list[GroupRole]


class AuthSourceStatus(BaseModel):
    source: str
    configured: bool


class AuthStatusResponse(BaseModel):
    sources: list[AuthSourceStatus]


class LoginEvent(BaseModel):
    ts: str
    username: str
    source: str
    outcome: str


class LoginAuditResponse(BaseModel):
    events: list[LoginEvent]


def _row_to_user(row: dict[str, Any]) -> AdminUser:
    return AdminUser(
        username=row["username"],
        role=row["role"],
        auth_source=row["auth_source"],
        enabled=bool(row["enabled"]),
    )


def _validate_role(role: str) -> None:
    if role not in ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {', '.join(ROLES)}")


# ── users ──────────────────────────────────────────────────────────────────


@router.get("/admin/users", response_model=UserListResponse, dependencies=[_admin])
def list_users(request: Request) -> UserListResponse:
    return UserListResponse(users=[_row_to_user(u) for u in request.app.state.auth.list_users()])


@router.post("/admin/users", response_model=AdminUser, status_code=201, dependencies=[_admin])
def create_user(body: CreateUserRequest, request: Request) -> AdminUser:
    _validate_role(body.role)
    store = request.app.state.auth
    if store.get_user(body.username) is not None:
        raise HTTPException(status_code=409, detail="user already exists")
    row = store.upsert_user(
        body.username, role=body.role, auth_source="local", password=body.password
    )
    return _row_to_user(row)


@router.patch("/admin/users/{username}/role", response_model=AdminUser, dependencies=[_admin])
def set_role(username: str, body: RoleUpdate, request: Request) -> AdminUser:
    _validate_role(body.role)
    store = request.app.state.auth
    if not store.set_role(username, body.role):
        raise HTTPException(status_code=404, detail="no such user")
    return _row_to_user(store.get_user(username))


@router.patch("/admin/users/{username}/enabled", response_model=AdminUser, dependencies=[_admin])
def set_enabled(username: str, body: EnabledUpdate, request: Request) -> AdminUser:
    store = request.app.state.auth
    if not store.set_enabled(username, body.enabled):
        raise HTTPException(status_code=404, detail="no such user")
    return _row_to_user(store.get_user(username))


# ── group → role mappings ───────────────────────────────────────────────────


@router.get("/admin/group-roles", response_model=GroupRoleListResponse, dependencies=[_admin])
def list_group_roles(request: Request) -> GroupRoleListResponse:
    return GroupRoleListResponse(
        mappings=[GroupRole(**m) for m in request.app.state.auth.list_group_roles()]
    )


@router.put("/admin/group-roles", response_model=GroupRole, dependencies=[_admin])
def set_group_role(body: GroupRole, request: Request) -> GroupRole:
    _validate_role(body.role)
    if body.source not in ("ldap", "oidc"):
        raise HTTPException(status_code=422, detail="source must be ldap or oidc")
    request.app.state.auth.set_group_role(body.source, body.group_name, body.role)
    return body


@router.delete("/admin/group-roles/{source}/{group_name}", status_code=204, dependencies=[_admin])
def delete_group_role(source: str, group_name: str, request: Request) -> Response:
    if not request.app.state.auth.delete_group_role(source, group_name):
        raise HTTPException(status_code=404, detail="no such mapping")
    return Response(status_code=204)


# ── auth source status + connectivity ───────────────────────────────────────


def _ldap_configured() -> bool:
    return bool(os.environ.get("OPSPILOT_LDAP_URL"))


def _oidc_configured() -> bool:
    return bool(os.environ.get("OPSPILOT_OIDC_ISSUER"))


@router.get("/admin/auth-status", response_model=AuthStatusResponse, dependencies=[_admin])
def auth_status() -> AuthStatusResponse:
    return AuthStatusResponse(
        sources=[
            AuthSourceStatus(source="local", configured=True),
            AuthSourceStatus(source="ldap", configured=_ldap_configured()),
            AuthSourceStatus(source="oidc", configured=_oidc_configured()),
        ]
    )


class TestConnectionResult(BaseModel):
    source: str
    ok: bool
    detail: str


@router.post(
    "/admin/auth-status/{source}/test", response_model=TestConnectionResult, dependencies=[_admin]
)
def test_connection(source: str) -> TestConnectionResult:
    """Probe a source's connectivity from env config; store nothing.

    The real bind / discovery probes arrive with the LDAP (#98) and OIDC
    (#99) slices; here the endpoint reports whether the source is
    configured so the admin UI is wired end to end.
    """
    if source == "ldap":
        from ...auth.ldap_connector import LdapConfig, LdapConnector, LdapError

        cfg = LdapConfig.from_env()
        if cfg is None:
            return TestConnectionResult(
                source=source, ok=False, detail="OPSPILOT_LDAP_URL / _BASE_DN not set"
            )
        try:
            LdapConnector(cfg).test_connection()
        except LdapError as exc:
            return TestConnectionResult(source=source, ok=False, detail=str(exc))
        return TestConnectionResult(source=source, ok=True, detail="service-account bind ok")
    if source == "oidc":
        from ...auth.oidc import OidcConfig, OidcConnector, OidcError

        oidc_cfg = OidcConfig.from_env()
        if oidc_cfg is None:
            return TestConnectionResult(
                source=source, ok=False, detail="OPSPILOT_OIDC_ISSUER / _CLIENT_ID not set"
            )
        try:
            disc = OidcConnector(oidc_cfg).discover()
        except OidcError as exc:
            return TestConnectionResult(source=source, ok=False, detail=str(exc))
        return TestConnectionResult(
            source=source, ok=True, detail=f"discovery ok: {disc.get('issuer', oidc_cfg.issuer)}"
        )
    raise HTTPException(status_code=422, detail="source must be ldap or oidc")


# ── LLM providers (env-only keys; status + real health probe) ───────────────

# provider_id → the env var its API key is read from (ADR-0020: env-only).
_PROVIDER_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "grok": "GROK_API_KEY",
}
_PROVIDER_LABELS = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "gemini": "Google Gemini",
    "grok": "xAI Grok",
    "ollama-local": "Local (Ollama)",
}


class ProviderStatus(BaseModel):
    id: str
    label: str
    env_var: str  # where to set the key ("" for Ollama, which needs none)
    configured: bool


class ProviderListResponse(BaseModel):
    providers: list[ProviderStatus]


@router.get("/admin/providers", response_model=ProviderListResponse, dependencies=[_admin])
def list_providers() -> ProviderListResponse:
    """Which LLM providers have a key configured (from env — never stored)."""
    out = [
        ProviderStatus(
            id=pid, label=_PROVIDER_LABELS[pid], env_var=env, configured=bool(os.environ.get(env))
        )
        for pid, env in _PROVIDER_ENV.items()
    ]
    # Ollama is local — no key; report it configured (base URL always set).
    out.append(
        ProviderStatus(
            id="ollama-local", label=_PROVIDER_LABELS["ollama-local"], env_var="", configured=True
        )
    )
    return ProviderListResponse(providers=out)


@router.post(
    "/admin/providers/{provider_id}/test",
    response_model=TestConnectionResult,
    dependencies=[_admin],
)
def test_provider(provider_id: str, request: Request) -> TestConnectionResult:
    """Build the provider from env config and run its health probe."""
    from ...providers.registry import make_provider

    env = _PROVIDER_ENV.get(provider_id)
    if env is not None and not os.environ.get(env):
        return TestConnectionResult(source=provider_id, ok=False, detail=f"{env} not set")
    try:
        provider = make_provider(provider_id, api_key=request.app.state.cfg.anthropic_api_key)
        ok = provider.health_probe()
    except Exception as exc:  # noqa: BLE001 — report, never 500
        return TestConnectionResult(source=provider_id, ok=False, detail=str(exc))
    return TestConnectionResult(
        source=provider_id, ok=ok, detail="reachable" if ok else "health probe failed"
    )


# ── team default model (persisted config, not a secret) ─────────────────────

_DEFAULT_MODEL_KEY = "default_model_id"


class DefaultModel(BaseModel):
    model_id: str | None


def _available_model_ids(request: Request) -> list[str]:
    pb = request.app.state.playbook
    ids = [f"{pb.model.provider_id}/{pb.model.name}"]
    ids += [f"{m.provider_id}/{m.name}" for m in pb.extra_models]
    return ids


@router.get("/admin/default-model", response_model=DefaultModel, dependencies=[_admin])
def get_default_model(request: Request) -> DefaultModel:
    return DefaultModel(model_id=request.app.state.settings.get(_DEFAULT_MODEL_KEY))


@router.put("/admin/default-model", response_model=DefaultModel, dependencies=[_admin])
def set_default_model(body: DefaultModel, request: Request) -> DefaultModel:
    """Set the team-default model; must be one the playbook offers. Null clears it."""
    if body.model_id is None:
        request.app.state.settings.delete(_DEFAULT_MODEL_KEY)
        return DefaultModel(model_id=None)
    if body.model_id not in _available_model_ids(request):
        raise HTTPException(status_code=422, detail="model is not one of the selectable models")
    request.app.state.settings.set(_DEFAULT_MODEL_KEY, body.model_id)
    return DefaultModel(model_id=body.model_id)


# ── login audit ─────────────────────────────────────────────────────────────


@router.get("/admin/login-audit", response_model=LoginAuditResponse, dependencies=[_admin])
def login_audit(request: Request, limit: int = 50) -> LoginAuditResponse:
    events = request.app.state.auth.recent_logins(limit)
    return LoginAuditResponse(events=[LoginEvent(**e) for e in events])
