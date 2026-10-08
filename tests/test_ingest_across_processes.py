"""Ingests of the same ``source_path`` from two processes (#260).

#257 made two ingests of one file take turns, with a lock that lives in the
process. Both production configs run two API workers (``--workers 2``), and
the CLI and TUI open the same KB beside a running server, so two processes
can ingest one file at once. Each holds its own copy of that lock.

These are #256's two interleavings (``test_ingest_same_source.py``) with the
runs in separate processes: the first is held at one step, the file is
rewritten, and a second process ingests it. The second gets a window to
finish before the first resumes. Both must then succeed and leave the newer
content stored once, every vector backed by a chunk.
"""

from __future__ import annotations

import multiprocessing as mp
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Event
from pathlib import Path
from typing import Any, Final

import pytest

from opspilot.kb import ingestion
from opspilot.kb.ingestion import IngestConfig
from opspilot.kb.lance_store import LanceStore
from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.storage_init import init_sqlite
from opspilot.redaction import Redactor

DIM: Final = 8
EMBED_MODEL: Final = "ollama-local/test-embed@2026-04"
# Long enough for an unserialised second run to finish once it has started; a
# serialised one is still waiting when it runs out.
WINDOW_S: Final = 1.0
# Starting a process and importing the KB stack, generously.
START_S: Final = 60.0
V1: Final = "# VPN\n\nRestart the client.\n"
V2: Final = "# VPN\n\nReinstall the client, then reboot.\n"


def _open(kb: Path) -> tuple[SqliteStore, LanceStore]:
    sqlite = SqliteStore(init_sqlite(kb / "kb.db"))
    lance = LanceStore.open_or_create(kb / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)
    return sqlite, lance


def _ingest_in_process(
    kb: str, path: str, hold: str | None, ready: Event, release: Event, out: Queue[Any]
) -> None:
    """One process's ingest. With ``hold``, it waits at that step until released."""
    sqlite, lance = _open(Path(kb))
    if hold == "vectors":
        write = lance.upsert_vectors

        def held_write(records: Any) -> int:
            ready.set()
            release.wait()
            return write(records)

        lance.upsert_vectors = held_write  # type: ignore[method-assign]
    elif hold == "chunking":
        chunk = ingestion.chunk_markdown

        def held_chunk(md: str, config: Any = None) -> Any:
            ready.set()
            release.wait()
            return chunk(md, config=config)

        ingestion.chunk_markdown = held_chunk  # type: ignore[assignment]
    else:
        ready.set()
    stats = ingestion.ingest(
        [Path(path)],
        sqlite=sqlite,
        lance=lance,
        redactor=Redactor.from_yaml(),
        embed_fn=lambda _: [1.0] + [0.0] * (DIM - 1),
        config=IngestConfig(embedding_model=EMBED_MODEL, embedding_dim=DIM),
    )
    out.put((hold, [f.error for f in stats.files if f.error]))


@pytest.mark.parametrize("hold", ["vectors", "chunking"])
def test_a_second_process_waits_for_the_first(hold: str, tmp_path: Path) -> None:
    """``vectors``: held before its LanceDB write, the first process's vectors
    landed after the second had deleted their document, backed by no chunk.
    ``chunking``: held after its lookup found nothing, the first process wrote
    its document after the second had written one for the same path."""
    ctx = mp.get_context("spawn")
    _open(tmp_path)
    doc = tmp_path / "sop.md"
    doc.write_text(V1, encoding="utf-8")
    out: Queue[Any] = ctx.Queue()
    held, second_ready, release = ctx.Event(), ctx.Event(), ctx.Event()

    first = ctx.Process(
        target=_ingest_in_process, args=(str(tmp_path), str(doc), hold, held, release, out)
    )
    first.start()
    assert held.wait(START_S), "the first process never reached the held step"
    doc.write_text(V2, encoding="utf-8")
    second = ctx.Process(
        target=_ingest_in_process,
        args=(str(tmp_path), str(doc), None, second_ready, release, out),
    )
    second.start()
    assert second_ready.wait(START_S), "the second process never started its ingest"
    second.join(WINDOW_S)
    release.set()
    first.join(START_S)
    second.join(START_S)

    errors = dict(out.get(timeout=START_S) for _ in range(2))
    sqlite, lance = _open(tmp_path)
    chunks, vectors = sqlite.chunk_vector_ids(), lance.vector_ids()
    assert vectors == chunks, f"vectors with no chunk: {sorted(vectors - chunks)}"
    assert errors == {hold: [], None: []}
    assert sqlite.kb_stats()["docs_total"] == 1
    assert any("Reinstall" in str(c["content"]) for c in _chunks(sqlite))


def _chunks(sqlite: SqliteStore) -> list[dict[str, Any]]:
    conn = sqlite._conn  # noqa: SLF001 — reading what landed
    return [dict(r) for r in conn.execute("SELECT content FROM kb_chunks")]
