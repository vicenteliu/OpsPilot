"""Tests for ``opspilot.memory.ingestion``.

Covers the end-to-end pipeline:
markitdown → redact → chunk → embed → upsert
plus dedup, error fan-out, and the spec exit criterion that an
ingested .md remains kb-searchable.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Final

import pytest

from opspilot.memory.ingestion import (
    IngestConfig,
    IngestionError,
    discover_files,
    ingest,
)
from opspilot.memory.lance_store import LanceStore
from opspilot.memory.retrieval import kb_search
from opspilot.memory.sqlite_store import SqliteStore
from opspilot.memory.storage_init import init_sqlite
from opspilot.redaction import Redactor

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_MD = REPO_ROOT / "examples" / "scn_ticket_summary_zh" / "kb" / "sop_vpn_zh.md"
SAMPLE_PDF = REPO_ROOT / "tests" / "fixtures" / "sample.pdf"

DIM = 768
EMBED_MODEL: Final[str] = "ollama-local/test-embed@2026-04"


# ── Mock embedder (3-axis topic vector, padded to 768) ───────────────


_AUTH_TERMS = ("认证", "鉴权", "auth", "authentication", "RADIUS", "LDAP")
_NETWORK_TERMS = ("隧道", "网络", "MTU", "NAT", "ESP", "tunnel", "ping")


def _topic_embed(text: str) -> list[float]:
    lower = text.lower()
    auth_w = sum(1.0 for t in _AUTH_TERMS if t.lower() in lower)
    net_w = sum(1.0 for t in _NETWORK_TERMS if t.lower() in lower)
    base = [auth_w + 0.05, 0.30, net_w + 0.05]
    norm = math.sqrt(sum(x * x for x in base))
    head = [x / norm for x in base]
    return head + [0.0] * (DIM - 3)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def stores(tmp_path: Path) -> tuple[SqliteStore, LanceStore]:
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)
    return sqlite, lance


@pytest.fixture
def redactor() -> Redactor:
    return Redactor.from_yaml()


@pytest.fixture
def cfg() -> IngestConfig:
    return IngestConfig(embedding_model=EMBED_MODEL, embedding_dim=DIM)


# ── discover_files ───────────────────────────────────────────────────


def test_discover_single_file(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text("hi", encoding="utf-8")
    assert discover_files([f]) == [f]


def test_discover_directory_recursive(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hi", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.md").write_text("bye", encoding="utf-8")
    out = discover_files([tmp_path])
    assert len(out) == 2


def test_discover_skips_hidden(tmp_path: Path) -> None:
    (tmp_path / ".hidden.md").write_text("x", encoding="utf-8")
    (tmp_path / "visible.md").write_text("y", encoding="utf-8")
    out = discover_files([tmp_path])
    assert {p.name for p in out} == {"visible.md"}


# ── Single-file ingest ───────────────────────────────────────────────


def test_ingest_md_creates_doc_and_chunks(
    stores: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    cfg: IngestConfig,
) -> None:
    sqlite, lance = stores
    stats = ingest(
        [SAMPLE_MD],
        sqlite=sqlite,
        lance=lance,
        redactor=redactor,
        embed_fn=_topic_embed,
        config=cfg,
    )
    assert stats.docs_succeeded == 1
    assert stats.docs_failed == 0
    assert stats.chunks_total >= 1
    assert lance.count() == stats.chunks_total


def test_ingest_pdf_via_markitdown(
    stores: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    cfg: IngestConfig,
) -> None:
    sqlite, lance = stores
    stats = ingest(
        [SAMPLE_PDF],
        sqlite=sqlite,
        lance=lance,
        redactor=redactor,
        embed_fn=_topic_embed,
        config=cfg,
    )
    assert stats.docs_succeeded == 1
    # PDF-derived markdown should yield at least one searchable chunk.
    hits = kb_search(
        "OpsPilot ingestion fixture",
        sqlite=sqlite,
        lance=lance,
        embed_fn=_topic_embed,
        top_k=3,
    )
    assert any("OpsPilot" in (h.content or "") for h in hits)


def test_ingest_then_kb_search_roundtrip(
    stores: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    cfg: IngestConfig,
) -> None:
    """End-to-end: ingest the example .md and verify auth chunk surfaces."""
    sqlite, lance = stores
    ingest(
        [SAMPLE_MD],
        sqlite=sqlite,
        lance=lance,
        redactor=redactor,
        embed_fn=_topic_embed,
        config=cfg,
    )
    hits = kb_search(
        "VPN 认证失败",
        sqlite=sqlite,
        lance=lance,
        embed_fn=_topic_embed,
        top_k=3,
    )
    assert hits
    assert any("认证" in (h.content or "") for h in hits)


# ── Dedup ────────────────────────────────────────────────────────────


def test_ingest_unchanged_is_noop(
    stores: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    cfg: IngestConfig,
) -> None:
    sqlite, lance = stores
    s1 = ingest(
        [SAMPLE_MD],
        sqlite=sqlite,
        lance=lance,
        redactor=redactor,
        embed_fn=_topic_embed,
        config=cfg,
    )
    initial_chunks = s1.chunks_total
    initial_lance_count = lance.count()

    s2 = ingest(
        [SAMPLE_MD],
        sqlite=sqlite,
        lance=lance,
        redactor=redactor,
        embed_fn=_topic_embed,
        config=cfg,
    )
    assert s2.docs_succeeded == 1
    assert s2.chunks_total == 0  # nothing rewritten
    assert s2.files[0].chunks_skipped_unchanged is True
    # Storage should be unchanged.
    assert lance.count() == initial_lance_count
    cur = sqlite._conn.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()
    assert cur[0] == initial_chunks


def test_ingest_modified_file_replaces_chunks(
    tmp_path: Path,
    stores: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    cfg: IngestConfig,
) -> None:
    sqlite, lance = stores
    p = tmp_path / "doc.md"
    p.write_text("# Title\n\nfirst content auth\n", encoding="utf-8")
    s1 = ingest(
        [p], sqlite=sqlite, lance=lance, redactor=redactor, embed_fn=_topic_embed, config=cfg
    )
    initial_doc_id = s1.files[0].document_id

    p.write_text("# Title\n\nsecond entirely different network MTU\n", encoding="utf-8")
    s2 = ingest(
        [p], sqlite=sqlite, lance=lance, redactor=redactor, embed_fn=_topic_embed, config=cfg
    )
    new_doc_id = s2.files[0].document_id
    assert new_doc_id != initial_doc_id  # content_hash → new sha8 prefix
    # Old chunks gone, new ones exist.
    cur = sqlite._conn.execute("SELECT COUNT(*) FROM kb_documents").fetchone()
    assert cur[0] == 1  # only the new doc; old was deleted
    assert lance.count() >= 1


# ── Restricted classification skips vector path ─────────────────────


def test_restricted_classification_skips_lance(
    stores: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
) -> None:
    sqlite, lance = stores
    cfg = IngestConfig(
        embedding_model=EMBED_MODEL,
        embedding_dim=DIM,
        classification="restricted",
    )
    stats = ingest(
        [SAMPLE_MD],
        sqlite=sqlite,
        lance=lance,
        redactor=redactor,
        embed_fn=_topic_embed,
        config=cfg,
    )
    assert stats.docs_succeeded == 1
    assert stats.chunks_total >= 1
    # SQLite has the chunks (FTS5 path) but LanceDB stays empty.
    assert lance.count() == 0


# ── Error fan-out ────────────────────────────────────────────────────


def test_unsupported_file_records_error(
    tmp_path: Path,
    stores: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    cfg: IngestConfig,
) -> None:
    sqlite, lance = stores
    bad = tmp_path / "code.py"
    bad.write_text("print('hi')", encoding="utf-8")
    stats = ingest(
        [bad],
        sqlite=sqlite,
        lance=lance,
        redactor=redactor,
        embed_fn=_topic_embed,
        config=cfg,
    )
    assert stats.docs_failed == 1
    assert stats.docs_succeeded == 0
    assert stats.files[0].error is not None
    assert "unsupported" in stats.files[0].error.lower()


def test_partial_failure_does_not_abort_run(
    tmp_path: Path,
    stores: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    cfg: IngestConfig,
) -> None:
    """One bad file, one good file → the good one still ingests."""
    sqlite, lance = stores
    bad = tmp_path / "bad.py"
    bad.write_text("oops", encoding="utf-8")
    good = tmp_path / "good.md"
    good.write_text("# Good\n\nauth content\n", encoding="utf-8")

    stats = ingest(
        [bad, good],
        sqlite=sqlite,
        lance=lance,
        redactor=redactor,
        embed_fn=_topic_embed,
        config=cfg,
    )
    assert stats.docs_succeeded == 1
    assert stats.docs_failed == 1


def test_hard_fail_pii_aborts_whole_run(
    tmp_path: Path,
    stores: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    cfg: IngestConfig,
) -> None:
    """A private key in the source must halt the entire batch.

    Default redaction rules ship a `private_key` rule — we don't want any
    text containing one ever to enter the KB even after redaction.
    """
    sqlite, lance = stores
    p = tmp_path / "leaky.md"
    p.write_text(
        "# Leaky\n\n-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA/DummyDummyDummyDummyDummyDummyDummyDummy\n"
        "AnotherFakeBlobOfBase64ContentForTheSakeOfMatching+/=\n"
        "-----END RSA PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    with pytest.raises(IngestionError, match="hard-fail"):
        ingest(
            [p],
            sqlite=sqlite,
            lance=lance,
            redactor=redactor,
            embed_fn=_topic_embed,
            config=cfg,
        )


# ── ingest_runs row written ──────────────────────────────────────────


def test_ingest_run_row_written(
    stores: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    cfg: IngestConfig,
) -> None:
    sqlite, _ = stores
    ingest(
        [SAMPLE_MD],
        sqlite=sqlite,
        lance=stores[1],
        redactor=redactor,
        embed_fn=_topic_embed,
        config=cfg,
    )
    cur = sqlite._conn.execute("SELECT id, status, docs_succeeded FROM ingest_runs")
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "succeeded"
    assert rows[0]["docs_succeeded"] == 1
    assert rows[0]["id"].startswith("run_")


def test_empty_inputs_writes_no_op_run(
    stores: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    cfg: IngestConfig,
) -> None:
    sqlite, lance = stores
    stats = ingest(
        [],
        sqlite=sqlite,
        lance=lance,
        redactor=redactor,
        embed_fn=_topic_embed,
        config=cfg,
    )
    assert stats.docs_total == 0
    cur = sqlite._conn.execute("SELECT COUNT(*) FROM ingest_runs").fetchone()
    assert cur[0] == 1


# ── valid_from / source_authority / conflict detection ──────────────


def _get_doc_by_source(sqlite: SqliteStore, source_path: str) -> dict | None:
    cur = sqlite._conn.execute(
        "SELECT * FROM kb_documents WHERE source_path=?", (source_path,)
    )
    row = cur.fetchone()
    return dict(row) if row else None


def test_ingest_stores_valid_from_from_frontmatter(
    tmp_path: Path, stores: tuple[SqliteStore, LanceStore], redactor: Redactor
) -> None:
    md = tmp_path / "sop_2026-03-01.md"
    md.write_text(
        "---\nvalid_from: 2026-03-01\n---\n\n"
        "## VPN auth\n\nAuthentication step: check RADIUS credentials.\n",
        encoding="utf-8",
    )
    cfg = IngestConfig(embedding_model=EMBED_MODEL, embedding_dim=DIM, detect_conflicts=False)
    sqlite, lance = stores
    ingest([md], sqlite=sqlite, lance=lance, redactor=redactor, embed_fn=_topic_embed, config=cfg)

    doc = _get_doc_by_source(sqlite, str(md))
    assert doc is not None
    assert (doc["valid_from"] or "").startswith("2026-03-01")


def test_ingest_stores_valid_from_from_filename(
    tmp_path: Path, stores: tuple[SqliteStore, LanceStore], redactor: Redactor
) -> None:
    md = tmp_path / "guide_2025-11-15.md"
    md.write_text(
        "## Setup\n\nAuthentication step: check RADIUS credentials.\n",
        encoding="utf-8",
    )
    cfg = IngestConfig(embedding_model=EMBED_MODEL, embedding_dim=DIM, detect_conflicts=False)
    sqlite, lance = stores
    ingest([md], sqlite=sqlite, lance=lance, redactor=redactor, embed_fn=_topic_embed, config=cfg)

    doc = _get_doc_by_source(sqlite, str(md))
    assert doc is not None
    assert (doc["valid_from"] or "").startswith("2025-11-15")


def test_ingest_stores_source_authority(
    tmp_path: Path, stores: tuple[SqliteStore, LanceStore], redactor: Redactor
) -> None:
    md = tmp_path / "official.md"
    md.write_text(
        "## VPN\n\nAuthentication step: check RADIUS credentials.\n",
        encoding="utf-8",
    )
    cfg = IngestConfig(
        embedding_model=EMBED_MODEL,
        embedding_dim=DIM,
        source_authority="official",
        detect_conflicts=False,
    )
    sqlite, lance = stores
    ingest([md], sqlite=sqlite, lance=lance, redactor=redactor, embed_fn=_topic_embed, config=cfg)

    doc = _get_doc_by_source(sqlite, str(md))
    assert doc is not None
    assert doc["source_authority"] == "official"


def test_ingest_conflict_detection_creates_conflict_record(
    tmp_path: Path, stores: tuple[SqliteStore, LanceStore], redactor: Redactor
) -> None:
    """Two semantically similar docs should produce a kb_conflicts row."""
    content = (
        "## VPN Authentication\n\n"
        "To authenticate, enter your RADIUS credentials and click Submit.\n"
        "If authentication fails, contact your administrator.\n"
    )
    doc_a = tmp_path / "vpn_auth_a.md"
    doc_b = tmp_path / "vpn_auth_b.md"
    doc_a.write_text(content, encoding="utf-8")
    doc_b.write_text(content + "\nAdditional note: also check your VPN client version.\n", encoding="utf-8")

    cfg = IngestConfig(
        embedding_model=EMBED_MODEL,
        embedding_dim=DIM,
        detect_conflicts=True,
        conflict_similarity_threshold=0.80,
    )
    sqlite, lance = stores
    ingest(
        [doc_a, doc_b],
        sqlite=sqlite, lance=lance, redactor=redactor, embed_fn=_topic_embed, config=cfg,
    )

    conflicts = sqlite.list_conflicts(status="open")
    assert len(conflicts) >= 1


def test_ingest_resolve_then_superseded_excluded_from_retrieval(
    tmp_path: Path, stores: tuple[SqliteStore, LanceStore], redactor: Redactor
) -> None:
    """Full pipeline: ingest → detect conflict → resolve (a_wins) → b chunk excluded."""
    content_a = (
        "## VPN Authentication\n\n"
        "Authenticate via RADIUS credentials. If it fails, reset your password.\n"
    )
    content_b = (
        "## VPN Authentication\n\n"
        "Authenticate via RADIUS credentials. If it fails, reset your password.\n"
        "Note: legacy LDAP mode is deprecated.\n"
    )
    doc_a = tmp_path / "vpn_a.md"
    doc_b = tmp_path / "vpn_b.md"
    doc_a.write_text(content_a, encoding="utf-8")
    doc_b.write_text(content_b, encoding="utf-8")

    cfg = IngestConfig(
        embedding_model=EMBED_MODEL,
        embedding_dim=DIM,
        detect_conflicts=True,
        conflict_similarity_threshold=0.80,
    )
    sqlite, lance = stores
    ingest(
        [doc_a, doc_b],
        sqlite=sqlite, lance=lance, redactor=redactor, embed_fn=_topic_embed, config=cfg,
    )

    conflicts = sqlite.list_conflicts(status="open")
    assert conflicts, "expected at least one conflict to be detected"
    conf_id = conflicts[0]["id"]

    from opspilot.memory.conflict import resolve_conflict
    resolve_conflict(conf_id, resolution="a_wins", resolved_by="tester", sqlite=sqlite)

    # After resolution, retrieval should not surface the superseded (b-side) chunk.
    hits = kb_search(
        "RADIUS authentication",
        sqlite=sqlite,
        lance=lance,
        embed_fn=_topic_embed,
        top_k=10,
        exclude_superseded=True,
    )
    winning_doc_id = sqlite.get_conflict(conf_id)["doc_a_id"]
    losing_doc_id = sqlite.get_conflict(conf_id)["doc_b_id"]
    hit_doc_ids = {h.document_id for h in hits}
    assert winning_doc_id in hit_doc_ids, "winning doc must appear in results"
    assert losing_doc_id not in hit_doc_ids, "losing doc chunks must be excluded"
