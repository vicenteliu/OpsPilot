"""Admin skill editor — create/edit agent_skills/<id>/SKILL.md in place (#122)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.admin import router as admin_router
from opspilot.api.routes.auth import router as auth_router
from opspilot.auth import AuthStore
from opspilot.skills import SkillRegistry

_VALID = {
    "name": "VPN auth failures",
    "trigger": "A user cannot authenticate to the VPN.",
    "body": "# Steps\n\n1. Check the account.\n2. Check MFA.",
    "allowed_tools": ["kb_search"],
    "trust": "internal",
}


def _client(tmp_path: Path) -> tuple[TestClient, Path, FastAPI]:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = AuthStore(conn)
    app.state.auth = store
    app.state.service_token = None
    app.state.skills = SkillRegistry.load(tmp_path)  # empty registry, base_dir=tmp_path
    store.upsert_user("root", role="admin", password="pw")
    store.upsert_user("olga", role="operator", password="pw")
    return TestClient(app), tmp_path, app


def _login(c: TestClient, user: str) -> None:
    c.post("/api/auth/login", json={"username": user, "password": "pw"})


def test_create_writes_file_and_reloads(tmp_path: Path) -> None:
    c, base, app = _client(tmp_path)
    _login(c, "root")
    r = c.put("/api/admin/skills/vpn-auth", json=_VALID)
    assert r.status_code == 200
    assert r.json()["id"] == "vpn-auth"
    # File written where the agent reads it.
    md = base / "vpn-auth" / "SKILL.md"
    assert md.is_file()
    assert "Check MFA" in md.read_text(encoding="utf-8")
    # Reloaded live: the app's registry now serves it.
    assert app.state.skills.get("vpn-auth") is not None


def test_roundtrips_through_get_and_list(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "root")
    c.put("/api/admin/skills/vpn-auth", json=_VALID)
    listed = c.get("/api/admin/skills").json()["skills"]
    assert [s["id"] for s in listed] == ["vpn-auth"]
    detail = c.get("/api/admin/skills/vpn-auth").json()
    assert detail["name"] == _VALID["name"]
    assert detail["allowed_tools"] == ["kb_search"]
    assert "Check the account" in detail["body"]


def test_edit_overwrites(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "root")
    c.put("/api/admin/skills/vpn-auth", json=_VALID)
    c.put("/api/admin/skills/vpn-auth", json={**_VALID, "name": "Renamed", "trust": "community"})
    detail = c.get("/api/admin/skills/vpn-auth").json()
    assert detail["name"] == "Renamed"
    assert detail["trust"] == "community"


def test_get_missing_is_404(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "root")
    assert c.get("/api/admin/skills/ghost").status_code == 404


def test_rejects_bad_id(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "root")
    assert c.put("/api/admin/skills/Bad_ID", json=_VALID).status_code == 422


def test_rejects_missing_fields_and_unknown_tool(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "root")
    assert c.put("/api/admin/skills/x", json={**_VALID, "name": "  "}).status_code == 422
    assert c.put("/api/admin/skills/x", json={**_VALID, "body": ""}).status_code == 422
    assert c.put("/api/admin/skills/x", json={**_VALID, "trust": "bogus"}).status_code == 422
    assert (
        c.put("/api/admin/skills/x", json={**_VALID, "allowed_tools": ["rm_rf"]}).status_code == 422
    )


def test_operator_forbidden(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "olga")
    assert c.get("/api/admin/skills").status_code == 403
    assert c.put("/api/admin/skills/x", json=_VALID).status_code == 403


def test_anonymous_401(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    assert c.get("/api/admin/skills").status_code == 401
