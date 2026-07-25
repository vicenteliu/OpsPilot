"""User + session store for multi-user auth (ADR-0020).

Local password hashing uses stdlib ``hashlib.scrypt`` (no new dependency);
sessions are opaque server-side tokens delivered in an HttpOnly cookie and
revocable at any time. Secrets (LDAP/OIDC) never live here — only user
identity, role, and password hashes for local accounts.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from typing import Any

from ..timeutil import now_rfc3339

ROLES = ("viewer", "operator", "admin")
# Role ordering for "at least this role" checks.
_RANK = {role: i for i, role in enumerate(ROLES)}
AUTH_SOURCES = ("local", "ldap", "oidc")

# Sessions live this long since creation (seconds); a week fits a work rhythm.
SESSION_TTL_S = 7 * 24 * 3600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username     TEXT PRIMARY KEY,
    role         TEXT NOT NULL DEFAULT 'viewer',
    auth_source  TEXT NOT NULL DEFAULT 'local',
    password_hash TEXT NOT NULL DEFAULT '',
    enabled      INTEGER NOT NULL DEFAULT 1,
    role_overridden INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS login_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    username TEXT NOT NULL,
    source   TEXT NOT NULL,
    outcome  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS group_role_map (
    source     TEXT NOT NULL,
    group_name TEXT NOT NULL,
    role       TEXT NOT NULL,
    PRIMARY KEY (source, group_name)
);
"""


def role_at_least(role: str, required: str) -> bool:
    """True when *role* meets or exceeds *required* in the viewer<operator<admin order."""
    return _RANK.get(role, -1) >= _RANK.get(required, 99)


