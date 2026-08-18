"""Concurrency semantics of ``SqliteStore``: one connection, many threads.

The store holds a single ``sqlite3.Connection`` opened with
``check_same_thread=False``, and the API keeps one instance on
``app.state.sqlite`` that every route reaches through
``loop.run_in_executor(None, ...)`` — the default, multi-threaded pool. So two
requests writing at the same time drive the same connection at the same time.

``commit()`` is **connection-scoped, not thread-scoped**, so those writes share
one implicit transaction. Before the store serialised them, eight concurrent
``upsert_document`` calls produced three ``InterfaceError`` raises and four rows
— and two of the three "failed" documents were in the database anyway. Writes
were lost, and the caller was told the wrong thing about which ones survived.

See #166.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.storage_init import init_sqlite

WRITERS = 16


def _doc(doc_id: str) -> dict[str, Any]:
    return {
        "id": doc_id,
        "source_path": f"examples/{doc_id}/source.md",
        "title": "VPN troubleshooting SOP",
        "classification": "internal",
        "content_hash": "sha256:" + ("a" * 64),
        "version": "1.0.0",
        "ingested_at": "2026-08-18T10:00:00Z",
        "language": "en",
        "tags": ["vpn"],
        "namespace": "opspilot:public-kb",
        "chunk_strategy": "headings_then_size",
        "chunk_count": 0,
        "embedding_model": "ollama-local/nomic-embed-text@2024-02",
        "embedding_dim": 768,
        "redaction_passed": True,
    }


def _concurrently(work: Any, count: int) -> list[BaseException]:
    """Run ``work(i)`` in ``count`` threads; return whatever they raised."""
    failures: list[BaseException] = []
    guard = threading.Lock()

    def run(i: int) -> None:
        try:
            work(i)
        except BaseException as exc:  # noqa: BLE001 — the test is about what escapes
            with guard:
                failures.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return failures


def test_concurrent_document_writes_all_land(tmp_path: Path) -> None:
    store = SqliteStore(init_sqlite(tmp_path / "kb.sqlite3"))

    failures = _concurrently(lambda i: store.upsert_document(_doc(f"doc_{i:08d}")), WRITERS)

    assert failures == [], f"concurrent writes raised: {[repr(e) for e in failures]}"
    assert store.kb_stats()["docs_total"] == WRITERS


def test_concurrent_correction_writes_all_land(tmp_path: Path) -> None:
    """Corrections touch two tables before committing — a wider window to lose."""
    store = SqliteStore(init_sqlite(tmp_path / "kb.sqlite3"))
    store.upsert_document(_doc("doc_00000000"))
    store.upsert_chunks(
        {
            "id": f"chk_{i:08d}",
            "document_id": "doc_00000000",
            "seq": i,
            "content": f"chunk {i}",
            "content_hash": "sha256:" + ("b" * 64),
            "char_start": 0,
            "char_end": 10,
            "line_start": 1,
            "line_end": 2,
            "heading_path": ["VPN"],
            "anchor": "#vpn",
            "token_count": 4,
            "embedding_model": "ollama-local/nomic-embed-text@2024-02",
            "vector_id": f"vec_{i:08d}",
            "namespace": "opspilot:public-kb",
            "classification": "internal",
            "language": "en",
            "tags": [],
            "redaction_passed": True,
        }
        for i in range(WRITERS)
    )

    failures = _concurrently(
        lambda i: store.add_correction(
            f"chk_{i:08d}", corrected_by="tester", reason="drift", new_content=f"fixed {i}"
        ),
        WRITERS,
    )

    assert failures == [], f"concurrent corrections raised: {[repr(e) for e in failures]}"
    assert store.kb_stats()["corrections_total"] == WRITERS
