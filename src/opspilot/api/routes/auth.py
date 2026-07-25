"""Auth routes — local login, logout, and whoami (ADR-0020)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ...auth import COOKIE_NAME, Identity, current_identity
from ...auth.store import SESSION_TTL_S

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class MeResponse(BaseModel):
    name: str
    role: str
    is_service: bool


@router.post("/auth/login", response_model=MeResponse)
def login(body: LoginRequest, request: Request, response: Response) -> MeResponse:
    store = request.app.state.auth
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
