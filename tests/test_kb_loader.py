"""Tests for ``opspilot.memory.kb_loader`` (PR-8.5).

The kb_loader bypasses the chunker / redactor / markitdown pipeline and
upserts a frozen KB fixture verbatim into SQLite + LanceDB. This guards
the contract that ``make golden`` consumes: spec-example chunk_ids
(``chk_0cf89826`` etc.) must round-trip into the live KB unchanged.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from opspilot.memory.kb_loader import KBLoadStats, load_kb_fixture
from opspilot.memory.lance_store import LanceStore
from opspilot.memory.sqlite_store import SqliteStore
from opspilot.memory.storage_init import init_sqlite

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = REPO_ROOT / "examples" / "scn_ticket_summary_zh" / "kb"
DOC_META = EXAMPLES / "doc-meta.json"
CHUNKS = EXAMPLES / "chunks.jsonl"

DIM = 768
EMBED_MODEL = "ollama-local/test-embed@2026-04"


def _fake_embed(text: str) -> list[float]:
    """Deterministic mock embedder: hashes content into a unit-normalised vector.

    Real callers hand load_kb_fixture an Ollama-backed embed_fn; tests
    prefer a synchronous in-process fake so we don't touch the network.
    """
    base = [float((hash(text) >> (i * 4)) & 0xFF) for i in range(3)]
    n = math.sqrt(sum(x * x for x in base)) or 1.0
    head = [x / n for x in base]
    return head + [0.0] * (DIM - 3)


@pytest.fixture
def stores(tmp_path: Path) -> tuple[SqliteStore, LanceStore]:
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)
    return sqlite, lance


def test_load_kb_fixture_round_trips_chunk_ids(
    stores: tuple[SqliteStore, LanceStore],
) -> None:
    """The fixture's hand-authored chunk_ids must land in SQLite verbatim."""
    sqlite, lance = stores
    stats = load_kb_fixture(
        sqlite=sqlite,
        lance=lance,
        doc_meta_path=DOC_META,
        chunks_jsonl_path=CHUNKS,
        embed_fn=_fake_embed,
    )

    assert isinstance(stats, KBLoadStats)
    assert stats.document_id == "doc_88a277cf"
    # The spec ships 3 chunks; if someone re-authors the fixture this
    # number changes — golden.json + retrieval/response.json must update.
    assert stats.chunk_count == 3
    assert stats.vector_count == 3

    # Every spec-promised chunk_id must be reachable.
    for cid in ("chk_ea5a0261", "chk_0cf89826", "chk_0f674194"):
        row = sqlite.get_chunk(cid)
        assert row is not None, f"chunk {cid} missing from SQLite after load"
        assert row["document_id"] == "doc_88a277cf"


def test_load_kb_fixture_uses_lance_pinned_embedding_model(
    stores: tuple[SqliteStore, LanceStore],
) -> None:
    """Fixture's embedding_model placeholder ('nomic-embed-text@2024-02') must
    be ignored — the live LanceDB table's pinned model wins."""
    sqlite, lance = stores
    load_kb_fixture(
        sqlite=sqlite,
        lance=lance,
        doc_meta_path=DOC_META,
        chunks_jsonl_path=CHUNKS,
        embed_fn=_fake_embed,
    )
    # If kb_loader had passed through the fixture's embedding_model,
    # LanceStore.upsert_vectors would have raised on the first record.
    # Reaching this assertion without exception is itself the test.
    rows = lance._table.to_pandas()  # noqa: SLF001 — inspecting test-side
    assert (rows["embedding_model"] == EMBED_MODEL).all()


def test_load_kb_fixture_raises_when_paths_missing(
    stores: tuple[SqliteStore, LanceStore], tmp_path: Path
) -> None:
    sqlite, lance = stores
    with pytest.raises(FileNotFoundError, match="doc-meta"):
        load_kb_fixture(
            sqlite=sqlite,
            lance=lance,
            doc_meta_path=tmp_path / "nope.json",
            chunks_jsonl_path=CHUNKS,
            embed_fn=_fake_embed,
        )
    with pytest.raises(FileNotFoundError, match="chunks.jsonl"):
        load_kb_fixture(
            sqlite=sqlite,
            lance=lance,
            doc_meta_path=DOC_META,
            chunks_jsonl_path=tmp_path / "nope.jsonl",
            embed_fn=_fake_embed,
        )
