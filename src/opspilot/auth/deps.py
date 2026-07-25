"""FastAPI auth dependencies — session/Service-token identity + role gates (ADR-0020).

Resolution order for the caller's identity:
1. A valid session cookie → the authenticated human User.
2. The Service token (ADR-0011 bearer) → a synthetic ``svc:`` identity with
   operator rights, so machine callers (Telegram, JSM, webhook) are unchanged.

When no auth is configured at all (no users bootstrapped and no service
token), the deps fall back to a local-dev ``operator`` so loopback dev stays
friction-free — mirroring ADR-0011's token-optional local posture.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request

from .store import AuthStore, role_at_least

COOKIE_NAME = "opspilot_session"


@dataclass(frozen=True)
class Identity:
    """Who is making the request."""

    name: str  # username, or "svc:<token-prefix>", or "local-dev"
    role: str
    is_service: bool = False


def _service_token(request: Request) -> str | None:
    return getattr(request.app.state, "service_token", None)


def current_identity(request: Request) -> Identity:
    store: AuthStore | None = getattr(request.app.state, "auth", None)
    # Session cookie → human user.
    if store is not None:
        token = request.cookies.get(COOKIE_NAME)
        if token:
            user = store.resolve_session(token)
            if user is not None:
                return Identity(name=user["username"], role=user["role"])

    # Service token → svc: operator (ADR-0011 bearer lives on).
    svc = _service_token(request)
    if svc:
        header = request.headers.get("authorization", "")
        scheme, _, cred = header.partition(" ")
        if scheme.lower() == "bearer" and cred and secrets.compare_digest(cred.strip(), svc):
            return Identity(name=f"svc:{cred[:6]}", role="operator", is_service=True)

    # No users configured and no service token → local-dev convenience.
    if store is not None and store.count_users() == 0 and not svc:
        return Identity(name="local-dev", role="operator")

    raise HTTPException(
        status_code=401, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"}
    )


def require_role(required: str) -> Any:
    """Dependency factory: 403 unless the caller's role >= *required*."""

    def _dep(identity: Identity = Depends(current_identity)) -> Identity:  # noqa: B008
        if not role_at_least(identity.role, required):
            raise HTTPException(
                status_code=403, detail=f"requires {required} role (you are {identity.role})"
            )
        return identity

    return _dep
