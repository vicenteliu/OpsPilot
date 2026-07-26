"""Admin MCP-server management — remote add/edit; stdio read-only (#121)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.admin import router as admin_router
from opspilot.api.routes.auth import router as auth_router
from opspilot.auth import AuthStore

_REMOTE = {
    "name": "Search",
    "transport": "http",
    "url": "https://example.com/mcp",
    "tools_prefix": "mcp__search__",
    "trust": "community",
    "auth_type": "bearer_env",
    "auth_env": "SEARCH_TOKEN",
}

_STDIO_FILE = (
    "version: '1.0.0'\n"
    "mcps:\n"
    "  - id: local-fs\n"
    "    name: Local FS\n"
    "    transport: stdio\n"
    "    command: /bin/echo\n"
    "    tools_prefix: mcp__fs__\n"
    "    enabled: true\n"
    "    trust: trusted\n"
)


def _client(tmp_path: Path) -> tuple[TestClient, Path, FastAPI]:
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = AuthStore(conn)
    app.state.auth = store
    app.state.service_token = None
    app.state.mcp_config_path = tmp_path / "mcp-config.yaml"
    app.state.mcp_registry = None
    store.upsert_user("root", role="admin", password="pw")
    store.upsert_user("olga", role="operator", password="pw")
    return TestClient(app), app.state.mcp_config_path, app


def _login(c: TestClient, user: str) -> None:
    c.post("/api/auth/login", json={"username": user, "password": "pw"})


def test_add_remote_writes_and_reloads(tmp_path: Path) -> None:
    c, path, app = _client(tmp_path)
    _login(c, "root")
    r = c.put("/api/admin/mcp/servers/search", json=_REMOTE)
    assert r.status_code == 200
    servers = {s["id"]: s for s in r.json()["servers"]}
    assert servers["search"]["url"] == "https://example.com/mcp"
    assert servers["search"]["read_only"] is False
    assert path.is_file()  # config written
    assert app.state.mcp_registry is not None  # reloaded live


def test_stdio_server_is_listed_read_only(tmp_path: Path) -> None:
    c, path, _ = _client(tmp_path)
    path.write_text(_STDIO_FILE, encoding="utf-8")
    _login(c, "root")
    servers = {s["id"]: s for s in c.get("/api/admin/mcp/servers").json()["servers"]}
    assert servers["local-fs"]["read_only"] is True
    assert servers["local-fs"]["transport"] == "stdio"


def test_cannot_edit_or_delete_stdio_via_ui(tmp_path: Path) -> None:
    c, path, _ = _client(tmp_path)
    path.write_text(_STDIO_FILE, encoding="utf-8")
    _login(c, "root")
    assert c.put("/api/admin/mcp/servers/local-fs", json=_REMOTE).status_code == 422
    assert c.delete("/api/admin/mcp/servers/local-fs").status_code == 422


def test_stdio_transport_in_body_is_rejected(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "root")
    # The request model only accepts http/sse — a stdio payload can't create RCE.
    r = c.put("/api/admin/mcp/servers/x", json={**_REMOTE, "transport": "stdio"})
    assert r.status_code == 422


def test_delete_remote_and_missing(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "root")
    c.put("/api/admin/mcp/servers/search", json=_REMOTE)
    assert c.delete("/api/admin/mcp/servers/search").status_code == 204
    assert c.get("/api/admin/mcp/servers").json()["servers"] == []
    assert c.delete("/api/admin/mcp/servers/search").status_code == 404


def test_rejects_bad_id_and_missing_url(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "root")
    assert c.put("/api/admin/mcp/servers/Bad_ID", json=_REMOTE).status_code == 422
    assert c.put("/api/admin/mcp/servers/x", json={**_REMOTE, "url": "  "}).status_code == 422


def test_operator_forbidden_and_anonymous_401(tmp_path: Path) -> None:
    c, _, _ = _client(tmp_path)
    _login(c, "olga")
    assert c.get("/api/admin/mcp/servers").status_code == 403
    assert c.put("/api/admin/mcp/servers/x", json=_REMOTE).status_code == 403
    c2, _, _ = _client(tmp_path)
    assert c2.get("/api/admin/mcp/servers").status_code == 401
