"""source_authority is settable at ingest, visible on hits, inert in ranking.

The field existed in the schema and on ``Hit`` but nothing could set it: the
ingest request had no such field, the CLI no such flag, and every document
landed on the ``internal`` default (#150). These lock in the three ways it can
now be set — and the promise that it still does not reorder anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.kb import router as kb_router
from opspilot.kb.ingestion import SOURCE_AUTHORITIES, IngestConfig
from opspilot.kb.ingestion import ingest as run_ingest
from opspilot.kb.lance_store import LanceStore
from opspilot.kb.retrieval import kb_search
from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.storage_init import init_sqlite
from opspilot.redaction import Redactor

_DIM = 8
_DOC = "# VPN SOP\n\nIf authentication fails, verify RADIUS and the user account.\n"


def _embed(text: str) -> list[float]:
    return [float(len(text) % 7) + 1.0] + [0.1] * (_DIM - 1)


def _stores(tmp_path: Path) -> tuple[SqliteStore, LanceStore]:
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=_DIM, embedding_model="m")
    return sqlite, lance


def _client(tmp_path: Path) -> tuple[TestClient, SqliteStore]:
    app = FastAPI()
    app.include_router(kb_router, prefix="/api")
    sqlite, lance = _stores(tmp_path)
    app.state.sqlite = sqlite
    app.state.lance = lance
    app.state.redactor = Redactor.from_yaml()
    app.state.embed_fn = _embed
    return TestClient(app), sqlite


def _authority_of(sqlite: SqliteStore, doc_id: str) -> str:
    return sqlite.get_source_authorities([doc_id])[doc_id]


def _ingest_via_api(client: TestClient, doc: Path, **body: object) -> str:
    """POST one file and return its document_id."""
    res = client.post("/api/kb/ingest", json={"paths": [str(doc)], **body})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["docs_succeeded"] == 1
    return str(payload["files"][0]["document_id"])


# ── settable ─────────────────────────────────────────────────────────


def test_api_ingest_records_the_requested_authority(tmp_path: Path) -> None:
    client, sqlite = _client(tmp_path)
    doc = tmp_path / "sop.md"
    doc.write_text(_DOC, encoding="utf-8")

    doc_id = _ingest_via_api(client, doc, source_authority="official")
    assert _authority_of(sqlite, doc_id) == "official"


def test_api_ingest_still_defaults_to_internal(tmp_path: Path) -> None:
    """Omitting the field must keep the old behaviour for existing callers."""
    client, sqlite = _client(tmp_path)
    doc = tmp_path / "sop.md"
    doc.write_text(_DOC, encoding="utf-8")

    doc_id = _ingest_via_api(client, doc)
    assert _authority_of(sqlite, doc_id) == "internal"


def test_api_ingest_rejects_an_unknown_authority(tmp_path: Path) -> None:
    """422 naming the field, not a sqlite CHECK failure part-way through."""
    client, _sqlite = _client(tmp_path)
    doc = tmp_path / "sop.md"
    doc.write_text(_DOC, encoding="utf-8")

    res = client.post(
        "/api/kb/ingest", json={"paths": [str(doc)], "source_authority": "trustworthy"}
    )
    assert res.status_code == 422
    assert "source_authority" in res.text


@pytest.mark.parametrize("authority", SOURCE_AUTHORITIES)
def test_every_declared_authority_survives_the_db_check(tmp_path: Path, authority: str) -> None:
    """SOURCE_AUTHORITIES must not drift from the column's CHECK constraint."""
    sqlite, lance = _stores(tmp_path / authority)
    doc = tmp_path / f"{authority}.md"
    doc.write_text(_DOC, encoding="utf-8")

    stats = run_ingest(
        [doc],
        sqlite=sqlite,
        lance=lance,
        redactor=Redactor.from_yaml(),
        embed_fn=_embed,
        config=IngestConfig(
            embedding_model="m",
            embedding_dim=_DIM,
            source_authority=authority,  # type: ignore[arg-type]
        ),
    )
    doc_id = stats.files[0].document_id
    assert doc_id is not None
    assert _authority_of(sqlite, doc_id) == authority


# ── visible ──────────────────────────────────────────────────────────


def test_search_hits_carry_the_authority(tmp_path: Path) -> None:
    client, _sqlite = _client(tmp_path)
    doc = tmp_path / "sop.md"
    doc.write_text(_DOC, encoding="utf-8")
    _ingest_via_api(client, doc, source_authority="vendor")

    hits = client.get("/api/kb/search", params={"q": "authentication"}).json()["hits"]
    assert hits and all(h["source_authority"] == "vendor" for h in hits)


# ── still inert in ranking ───────────────────────────────────────────


def test_authority_does_not_reorder_results(tmp_path: Path) -> None:
    """The staged decision on #150: provenance now, ranking unchanged.

    Two documents, the second a much better match for the query and the worse
    of the two by authority. Relevance has to win — if a later change makes
    authority a ranking signal, this is the test that should be revisited
    deliberately rather than quietly deleted.
    """
    sqlite, lance = _stores(tmp_path)
    redactor = Redactor.from_yaml()

    official = tmp_path / "official.md"
    official.write_text("# Printer setup\n\nHow to add a printer queue.\n", encoding="utf-8")
    unverified = tmp_path / "unverified.md"
    unverified.write_text(
        "# VPN authentication\n\nVPN authentication fails: check RADIUS.\n", encoding="utf-8"
    )

    for path, authority in ((official, "official"), (unverified, "unverified")):
        run_ingest(
            [path],
            sqlite=sqlite,
            lance=lance,
            redactor=redactor,
            embed_fn=_embed,
            config=IngestConfig(
                embedding_model="m",
                embedding_dim=_DIM,
                source_authority=authority,  # type: ignore[arg-type]
            ),
        )

    hits = kb_search("VPN authentication", sqlite=sqlite, lance=lance, embed_fn=_embed, top_k=2)
    assert hits[0].source_authority == "unverified"  # relevance, not provenance
