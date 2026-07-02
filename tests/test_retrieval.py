"""End-to-end retrieval test against the spec example KB.

This test enforces the **PR-4 exit criterion** from
``docs/zh/design/IMPLEMENTATION_STAGE_1.md §738``::

    把样例 chunks.jsonl 灌入两个 store；
    kb_search("VPN 认证失败") top-1 返回 chk_0cf89826

We use a hand-tuned mock ``embed_fn`` (``_topic_embed``) that maps text
into a sparse 3-axis "topic" space (auth / general / network), padded to
the spec's 768-dim. The mock is deterministic and intentionally simple —
the goal is to verify the retrieval **plumbing** (RRF, two-store join,
filters) rather than embedding quality. PR-7 swaps in the real
nomic-embed-text-v2-moe at integration time.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from opspilot.memory.lance_store import LanceStore, VectorRecord
from opspilot.memory.retrieval import RRF_K, Hit, kb_search
from opspilot.memory.sqlite_store import SqliteStore
from opspilot.memory.storage_init import init_sqlite

REPO_ROOT = Path(__file__).resolve().parents[1]
KB_DIR = REPO_ROOT / "examples" / "scn_ticket_summary_zh" / "kb"
DOC_META_PATH = KB_DIR / "doc-meta.json"
CHUNKS_JSONL_PATH = KB_DIR / "chunks.jsonl"

DIM = 768
EMBED_MODEL = "ollama-local/nomic-embed-text@2024-02"


# ── Deterministic mock embedder ──────────────────────────────────────


_AUTH_TERMS = ("认证", "鉴权", "auth", "authentication", "RADIUS", "LDAP")
_NETWORK_TERMS = ("隧道", "网络", "MTU", "NAT", "ESP", "tunnel", "ping", "<vpn_gw>")


def _topic_embed(text: str) -> list[float]:
    """Map text → 3-axis topic vector (auth, general, network), padded to 768.

    Returns a unit-length vector so cosine is a clean inner product.
    """
    lower = text.lower()
    auth_w = sum(1.0 for t in _AUTH_TERMS if t.lower() in lower)
    net_w = sum(1.0 for t in _NETWORK_TERMS if t.lower() in lower)
    base = [auth_w + 0.05, 0.30, net_w + 0.05]  # +0.05 prevents zero-length
    norm = math.sqrt(sum(x * x for x in base))
    head = [x / norm for x in base]
    return head + [0.0] * (DIM - 3)


# ── Fixture: populated KB ────────────────────────────────────────────


@pytest.fixture
def kb_stores(tmp_path: Path) -> tuple[SqliteStore, LanceStore]:
    """Load examples/.../kb into both stores using the mock embedder."""
    sqlite_conn = init_sqlite(tmp_path / "kb.db")
    sqlite = SqliteStore(sqlite_conn)
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)

    # Load doc-meta + chunks straight from the spec fixture.
    doc = json.loads(DOC_META_PATH.read_text(encoding="utf-8"))
    doc.pop("_comment", None)
    sqlite.upsert_document(doc)

    chunks: list[dict[str, Any]] = []
    with CHUNKS_JSONL_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            c.pop("_comment", None)
            chunks.append(c)
    sqlite.upsert_chunks(chunks)

    # Embed each chunk's content with the mock and load into LanceDB.
    vector_records: list[VectorRecord] = []
    for c in chunks:
        md = c["metadata"]
        vector_records.append(
            VectorRecord(
                vector_id=c["vector_id"],
                embedding=_topic_embed(c["content"] or ""),
                document_id=c["document_id"],
                chunk_id=c["id"],
                namespace=md["namespace"],
                classification=md["classification"],
                language=md.get("language", "und"),
                tags=md.get("tags", []),
                embedding_model=EMBED_MODEL,
            )
        )
    lance.upsert_vectors(vector_records)
    return sqlite, lance


# ── Exit-criterion test ──────────────────────────────────────────────


def test_exit_criterion_top1_is_authentication_chunk(
    kb_stores: tuple[SqliteStore, LanceStore],
) -> None:
    """PR-4 exit criterion: kb_search("VPN 认证失败") → top-1 = chk_0cf89826."""
    sqlite, lance = kb_stores
    hits = kb_search(
        "VPN 认证失败",
        sqlite=sqlite,
        lance=lance,
        embed_fn=_topic_embed,
        top_k=3,
    )
    assert len(hits) >= 1
    assert hits[0].chunk_id == "chk_0cf89826"
    # Sanity on the structure.
    assert isinstance(hits[0], Hit)
    assert hits[0].score > 0
    assert hits[0].document_id == "doc_88a277cf"
    assert hits[0].namespace == "opspilot:public-kb"
    assert hits[0].content is not None
    assert "认证" in hits[0].content


# ── Behavioural tests ────────────────────────────────────────────────


def test_kb_search_empty_query_returns_empty(
    kb_stores: tuple[SqliteStore, LanceStore],
) -> None:
    sqlite, lance = kb_stores
    assert kb_search("", sqlite=sqlite, lance=lance, embed_fn=_topic_embed) == []
    assert kb_search("   ", sqlite=sqlite, lance=lance, embed_fn=_topic_embed) == []


def test_kb_search_respects_top_k(
    kb_stores: tuple[SqliteStore, LanceStore],
) -> None:
    sqlite, lance = kb_stores
    hits = kb_search(
        "VPN",
        sqlite=sqlite,
        lance=lance,
        embed_fn=_topic_embed,
        top_k=2,
    )
    assert len(hits) <= 2


def test_kb_search_namespace_filter_excludes_other_kb(
    tmp_path: Path,
) -> None:
    """Filter should pass through to both stores."""
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)

    # Two docs in two namespaces. Same content; we want filter to hide
    # the private one when namespace='opspilot:public-kb'.
    for doc_id, ns in (
        ("doc_aaaaaaaa", "opspilot:public-kb"),
        ("doc_bbbbbbbb", "opspilot:private-kb"),
    ):
        sqlite.upsert_document(
            {
                "id": doc_id,
                "source_path": f"x/{doc_id}.md",
                "title": "VPN auth doc",
                "classification": "internal",
                "content_hash": "sha256:" + ("a" * 64),
                "ingested_at": "2026-05-01T10:00:00Z",
                "language": "zh-CN",
                "tags": [],
                "namespace": ns,
                "chunk_strategy": "headings_then_size",
                "chunk_count": 1,
                "embedding_model": EMBED_MODEL,
                "embedding_dim": DIM,
                "redaction_passed": True,
            }
        )
        cid = "chk_aaaaaaaa" if ns.endswith("public-kb") else "chk_bbbbbbbb"
        chunk_payload = {
            "id": cid,
            "document_id": doc_id,
            "seq": 0,
            "content": "VPN 认证失败 排查",
            "content_hash": "sha256:" + ("a" * 64),
            "char_start": 0,
            "char_end": 10,
            "line_start": 1,
            "line_end": 1,
            "embedding_model": EMBED_MODEL,
            "vector_id": f"vec_{cid}",
            "metadata": {
                "namespace": ns,
                "classification": "internal",
                "language": "zh-CN",
                "tags": [],
            },
        }
        sqlite.upsert_chunks([chunk_payload])
        lance.upsert_vectors(
            [
                VectorRecord(
                    vector_id=f"vec_{cid}",
                    embedding=_topic_embed("VPN 认证失败 排查"),
                    document_id=doc_id,
                    chunk_id=cid,
                    namespace=ns,
                    classification="internal",
                    language="zh-CN",
                    tags=[],
                    embedding_model=EMBED_MODEL,
                )
            ]
        )

    hits = kb_search(
        "VPN 认证失败",
        sqlite=sqlite,
        lance=lance,
        embed_fn=_topic_embed,
        top_k=5,
        namespace="opspilot:public-kb",
    )
    assert {h.chunk_id for h in hits} == {"chk_aaaaaaaa"}


def test_kb_search_returns_hit_metadata(
    kb_stores: tuple[SqliteStore, LanceStore],
) -> None:
    """Both per-source ranks should be exposed for debugging."""
    sqlite, lance = kb_stores
    hits = kb_search(
        "VPN 认证失败",
        sqlite=sqlite,
        lance=lance,
        embed_fn=_topic_embed,
        top_k=3,
    )
    target = next(h for h in hits if h.chunk_id == "chk_0cf89826")
    # Vector path should have seen it (likely rank 1 due to hand-tuned vec).
    assert target.rank_vector is not None
    # FTS may or may not have surfaced it depending on tokenisation;
    # but if it did, rank should be a positive int.
    if target.rank_fts is not None:
        assert target.rank_fts >= 1


def test_rrf_constant_is_sixty() -> None:
    """Don't drift the constant without thinking about ranking dynamics."""
    assert RRF_K == 60


