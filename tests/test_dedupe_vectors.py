"""Collapsing LanceDB rows that share a ``vector_id``.

Before #261, an upsert through a LanceDB handle pinned to an older version
inserted a second row instead of updating the first: two API workers left
duplicates whenever one re-wrote a vector the other had written. Every row is
an ANN hit, and retrieval adds a vector score per hit, so a duplicated chunk's
vector score counts twice and it outranks chunks that match better.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from typer.testing import CliRunner

from opspilot.cli import _open_kb_stores, app
from opspilot.config import load_config
from opspilot.embedding import EMBED_DIM
from opspilot.kb.ingestion import IngestConfig, dedupe_vectors, ingest
from opspilot.kb.lance_store import LanceStore, VectorRecord
from opspilot.kb.retrieval import kb_search
from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.storage_init import init_sqlite
from opspilot.redaction import Redactor

DIM: Final = 8
EMBED_MODEL: Final = "ollama-local/test-embed@2026-04"
# The query matches no chunk's text, so only the vector path ranks; it points
# at "alpha", with "beta" a close second.
QUERY: Final = "qqqq"


def _embed(text: str) -> list[float]:
    if "beta" in text:
        return [0.9, 0.436] + [0.0] * (DIM - 2)
    return [1.0] + [0.0] * (DIM - 1)


@pytest.fixture
def stores(tmp_path: Path) -> tuple[SqliteStore, LanceStore]:
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)
    for name in ("alpha", "beta"):
        doc = tmp_path / f"{name}.md"
        doc.write_text(f"# {name}\n\nThe {name} runbook.\n", encoding="utf-8")
        ingest(
            [doc],
            sqlite=sqlite,
            lance=lance,
            redactor=Redactor.from_yaml(),
            embed_fn=_embed,
            config=IngestConfig(embedding_model=EMBED_MODEL, embedding_dim=DIM),
        )
    return sqlite, lance


def _chunk(sqlite: SqliteStore, name: str) -> dict[str, object]:
    conn = sqlite._conn  # noqa: SLF001
    row = conn.execute("SELECT * FROM kb_chunks WHERE content LIKE ?", (f"%{name} runbook%",))
    return dict(row.fetchone())


def _duplicate(lance: LanceStore, chunk: dict[str, object], *, chunk_id: str | None = None) -> None:
    """Add a second row for ``chunk``'s vector_id, as a stale upsert did."""
    record = VectorRecord(
        vector_id=str(chunk["vector_id"]),
        embedding=_embed(str(chunk["content"])),
        document_id=str(chunk["document_id"]),
        chunk_id=chunk_id or str(chunk["id"]),
        namespace=str(chunk["namespace"]),
        classification=str(chunk["classification"]),
        language="en",
        tags=[],
        embedding_model=EMBED_MODEL,
    )
    lance._table.add([record.to_arrow_record()])  # noqa: SLF001 — bypassing upsert on purpose


def _rows(lance: LanceStore) -> list[tuple[str, str]]:
    lance._refresh()  # noqa: SLF001
    table = lance._table.to_arrow()  # noqa: SLF001
    ids = table.column("vector_id").to_pylist()
    return sorted(zip(ids, table.column("chunk_id").to_pylist(), strict=True))


def _first_hit(stores: tuple[SqliteStore, LanceStore]) -> str:
    sqlite, lance = stores
    return kb_search(QUERY, sqlite=sqlite, lance=lance, embed_fn=_embed, top_k=2)[0].chunk_id


def test_a_duplicated_vector_outranks_a_better_match_until_deduped(
    stores: tuple[SqliteStore, LanceStore],
) -> None:
    sqlite, lance = stores
    alpha, beta = _chunk(sqlite, "alpha"), _chunk(sqlite, "beta")
    assert _first_hit(stores) == alpha["id"]

    _duplicate(lance, beta)
    assert _first_hit(stores) == beta["id"], "two ANN hits: its vector score counts twice"

    assert dedupe_vectors(sqlite, lance) == [beta["vector_id"]]
    assert len(_rows(lance)) == 2
    assert _first_hit(stores) == alpha["id"]


def test_the_row_kept_is_the_one_naming_the_chunk(
    stores: tuple[SqliteStore, LanceStore],
) -> None:
    """Kept even though the other copy is newer: it names a chunk that does not exist."""
    sqlite, lance = stores
    beta = _chunk(sqlite, "beta")
    _duplicate(lance, beta, chunk_id="chk_5ta1e000")

    dedupe_vectors(sqlite, lance)

    assert (beta["vector_id"], beta["id"]) in _rows(lance)
    assert (beta["vector_id"], "chk_5ta1e000") not in _rows(lance)


def test_a_dry_run_names_the_duplicates_and_deletes_nothing(
    stores: tuple[SqliteStore, LanceStore],
) -> None:
    sqlite, lance = stores
    beta = _chunk(sqlite, "beta")
    _duplicate(lance, beta)
    before = _rows(lance)

    assert dedupe_vectors(sqlite, lance, dry_run=True) == [beta["vector_id"]]
    assert _rows(lance) == before


def test_the_sweep_command_collapses_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPSPILOT_HOME", str(tmp_path / "home"))
    cfg = load_config()
    _, lance = _open_kb_stores(
        home=cfg.home, embedding_dim=EMBED_DIM, embedding_model=cfg.embed_model
    )
    # A vector with no chunk, held twice: the sweep removes both rows as an
    # orphan, and nothing is left to collapse.
    record = VectorRecord(
        vector_id="vec_chk_d0ub1e00",
        embedding=[1.0] + [0.0] * (EMBED_DIM - 1),
        document_id="doc_d0ub1e00",
        chunk_id="chk_d0ub1e00",
        namespace="opspilot:public-kb",
        classification="internal",
        language="en",
        tags=[],
        embedding_model=cfg.embed_model,
    )
    lance._table.add([record.to_arrow_record(), record.to_arrow_record()])  # noqa: SLF001
    runner = CliRunner()

    dry = runner.invoke(app, ["kb", "sweep-vectors", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "1 duplicate vector(s)" in dry.output
    assert lance.count() == 2

    swept = runner.invoke(app, ["kb", "sweep-vectors", "--yes"])
    assert swept.exit_code == 0, swept.output
    assert lance.count() == 0

    again = runner.invoke(app, ["kb", "sweep-vectors"])
    assert "no duplicate vectors" in again.output
