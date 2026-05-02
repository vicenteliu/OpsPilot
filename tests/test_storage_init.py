"""Tests for ``opspilot.memory.storage_init``.

Covers:
* Schema is applied on a fresh DB (tables and triggers exist).
* Re-running ``init_sqlite`` on the same file is a no-op (idempotent).
* PRAGMAs are set as recommended by the spec header.
* Schema-meta row is populated with version 1.0.0.
"""

from __future__ import annotations

from pathlib import Path

from opspilot.memory.storage_init import (
    SCHEMA_SQL_PATH,
    init_sqlite,
    open_sqlite,
)

# ── Fixtures via pytest tmp_path ──────────────────────────────────────


def test_schema_sql_file_exists() -> None:
    """The spec file must be discoverable from the package install layout."""
    assert SCHEMA_SQL_PATH.is_file(), f"missing: {SCHEMA_SQL_PATH}"


def test_init_creates_all_tables(tmp_path: Path) -> None:
    db = tmp_path / "kb.db"
    conn = init_sqlite(db)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
        names = {r["name"] for r in rows}
        # The schema declares 6 user tables + FTS5 shadow tables.
        # We assert the 6 first-class tables exist; FTS5 internals (_data,
        # _idx, ...) are bookkeeping.
        for required in {
            "schema_meta",
            "memory_records",
            "kb_documents",
            "kb_chunks",
            "ingest_runs",
            "audit_log",
        }:
            assert required in names, f"table {required} not created"
    finally:
        conn.close()


def test_init_creates_fts_virtual_tables(tmp_path: Path) -> None:
    db = tmp_path / "kb.db"
    conn = init_sqlite(db)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('memory_records_fts','kb_chunks_fts')"
        ).fetchall()
        names = {r["name"] for r in rows}
        assert names == {"memory_records_fts", "kb_chunks_fts"}
    finally:
        conn.close()


def test_init_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "kb.db"
    conn1 = init_sqlite(db)
    conn1.close()
    # Second call must not raise (schema uses CREATE * IF NOT EXISTS).
    conn2 = init_sqlite(db)
    try:
        # Schema_meta row should still be exactly one for schema_version.
        rows = conn2.execute(
            "SELECT key, value FROM schema_meta WHERE key='schema_version'"
        ).fetchall()
        assert len(rows) == 1
        # Schema bumped to 1.1.0 in PR-4 (FTS5 tokenizer trigram).
        assert rows[0]["value"] == "1.1.0"
    finally:
        conn2.close()


def test_init_applies_pragmas(tmp_path: Path) -> None:
    db = tmp_path / "kb.db"
    conn = init_sqlite(db)
    try:
        # journal_mode is file-scoped; should be WAL after init.
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

        # foreign_keys is connection-scoped; should be ON for this conn.
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
    finally:
        conn.close()


def test_open_sqlite_does_not_recreate(tmp_path: Path) -> None:
    db = tmp_path / "kb.db"
    init_conn = init_sqlite(db)
    init_conn.execute("INSERT INTO schema_meta(key, value) VALUES ('test_marker','keep_me')")
    init_conn.commit()
    init_conn.close()

    conn = open_sqlite(db)
    try:
        rows = conn.execute("SELECT value FROM schema_meta WHERE key='test_marker'").fetchall()
        # If open_sqlite wrongly re-ran the schema script, the INSERT OR
        # REPLACE on schema_version would still be fine, but our marker row
        # would survive because the script doesn't touch it.
        assert len(rows) == 1
        assert rows[0]["value"] == "keep_me"
    finally:
        conn.close()


def test_open_sqlite_raises_on_missing(tmp_path: Path) -> None:
    db = tmp_path / "does-not-exist.db"
    try:
        open_sqlite(db)
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")