def hash_password(password: str) -> str:
    """scrypt hash as ``scrypt$<salt_hex>$<hash_hex>`` (stdlib, no bcrypt dep)."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, hash_hex = stored.split("$")
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)


def _monotonic_plus(ttl: float) -> float:
    # time.monotonic() is unavailable to workflow scripts but fine in the app;
    # sessions compare against wall-clock epoch so restarts don't extend TTLs.
    import time

    return time.time() + ttl


class AuthStore:
    """Users, sessions, and login audit over the shared SQLite connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        conn.executescript(_SCHEMA)
        # Idempotent column add (#98): pre-existing DBs gain role_overridden.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        if "role_overridden" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN role_overridden INTEGER NOT NULL DEFAULT 0")
        conn.commit()

    # ── users ──────────────────────────────────────────────────────────

    def get_user(self, username: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        return dict(zip((d[0] for d in cur.description), row, strict=True)) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM users ORDER BY username")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def count_users(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def upsert_user(
        self,
        username: str,
        role: str = "viewer",
        auth_source: str = "local",
        password: str | None = None,
    ) -> dict[str, Any]:
        now = now_rfc3339()
        existing = self.get_user(username)
        pw_hash = hash_password(password) if password else (existing or {}).get("password_hash", "")
        if existing:
            self._conn.execute(
                "UPDATE users SET role=?, auth_source=?, password_hash=?, updated_at=? "
                "WHERE username=?",
                (role, auth_source, pw_hash, now, username),
            )
        else:
            self._conn.execute(
                "INSERT INTO users (username, role, auth_source, password_hash, "
                "enabled, created_at, updated_at) VALUES (?,?,?,?,1,?,?)",
                (username, role, auth_source, pw_hash, now, now),
            )
        self._conn.commit()
        user = self.get_user(username)
        assert user is not None
        return user

    def set_role(self, username: str, role: str) -> bool:
        """Explicit admin role change — marks the user as override-pinned so a
        directory group mapping won't reset it on the next LDAP/OIDC login."""
        cur = self._conn.execute(
            "UPDATE users SET role=?, role_overridden=1, updated_at=? WHERE username=?",
            (role, now_rfc3339(), username),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def apply_directory_role(self, username: str, auth_source: str, mapped_role: str) -> str:
        """Upsert a directory user, honoring an admin override (ADR-0020).

        Returns the effective role: an existing override wins over the freshly
        mapped group role; otherwise the mapped role is stored."""
        existing = self.get_user(username)
        if existing and existing["role_overridden"]:
            self.upsert_user(username, role=existing["role"], auth_source=auth_source)
            return str(existing["role"])
        self.upsert_user(username, role=mapped_role, auth_source=auth_source)
        return mapped_role

    def set_enabled(self, username: str, enabled: bool) -> bool:
        cur = self._conn.execute(
            "UPDATE users SET enabled=?, updated_at=? WHERE username=?",
            (1 if enabled else 0, now_rfc3339(), username),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def bootstrap_admin(self, username: str, password: str) -> None:
        """Create the first admin when the user table is empty (break-glass)."""
        if self.count_users() == 0:
            self.upsert_user(username, role="admin", auth_source="local", password=password)

    # ── authentication ─────────────────────────────────────────────────

    def authenticate_local(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.get_user(username)
        ok = (
            user is not None
            and user["enabled"]
            and user["auth_source"] == "local"
            and verify_password(password, user["password_hash"])
        )
        self._log_login(username, "local", "success" if ok else "failure")
        return user if ok else None

    # ── sessions ───────────────────────────────────────────────────────

    def create_session(self, username: str) -> str:
        """Return a fresh opaque session token; only its hash is stored."""
        token = secrets.token_urlsafe(32)
        self._conn.execute(
            "INSERT INTO auth_sessions (token_hash, username, created_at, expires_at) "
            "VALUES (?,?,?,?)",
            (_sha(token), username, now_rfc3339(), _monotonic_plus(SESSION_TTL_S)),
        )
        self._conn.commit()
        return token

    def resolve_session(self, token: str) -> dict[str, Any] | None:
        """Return the live, enabled User for a session token, or None."""
        import time

        cur = self._conn.execute(
            "SELECT username, expires_at FROM auth_sessions WHERE token_hash = ?", (_sha(token),)
        )
        row = cur.fetchone()
        if row is None:
            return None
        if row[1] < time.time():
            self.revoke_session(token)
            return None
        user = self.get_user(row[0])
        return user if user and user["enabled"] else None

    def revoke_session(self, token: str) -> None:
        self._conn.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (_sha(token),))
        self._conn.commit()

    # ── audit ──────────────────────────────────────────────────────────

    def log_login(self, username: str, source: str, outcome: str) -> None:
        """Public login-audit hook for non-local sources (LDAP/OIDC)."""
        self._log_login(username, source, outcome)

    def _log_login(self, username: str, source: str, outcome: str) -> None:
        self._conn.execute(
            "INSERT INTO login_events (ts, username, source, outcome) VALUES (?,?,?,?)",
            (now_rfc3339(), username, source, outcome),
        )
        self._conn.commit()

    # ── group → role mapping (used by the LDAP / OIDC slices) ──────────

    def list_group_roles(self) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT source, group_name, role FROM group_role_map ORDER BY source, group_name"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def set_group_role(self, source: str, group_name: str, role: str) -> None:
        self._conn.execute(
            "INSERT INTO group_role_map (source, group_name, role) VALUES (?,?,?) "
            "ON CONFLICT(source, group_name) DO UPDATE SET role=excluded.role",
            (source, group_name, role),
        )
        self._conn.commit()

    def delete_group_role(self, source: str, group_name: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM group_role_map WHERE source=? AND group_name=?", (source, group_name)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def resolve_group_role(self, source: str, groups: list[str]) -> str | None:
        """Highest role any of *groups* maps to for *source*, or None."""
        best: str | None = None
        mapped = {
            (r["group_name"]): r["role"] for r in self.list_group_roles() if r["source"] == source
        }
        for g in groups:
            role = mapped.get(g)
            if role and (best is None or role_at_least(role, best)):
                best = role
        return best

    def recent_logins(self, limit: int = 50) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT ts, username, source, outcome FROM login_events ORDER BY event_id DESC LIMIT ?",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
