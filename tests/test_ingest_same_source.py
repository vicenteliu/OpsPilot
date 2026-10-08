"""Two ingests of the same ``source_path`` at once (#256).

Each statement ingestion sends to the shared connection is atomic (#245), but
the per-file sequence is not: look the document up, delete it if it changed,
write the document, embed, write the chunks, write the vectors, detect
conflicts. ``POST /api/kb/ingest`` runs in the thread pool, so a second run on
the same file can land between any two of those steps.

Each test pauses the first run at one step, rewrites the file, and starts a
second run on it. The second run has a window to finish before the first
resumes. Both runs must then succeed and leave the newer content stored once,
every vector backed by a chunk.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest

from opspilot.kb import ingestion
from opspilot.kb.ingestion import IngestConfig, IngestStats, ingest
from opspilot.kb.lance_store import LanceStore
from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.storage_init import init_sqlite
from opspilot.redaction import Redactor

DIM: Final = 8
EMBED_MODEL: Final = "ollama-local/test-embed@2026-04"
# Long enough for an unserialised second run to finish; a serialised one is
# still waiting when it runs out.
WINDOW_S: Final = 0.5
V1: Final = "# VPN\n\nRestart the client.\n"
V2: Final = "# VPN\n\nReinstall the client, then reboot.\n"


@pytest.fixture
def stores(tmp_path: Path) -> tuple[SqliteStore, LanceStore]:
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)
    return sqlite, lance


class _HeldFirstCall:
    """Wrap ``fn`` so its first call waits until released; later calls pass."""

    def __init__(self, fn: Callable[..., Any]) -> None:
        self._fn = fn
        self._first = True
        self.reached = threading.Event()
        self.release = threading.Event()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self._first:
            self._first = False
            self.reached.set()
            self.release.wait()
        return self._fn(*args, **kwargs)


class _Run(threading.Thread):
    """``ingest([path])`` in its own thread, as a request in the thread pool."""

    def __init__(self, path: Path, stores: tuple[SqliteStore, LanceStore]) -> None:
        super().__init__()
        self._path = path
        self._stores = stores
        self.stats: IngestStats | None = None

    def run(self) -> None:
        sqlite, lance = self._stores
        self.stats = ingest(
            [self._path],
            sqlite=sqlite,
            lance=lance,
            redactor=Redactor.from_yaml(),
            embed_fn=lambda _: [1.0] + [0.0] * (DIM - 1),
            config=IngestConfig(embedding_model=EMBED_MODEL, embedding_dim=DIM),
        )


def _second_run_while_first_is_held(
    held: _HeldFirstCall, path: Path, stores: tuple[SqliteStore, LanceStore]
) -> tuple[IngestStats, IngestStats]:
    path.write_text(V1, encoding="utf-8")
    first = _Run(path, stores)
    first.start()
    assert held.reached.wait(10), "the first run never reached the held step"
    path.write_text(V2, encoding="utf-8")
    second = _Run(path, stores)
    second.start()
    second.join(WINDOW_S)
    held.release.set()
    first.join()
    second.join()
    assert first.stats is not None and second.stats is not None
    return first.stats, second.stats


def _stored(stores: tuple[SqliteStore, LanceStore]) -> tuple[int, str, set[str], set[str]]:
    """Documents stored, their chunks' text, chunk ids, and the chunk ids vectors name."""
    sqlite, lance = stores
    conn = sqlite._conn  # noqa: SLF001 — reading what landed, across both stores
    docs = int(conn.execute("SELECT COUNT(*) FROM kb_documents").fetchone()[0])
    rows = conn.execute("SELECT id, content FROM kb_chunks").fetchall()
    vectors = set(lance._table.to_arrow().column("chunk_id").to_pylist())  # noqa: SLF001
    return docs, " ".join(str(r[1]) for r in rows), {str(r[0]) for r in rows}, vectors


def _failures(stats: IngestStats) -> list[str | None]:
    return [f.error for f in stats.files if f.error]


def test_a_replacement_during_the_vector_write_leaves_no_orphan_vector(
    stores: tuple[SqliteStore, LanceStore], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Held just before its LanceDB write, the first run's vectors used to land
    after the second run had deleted their document, backed by no chunk."""
    lance = stores[1]
    held = _HeldFirstCall(lance.upsert_vectors)
    monkeypatch.setattr(lance, "upsert_vectors", held)

    first, second = _second_run_while_first_is_held(held, tmp_path / "sop.md", stores)

    docs, text, chunks, vectors = _stored(stores)
    assert vectors == chunks, f"vectors with no chunk: {sorted(vectors - chunks)}"
    assert docs == 1 and "Reinstall" in text
    assert _failures(first) == [] and _failures(second) == []


def test_two_runs_that_both_miss_the_lookup_do_not_collide(
    stores: tuple[SqliteStore, LanceStore], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Held after its lookup found nothing, the first run used to write its
    document after the second run had written one for the same path."""
    held = _HeldFirstCall(ingestion.chunk_markdown)
    monkeypatch.setattr(ingestion, "chunk_markdown", held)

    first, second = _second_run_while_first_is_held(held, tmp_path / "sop.md", stores)

    assert _failures(first) == [] and _failures(second) == []
    docs, text, chunks, vectors = _stored(stores)
    assert docs == 1 and "Reinstall" in text
    assert vectors == chunks