# ── source_authority tie-breaking tests ─────────────────────────────


def _make_two_authority_stores(
    tmp_path: Path, authority_a: str, authority_b: str
) -> tuple[SqliteStore, LanceStore]:
    """Create two docs with identical content but different source_authority.

    Both chunks get the same embedding so RRF scores are equal; the
    authority rank should break the tie.
    """
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)

    content = "VPN authentication fails — please verify RADIUS credentials and retry"

    for doc_id, cid, authority in (
        ("doc_aaaaaaaa", "chk_aaaaaaaa", authority_a),
        ("doc_bbbbbbbb", "chk_bbbbbbbb", authority_b),
    ):
        sqlite.upsert_document(
            {
                "id": doc_id,
                "source_path": f"docs/{doc_id}.md",
                "title": f"VPN doc ({authority})",
                "classification": "internal",
                "content_hash": "sha256:" + (doc_id[-1] * 64),
                "ingested_at": "2026-05-01T10:00:00Z",
                "language": "en",
                "tags": [],
                "namespace": "opspilot:public-kb",
                "chunk_strategy": "headings_then_size",
                "chunk_count": 1,
                "embedding_model": EMBED_MODEL,
                "embedding_dim": DIM,
                "redaction_passed": True,
                "source_authority": authority,
            }
        )
        sqlite.upsert_chunks(
            [
                {
                    "id": cid,
                    "document_id": doc_id,
                    "seq": 0,
                    "content": content,
                    "content_hash": "sha256:" + (cid[-1] * 64),
                    "char_start": 0,
                    "char_end": len(content),
                    "line_start": 1,
                    "line_end": 1,
                    "embedding_model": EMBED_MODEL,
                    "vector_id": f"vec_{cid}",
                    "metadata": {
                        "namespace": "opspilot:public-kb",
                        "classification": "internal",
                        "language": "en",
                        "tags": [],
                    },
                }
            ]
        )
        embedding = _topic_embed(content)
        lance.upsert_vectors(
            [
                VectorRecord(
                    vector_id=f"vec_{cid}",
                    embedding=embedding,
                    document_id=doc_id,
                    chunk_id=cid,
                    namespace="opspilot:public-kb",
                    classification="internal",
                    language="en",
                    tags=[],
                    embedding_model=EMBED_MODEL,
                )
            ]
        )

    return sqlite, lance


