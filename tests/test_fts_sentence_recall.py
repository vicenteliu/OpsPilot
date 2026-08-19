"""The keyword arm has to survive a question written as a sentence.

`_safe_fts_query` quoted every token and relied on FTS5's default implicit AND,
so a question required every stopword — "why", "would", "a", "be", "in" — to
appear in the document. Measured on a real 5-document KB:

    "CrashLoopBackOff"                              FTS ranks 1, 2
    "pod CrashLoopBackOff"                          FTS ranks 1, 2
    "why would a pod be stuck in CrashLoopBackOff"  FTS contributed nothing

A sentence is the product's dominant input — Chat/Consultation, Telegram, a
ticket body — so hybrid retrieval was silently pure-vector in normal use. The
existing tests all fed one or two keywords; the longest was "VPN authentication".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opspilot.kb.retrieval import _safe_fts_query
from opspilot.kb.sqlite_store import SqliteStore
from opspilot.kb.storage_init import init_sqlite

_QUESTION = "why would a pod be stuck in CrashLoopBackOff"


class TestQueryShape:
    def test_tokens_are_or_ed(self) -> None:
        assert _safe_fts_query("pod crashloop") == '"pod" OR "crashloop"'

    def test_a_single_token_is_unchanged(self) -> None:
        assert _safe_fts_query("CrashLoopBackOff") == '"CrashLoopBackOff"'

    def test_empty_input_stays_empty(self) -> None:
        assert _safe_fts_query("   ") == ""

    def test_fts5_syntax_is_still_neutralised(self) -> None:
        """The sanitiser's original job: a redaction placeholder must not crash."""
        assert _safe_fts_query("[REDACTED:role:11111111]") == '"REDACTED" OR "role" OR "11111111"'

    def test_cjk_still_tokenises(self) -> None:
        assert _safe_fts_query("VPN 认证失败") == '"VPN" OR "认证失败"'


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    s = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    s.upsert_document(
        {
            "id": "doc_11111111",
            "source_path": "/pods.md",
            "title": "Pod failures",
            "classification": "internal",
            "content_hash": "sha256:" + ("a" * 64),
            "ingested_at": "2026-01-01T00:00:00Z",
            "language": "en",
            "tags": [],
            "namespace": "ns",
            "chunk_strategy": "headings_then_size",
            "chunk_count": 2,
            "embedding_model": "nomic-embed-text-v2-moe",
            "embedding_dim": 768,
            "redaction_passed": True,
            "valid_from": None,
        }
    )
    for i, (cid, text) in enumerate(
        [
            ("chk_aaaaaaaa", "CrashLoopBackOff means the container exits and is restarted"),
            ("chk_bbbbbbbb", "ImagePullBackOff means registry auth failed"),
        ]
    ):
        s.upsert_chunks(
            [
                {
                    "id": cid,
                    "document_id": "doc_11111111",
                    "seq": i,
                    "content": text,
                    "content_hash": f"sha256:{i:064d}",
                    "char_start": 0,
                    "char_end": len(text),
                    "line_start": 1,
                    "line_end": 1,
                    "embedding_model": "nomic-embed-text-v2-moe",
                    "vector_id": f"vec_{cid}",
                    "metadata": {"namespace": "ns", "classification": "internal"},
                }
            ]
        )
    return s


class TestSentenceRecall:
    def test_a_question_reaches_the_document_that_answers_it(self, store: SqliteStore) -> None:
        hits = store.fts_search(_safe_fts_query(_QUESTION), top_k=5)
        assert [h.chunk_id for h in hits][:1] == ["chk_aaaaaaaa"]

    def test_the_same_question_found_nothing_under_implicit_and(self, store: SqliteStore) -> None:
        """The old shape, kept as the record of what regressing would look like."""
        and_query = " ".join(f'"{t}"' for t in _QUESTION.split())
        assert store.fts_search(and_query, top_k=5) == []

    def test_a_bare_keyword_still_behaves(self, store: SqliteStore) -> None:
        hits = store.fts_search(_safe_fts_query("CrashLoopBackOff"), top_k=5)
        assert [h.chunk_id for h in hits] == ["chk_aaaaaaaa"]

    def test_bm25_still_ranks_the_better_match_first(self, store: SqliteStore) -> None:
        """OR widens the candidate set; BM25 is what keeps it ordered."""
        hits = store.fts_search(_safe_fts_query("registry auth failed"), top_k=5)
        assert hits[0].chunk_id == "chk_bbbbbbbb"
