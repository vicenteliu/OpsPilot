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


# ── playbook model list (edits the active playbook.yaml in place) ────────────

# provider_ids and kinds an admin may save. Kinds are the *protocol* kinds the
# provider factory can actually build (make_provider), not the wider session
# Model literal — this prevents saving a model that no run could construct.
_MODEL_PROVIDER_IDS = set(_PROVIDER_LABELS)  # anthropic/openai/openrouter/gemini/grok/ollama-local
_MODEL_KINDS = {"anthropic", "openai", "ollama"}


class PlaybookModelEntry(BaseModel):
    provider_id: str
    kind: str
    name: str
    version: str
    params: dict[str, Any] = {}
    primary: bool = False  # informational in responses; ignored on write (order decides)


class PlaybookModelsResponse(BaseModel):
    playbook_id: str
    models: list[PlaybookModelEntry]  # [0] is the primary, the rest are extras


class PlaybookModelsUpdate(BaseModel):
    models: list[PlaybookModelEntry]  # [0] is the primary, the rest are extras


def _model_entry(m: Any, *, primary: bool = False) -> PlaybookModelEntry:
    return PlaybookModelEntry(
        provider_id=m.provider_id,
        kind=m.kind,
        name=m.name,
        version=m.version,
        params=dict(m.params),
        primary=primary,
    )


def _validate_model_entry(m: PlaybookModelEntry) -> None:
    if m.provider_id not in _MODEL_PROVIDER_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"provider_id must be one of {', '.join(sorted(_MODEL_PROVIDER_IDS))}",
        )
    if m.kind not in _MODEL_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f"kind must be one of {', '.join(sorted(_MODEL_KINDS))} (the provider protocol)",
        )
    if not m.name.strip() or not m.version.strip():
        raise HTTPException(status_code=422, detail="model name and version are required")


def _current_model_ids(pb: Any) -> set[str]:
    ids = {f"{pb.model.provider_id}/{pb.model.name}"}
    ids |= {f"{m.provider_id}/{m.name}" for m in pb.extra_models}
    return ids


@router.get("/admin/playbook-models", response_model=PlaybookModelsResponse, dependencies=[_admin])
def get_playbook_models(request: Request) -> PlaybookModelsResponse:
    """The active playbook's model list ([0] = primary, rest = selectable extras)."""
    pb = request.app.state.playbook
    models = [_model_entry(pb.model, primary=True)]
    models += [_model_entry(m) for m in pb.extra_models]
    return PlaybookModelsResponse(playbook_id=pb.id, models=models)


@router.put("/admin/playbook-models", response_model=PlaybookModelsResponse, dependencies=[_admin])
def set_playbook_models(body: PlaybookModelsUpdate, request: Request) -> PlaybookModelsResponse:
    """Rewrite the active playbook.yaml's model list, then reload it live.

    The first entry is the primary; the rest are the selectable extras. This
    edits the version-controlled spec file in place (ADR-0021) — comments are
    preserved — and bypasses the regression harness that normally gates model
    upgrades, so the admin owns validating the new models.
    """
    from ...orchestrator.types import load_playbook
    from ...playbook_models import write_playbook_models
    from ...providers.registry import make_provider

    if not body.models:
        raise HTTPException(status_code=422, detail="at least the primary model is required")
    for m in body.models:
        _validate_model_entry(m)

    state = request.app.state
    source_dir = state.playbook.source_dir
    primary = body.models[0].model_dump(exclude={"primary"})
    extras = [m.model_dump(exclude={"primary"}) for m in body.models[1:]]
    write_playbook_models(source_dir, primary, extras)

    # Reload the spec and rebuild the startup-cached primary provider / ref so a
    # run selecting the (possibly renamed) primary uses the new model, not the
    # stale one built at boot.
    pb = load_playbook(source_dir)
    state.playbook = pb
    state.active_model_ref = f"{pb.model.provider_id}/{pb.model.name}@{pb.model.version}"
    state.chat_provider = make_provider(
        pb.model.provider_id, kind=pb.model.kind, api_key=state.cfg.anthropic_api_key
    )

    # Drop a team-default that no longer points at an offered model.
    settings = getattr(state, "settings", None)
    if settings is not None:
        saved = settings.get(_DEFAULT_MODEL_KEY)
        if saved is not None and saved not in _current_model_ids(pb):
            settings.delete(_DEFAULT_MODEL_KEY)

    return get_playbook_models(request)


# ── login audit ─────────────────────────────────────────────────────────────


@router.get("/admin/login-audit", response_model=LoginAuditResponse, dependencies=[_admin])
def login_audit(request: Request, limit: int = 50) -> LoginAuditResponse:
    events = request.app.state.auth.recent_logins(limit)
    return LoginAuditResponse(events=[LoginEvent(**e) for e in events])


# ── system logs (in-memory ring buffer, admin-only) ─────────────────────────


class LogRecord(BaseModel):
    ts: str
    level: str
    logger: str
    msg: str
    request_id: str | None = None


class LogListResponse(BaseModel):
    records: list[LogRecord]
    available: bool  # False if the buffer isn't installed (no logs captured)


@router.get("/admin/logs", response_model=LogListResponse, dependencies=[_admin])
def system_logs(level: str | None = None, limit: int = 200) -> LogListResponse:
    """Recent in-process log records (newest last). Ephemeral, per-worker."""
    from ...log_buffer import get_handler

    handler = get_handler()
    if handler is None:
        return LogListResponse(records=[], available=False)
    limit = max(1, min(limit, 1000))
    rows = handler.records(level=level, limit=limit)
    return LogListResponse(records=[LogRecord(**r) for r in rows], available=True)
