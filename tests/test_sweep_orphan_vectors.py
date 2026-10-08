"""Sweeping LanceDB vectors that no chunk backs.

A vector is reached through its chunk: every delete looks vector ids up in
``kb_chunks``, and retrieval drops an ANN hit whose chunk is missing. So once a
vector's chunk is gone, nothing that deletes will find it again. #256's race
left such vectors, and so does anything that removes chunks without their
vectors. Answers stay correct, but each one takes an ANN candidate slot, and
they accumulate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from typer.testing import CliRunner

from opspilot.cli import _open_kb_stores, app
from opspilot.config import load_config
from opspilot.embedding import EMBED_DIM
from opspilot.kb.ingestion import IngestConfig, ingest, sweep_orphan_vectors
from opspilot.kb.lance_store import LanceStore, VectorRecord
from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.storage_init import init_sqlite
from opspilot.redaction import Redactor

DIM: Final = 8
EMBED_MODEL: Final = "ollama-local/test-embed@2026-04"
ORPHAN: Final = "vec_chk_0rphan00"


def _orphan(*, dim: int, model: str) -> VectorRecord:
    """A vector whose chunk is gone, as #256's race left them."""
    return VectorRecord(
        vector_id=ORPHAN,
        embedding=[1.0] + [0.0] * (dim - 1),
        document_id="doc_0rphan00",
        chunk_id="chk_0rphan00",
        namespace="opspilot:public-kb",
        classification="internal",
        language="en",
        tags=[],
        embedding_model=model,
    )


@pytest.fixture
def stores(tmp_path: Path) -> tuple[SqliteStore, LanceStore]:
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)
    for name, text in (("vpn", "Restart the client."), ("dns", "Flush the resolver cache.")):
        doc = tmp_path / f"{name}.md"
        doc.write_text(f"# {name}\n\n{text}\n", encoding="utf-8")
        ingest(
            [doc],
            sqlite=sqlite,
            lance=lance,
            redactor=Redactor.from_yaml(),
            embed_fn=lambda _: [1.0] + [0.0] * (DIM - 1),
            config=IngestConfig(embedding_model=EMBED_MODEL, embedding_dim=DIM),
        )
    lance.upsert_vectors([_orphan(dim=DIM, model=EMBED_MODEL)])
    return sqlite, lance


def _vector_ids(lance: LanceStore) -> set[str]:
    return set(lance._table.to_arrow().column("vector_id").to_pylist())  # noqa: SLF001


def _doc(sqlite: SqliteStore, source_path: Path) -> tuple[str, set[str]]:
    """The document ingested from ``source_path``, and its chunks' vector ids."""
    row = sqlite._conn.execute(  # noqa: SLF001
        "SELECT id FROM kb_documents WHERE source_path = ?", (str(source_path),)
    ).fetchone()
    doc_id = str(row["id"])
    return doc_id, {str(c["vector_id"]) for c in sqlite.get_chunks_by_document_id(doc_id)}


def test_only_the_sweep_removes_an_orphan_vector(
    stores: tuple[SqliteStore, LanceStore], tmp_path: Path
) -> None:
    sqlite, lance = stores
    vpn_id, vpn = _doc(sqlite, tmp_path / "vpn.md")
    _, dns = _doc(sqlite, tmp_path / "dns.md")
    assert _vector_ids(lance) == vpn | dns | {ORPHAN}

    # Deleting a document the way ``kb delete`` does reaches vectors through
    # its chunks, so the orphan outlives it.
    report = sqlite.delete_document(vpn_id, actor="tester", reason="test")
    lance.delete_by_vector_ids(report["vector_ids"])
    assert _vector_ids(lance) == dns | {ORPHAN}

    assert sweep_orphan_vectors(sqlite, lance) == [ORPHAN]
    assert _vector_ids(lance) == dns


def test_a_dry_run_names_the_orphans_and_deletes_nothing(
    stores: tuple[SqliteStore, LanceStore],
) -> None:
    sqlite, lance = stores
    before = _vector_ids(lance)

    assert sweep_orphan_vectors(sqlite, lance, dry_run=True) == [ORPHAN]
    assert _vector_ids(lance) == before


def test_the_cli_sweeps_the_configured_kb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPSPILOT_HOME", str(tmp_path / "home"))
    cfg = load_config()
    _, lance = _open_kb_stores(
        home=cfg.home, embedding_dim=EMBED_DIM, embedding_model=cfg.embed_model
    )
    lance.upsert_vectors([_orphan(dim=EMBED_DIM, model=cfg.embed_model)])
    runner = CliRunner()

    dry = runner.invoke(app, ["kb", "sweep-vectors", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert ORPHAN in dry.output
    assert lance.count() == 1

    swept = runner.invoke(app, ["kb", "sweep-vectors", "--yes"])
    assert swept.exit_code == 0, swept.output
    assert lance.count() == 0

    again = runner.invoke(app, ["kb", "sweep-vectors"])
    assert again.exit_code == 0, again.output
    assert "no orphan vectors" in again.output