def test_official_ranks_above_internal_on_equal_rrf(tmp_path: Path) -> None:
    """'official' source_authority should beat 'internal' as tie-breaker."""
    sqlite, lance = _make_two_authority_stores(tmp_path, "official", "internal")
    hits = kb_search(
        "VPN authentication",
        sqlite=sqlite,
        lance=lance,
        embed_fn=_topic_embed,
        top_k=2,
    )
    assert len(hits) == 2
    assert hits[0].chunk_id == "chk_aaaaaaaa"  # official
    assert hits[0].source_authority == "official"
    assert hits[1].source_authority == "internal"


def test_official_ranks_above_unverified_on_equal_rrf(tmp_path: Path) -> None:
    """'official' should also beat 'unverified'."""
    sqlite, lance = _make_two_authority_stores(tmp_path, "official", "unverified")
    hits = kb_search(
        "VPN authentication",
        sqlite=sqlite,
        lance=lance,
        embed_fn=_topic_embed,
        top_k=2,
    )
    assert len(hits) == 2
    assert hits[0].chunk_id == "chk_aaaaaaaa"  # official
    assert hits[1].chunk_id == "chk_bbbbbbbb"  # unverified


def test_vendor_ranks_above_unverified_on_equal_rrf(tmp_path: Path) -> None:
    """'vendor' should beat 'unverified'."""
    sqlite, lance = _make_two_authority_stores(tmp_path, "vendor", "unverified")
    hits = kb_search(
        "VPN authentication",
        sqlite=sqlite,
        lance=lance,
        embed_fn=_topic_embed,
        top_k=2,
    )
    assert len(hits) == 2
    assert hits[0].source_authority == "vendor"
    assert hits[1].source_authority == "unverified"


def test_source_authority_propagated_to_hit(tmp_path: Path) -> None:
    """Hit.source_authority should reflect the document's actual value."""
    sqlite, lance = _make_two_authority_stores(tmp_path, "vendor", "internal")
    hits = kb_search(
        "VPN authentication",
        sqlite=sqlite,
        lance=lance,
        embed_fn=_topic_embed,
        top_k=2,
    )
    authority_by_chunk = {h.chunk_id: h.source_authority for h in hits}
    assert authority_by_chunk["chk_aaaaaaaa"] == "vendor"
    assert authority_by_chunk["chk_bbbbbbbb"] == "internal"
