"""Small key-value app-settings store (non-secret config only).

Holds operational config an admin sets from the UI — e.g. the team-default
model — over the shared SQLite connection. Secrets never live here (API
keys and connection credentials stay in the environment, ADR-0020); this
is for choices that are safe to persist and read back.
"""

from __future__ import annotations

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SettingsStore:
    """get/set string settings by key over the shared DB connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        conn.executescript(_SCHEMA)
        conn.commit()

    def get(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else None

    def set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        self._conn.commit()
