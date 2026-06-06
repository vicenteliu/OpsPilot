"""SQLite bootstrap for the memory subsystem.

Loads ``memory/storage/sqlite-schema.sql`` from the spec directory, opens a
connection to the target ``.db`` file, applies recommended PRAGMAs, and
executes the schema as a single script. The schema itself is idempotent
(``CREATE TABLE IF NOT EXISTS`` everywhere), so calling :func:`init_sqlite`
twice on the same path is a no-op.

Usage::

    conn = init_sqlite(Path("~/.opspilot/kb/sqlite.db").expanduser())
    # ... use conn ...
    conn.close()

The schema file lives alongside the spec (not inside the package) so it can
be inspected and validated by non-Python tools too. We resolve it relative
to the repo root via :data:`SCHEMA_SQL_PATH`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Final

# Repo-root-relative path to the spec schema. The package lives at
# ``src/opspilot/memory/`` so we walk up four parents to reach repo root,
# then descend into ``memory/storage/``.
_THIS_FILE = Path(__file__).resolve()
SCHEMA_SQL_PATH: Final[Path] = _THIS_FILE.parents[3] / "memory" / "storage" / "sqlite-schema.sql"

# Recommended PRAGMAs from the schema header. Applied on every connection
# (some are connection-scoped, e.g. mmap_size; others persist in the file).
_PRAGMAS: Final[tuple[tuple[str, str], ...]] = (
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    ("foreign_keys", "ON"),
    ("temp_store", "MEMORY"),
    ("mmap_size", "268435456"),  # 256 MiB
)


def _read_schema_sql() -> str:
    if not SCHEMA_SQL_PATH.is_file():
        raise FileNotFoundError(
            f"sqlite-schema.sql not found at {SCHEMA_SQL_PATH}; "
            "is the package installed outside the repo?"
        )
    return SCHEMA_SQL_PATH.read_text(encoding="utf-8")


_COLUMN_MIGRATIONS: Final[tuple[tuple[str, str, str], ...]] = (
    # (table, column, definition) — applied when column is absent
    ("kb_documents", "valid_from", "TEXT"),
    ("kb_documents", "source_authority", "TEXT NOT NULL DEFAULT 'internal'"),
    ("kb_chunks", "valid_from", "TEXT"),
    ("kb_chunks", "superseded_by", "TEXT"),
)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return bool(cur.fetchone()[0])


def _col_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"SELECT COUNT(*) FROM pragma_table_info('{table}') WHERE name=?", (column,))
    return bool(cur.fetchone()[0])


def _apply_column_migrations(conn: sqlite3.Connection) -> None:
    """Add new columns to existing tables (idempotent via presence check).

    Safe to call before the schema script on an empty database — the table
    existence check prevents ALTER TABLE on non-existent tables.
    """
    for table, column, definition in _COLUMN_MIGRATIONS:
        if _table_exists(conn, table) and not _col_exists(conn, table, column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_sqlite(db_path: Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database at ``db_path`` and apply schema.

    Creates parent directories as needed. Idempotent — safe to call on a
    pre-existing file.

    Column migrations run BEFORE the schema script so that ``CREATE INDEX``
    statements on new columns (e.g. ``valid_from``) succeed on databases
    created before those columns were added.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # PRAGMAs first so the schema executes under WAL etc.
    cur = conn.cursor()
    for name, value in _PRAGMAS:
        cur.execute(f"PRAGMA {name} = {value}")

    # Migrate columns before running the full schema: on old databases this
    # ensures the new columns exist before the schema tries to create indexes
    # on them.  On a fresh database the table-existence check makes this a
    # no-op, and executescript creates everything from scratch.
    _apply_column_migrations(conn)
    conn.commit()  # make column additions visible to the subsequent executescript
    cur.executescript(_read_schema_sql())
    conn.commit()
    return conn


def open_sqlite(db_path: Path) -> sqlite3.Connection:
    """Open an existing DB without re-running the schema script.

    PRAGMAs are still applied (they are connection-scoped).
    Caller is responsible for ensuring the file already has the schema —
    use :func:`init_sqlite` for the first time.
    """
    if not db_path.is_file():
        raise FileNotFoundError(f"SQLite DB not found at {db_path}")

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    cur = conn.cursor()
    for name, value in _PRAGMAS:
        cur.execute(f"PRAGMA {name} = {value}")
    return conn
