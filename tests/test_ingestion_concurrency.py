"""Ingestion on a connection other stores share (#245).

In the API one ``sqlite3.Connection`` carries the KB store and seven others
(``api/app.py``), and ``POST /api/kb/ingest`` runs ``ingest()`` in the default
thread pool while other routes reach the same connection. #166 put every store
method behind the connection's lock (``dblock.lock_for``) because a statement
sequence is not atomic on that connection, and ``commit()`` is connection-scoped:
a commit from one thread ends whatever transaction another thread has open.

``ingestion.py`` reaches past the store to its connection in three helpers. Each
test holds the lock with a write executed but not committed — what any store
method looks like halfway through — runs one helper in another thread, then
rolls the write back. A helper that does not wait for the lock either commits
that write or reads it.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

from opspilot.dblock import lock_for
from opspilot.kb.ingestion import (
    IngestConfig,
    _delete_doc_with_vectors,
    _find_doc_by_source_path,
    ingest,
)
from opspilot.kb.lance_store import LanceStore
from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.storage_init import init_sqlite
from opspilot.redaction import Redactor

DIM: Final = 8
EMBED_MODEL: Final = "ollama-local/test-embed@2026-04"
# Long enough for a helper that does not wait to finish; one that waits is still
# blocked when it runs out.
WINDOW_S: Final = 0.5
MARKER_SQL: Final = "INSERT INTO schema_meta(key, value) VALUES ('held_by_another_store', 'x')"


def _embed(text: str) -> list[float]:
    return [1.0] + [0.0] * (DIM - 1)


@pytest.fixture
def stores(tmp_path: Path) -> tuple[SqliteStore, LanceStore]:
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)
    return sqlite, lance


def _conn(sqlite: SqliteStore) -> sqlite3.Connection:
    return sqlite._conn  # noqa: SLF001 — the tests play the other store on it


def _ingest(paths: list[Path], stores: tuple[SqliteStore, LanceStore]) -> None:
    sqlite, lance = stores
    ingest(
        paths,
        sqlite=sqlite,
        lance=lance,
        redactor=Redactor.from_yaml(),
        embed_fn=_embed,
        config=IngestConfig(embedding_model=EMBED_MODEL, embedding_dim=DIM),
    )


def _ingested(tmp_path: Path, stores: tuple[SqliteStore, LanceStore]) -> Path:
    doc = tmp_path / "sop.md"
    doc.write_text("# VPN\n\nRestart the client.\n", encoding="utf-8")
    _ingest([doc], stores)
    return doc


def _while_another_store_writes[T](conn: sqlite3.Connection, sql: str, work: Callable[[], T]) -> T:
    """Run ``work`` in another thread while this one holds the lock mid-write.

    ``sql`` is executed and left uncommitted, then rolled back once ``work`` has
    had its window. Returns what ``work`` returned.
    """
    results: list[T] = []
    failures: list[BaseException] = []

    def run() -> None:
        try:
            results.append(work())
        except BaseException as exc:  # noqa: BLE001 — reported below
            failures.append(exc)

    worker = threading.Thread(target=run)
    with lock_for(conn):
        conn.execute(sql)
        worker.start()
        worker.join(WINDOW_S)
        conn.rollback()
    worker.join()
    assert failures == [], f"the helper raised: {[repr(e) for e in failures]}"
    return results[0]


def _marker_survived(conn: sqlite3.Connection) -> bool:
    sql = "SELECT 1 FROM schema_meta WHERE key = 'held_by_another_store'"
    return conn.execute(sql).fetchone() is not None


def test_recording_the_run_waits_for_the_lock(stores: tuple[SqliteStore, LanceStore]) -> None:
    """Every ingest ends by inserting its ``ingest_runs`` row and committing."""
    conn = _conn(stores[0])

    _while_another_store_writes(conn, MARKER_SQL, lambda: _ingest([], stores))

    assert not _marker_survived(conn), "ingest committed another store's transaction"
    assert conn.execute("SELECT COUNT(*) FROM ingest_runs").fetchone()[0] == 1


def test_deleting_a_changed_document_waits_for_the_lock(
    stores: tuple[SqliteStore, LanceStore], tmp_path: Path
) -> None:
    """A changed file's old document is deleted and committed before re-chunking."""
    sqlite, lance = stores
    found = _find_doc_by_source_path(sqlite, str(_ingested(tmp_path, stores)))
    assert found is not None
    conn = _conn(sqlite)

    _while_another_store_writes(
        conn, MARKER_SQL, lambda: _delete_doc_with_vectors(sqlite, lance, found[0])
    )

    assert not _marker_survived(conn), "ingest committed another store's transaction"
    assert sqlite.kb_stats()["docs_total"] == 0
    assert lance.count() == 0


def test_looking_up_a_document_waits_for_the_lock(
    stores: tuple[SqliteStore, LanceStore], tmp_path: Path
) -> None:
    """A lookup that does not wait reads another store's uncommitted delete."""
    sqlite = stores[0]
    source_path = str(_ingested(tmp_path, stores))
    delete = f"DELETE FROM kb_documents WHERE source_path = '{source_path}'"  # noqa: S608

    found = _while_another_store_writes(
        _conn(sqlite), delete, lambda: _find_doc_by_source_path(sqlite, source_path)
    )

    assert found is not None, "the lookup read a delete that was rolled back"
