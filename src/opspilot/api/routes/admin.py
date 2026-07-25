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
        ok = _oidc_configured()
        return TestConnectionResult(
            source=source,
            ok=ok,
            detail="OIDC configured (discovery probe lands with the OIDC slice)"
            if ok
            else "OPSPILOT_OIDC_ISSUER not set",
        )
    raise HTTPException(status_code=422, detail="source must be ldap or oidc")


# ── login audit ─────────────────────────────────────────────────────────────


@router.get("/admin/login-audit", response_model=LoginAuditResponse, dependencies=[_admin])
def login_audit(request: Request, limit: int = 50) -> LoginAuditResponse:
    events = request.app.state.auth.recent_logins(limit)
    return LoginAuditResponse(events=[LoginEvent(**e) for e in events])
