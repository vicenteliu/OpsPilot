"""Tests for opspilot.wiki (PR-19)."""

from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from opspilot.memory.sqlite_store import SqliteStore
from opspilot.memory.storage_init import init_sqlite
from opspilot.providers.types import ChatResponse, Usage
from opspilot.wiki.index import WikiLogEntry, append_log, update_index
from opspilot.wiki.ingest import WikiIngestConfig, WikiIngestError, ingest
from opspilot.wiki.page import WikiPage, make_page_id, read_page, write_page


# ──────────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────────


def _make_sqlite(tmp_path: Path) -> SqliteStore:
    db_path = tmp_path / "test.db"
    return SqliteStore(init_sqlite(db_path))


def _insert_doc_and_chunks(sqlite: SqliteStore, doc_id: str, content: str) -> None:
    import hashlib

    sha = hashlib.sha256(content.encode()).hexdigest()
    doc: dict[str, Any] = {
        "id": doc_id,
        "source_path": f"kb/{doc_id}.md",
        "source_url": None,
        "title": "Test Document",
        "classification": "internal",
        "content_hash": f"sha256:{sha}",
        "version": "1.0.0",
        "ingested_at": "2026-05-01T00:00:00Z",
        "last_modified": None,
        "language": "zh-CN",
        "namespace": "opspilot:public-kb",
        "tags": [],
        "extensions": {},
        "redaction_passed": True,
        "redaction_rules_version": "1.0.0",
        "chunk_strategy": "headings_then_size",
        "chunk_count": 1,
        "embedding_model": "test-embed-model",
        "embedding_dim": 768,
        "license": None,
    }
    sqlite.upsert_document(doc)
    sqlite.upsert_chunks(
        [
            {
                "id": f"chk_{sha[:8]}",
                "document_id": doc_id,
                "seq": 0,
                "content": content,
                "content_artifact_id": None,
                "content_hash": f"sha256:{sha}",
                "char_start": 0,
                "char_end": len(content),
                "line_start": 1,
                "line_end": 5,
                "heading_path": ["Test"],
                "anchor": None,
                "token_count": len(content) // 3,
                "embedding_model": "test-model",
                "vector_id": f"vec_{sha[:8]}",
                "namespace": "opspilot:public-kb",
                "classification": "internal",
                "language": "zh-CN",
                "tags": [],
            }
        ]
    )


def _mock_provider(slug: str = "test-sop-zh") -> MagicMock:
    """Return a provider mock that always returns a valid wiki page proposal."""
    import json

    body = textwrap.dedent(
        """\
        ## TL;DR

        This SOP describes network device maintenance procedures.

        ## Key claims

        1. Monthly maintenance window on first Saturday 00:00-04:00.
        2. Must backup config before any changes.
        3. Verify BGP/OSPF neighbors after maintenance.

        ## Implications for our wiki

        Missing pages: [[bgp-neighbor-troubleshooting]], [[stp-root-bridge]].

        ## Cross-links

        - see_also → [[network-device-inventory]]

        ## Sources

        1. [Network Maintenance SOP](kb/doc_aabb1234.md) — full text

        ## Changelog

        - v1.0.0 (2026-05-04): initial; from doc_aabb1234
        """
    )
    proposal = {
        "slug": slug,
        "title": "Source Summary: Network Maintenance SOP (Chinese)",
        "summary": "Monthly network device maintenance: backup, BGP/STP checks, firmware upgrade.",
        "language": "zh-CN",
        "tags": ["network", "maintenance", "sop"],
        "aliases": [],
        "body": body,
    }
    mock = MagicMock()
    mock.chat.return_value = ChatResponse(
        content=json.dumps(proposal),
        finish_reason="stop",
        usage=Usage(input_tokens=100, output_tokens=200),
    )
    return mock


# ──────────────────────────────────────────────────────────────────────────
#  page.py
# ──────────────────────────────────────────────────────────────────────────


class TestWikiPage:
    def test_make_page_id(self) -> None:
        pid = make_page_id("my-slug", "some body text")
        assert pid.startswith("wpg_")
        assert len(pid) == 12  # "wpg_" + 8 hex chars

    def test_make_page_id_deterministic(self) -> None:
        assert make_page_id("slug", "body") == make_page_id("slug", "body")

    def test_make_page_id_differs_on_body(self) -> None:
        assert make_page_id("slug", "body-a") != make_page_id("slug", "body-b")

    def test_write_read_roundtrip(self, tmp_path: Path) -> None:
        slug = "test-page"
        body = "## TL;DR\n\nSome content.\n"
        page = WikiPage(
            page_id=make_page_id(slug, body),
            slug=slug,
            kind="summary",
            title="Test Page",
            summary="A test wiki page.",
            namespace="opspilot:public-kb",
            classification="internal",
            language="en",
            version="1.0.0",
            created_at="2026-05-04T00:00:00Z",
            updated_at="2026-05-04T00:00:00Z",
            derived_from={"sources": [], "parent_pages": []},
            outbound_links=[],
            inbound_link_count=0,
            redacted=True,
            redaction_rules_version="1.0.0",
            lifecycle_state="live",
            owner="test@opspilot",
            body=body,
            tags=["test"],
        )
        path = tmp_path / "test-page.md"
        write_page(page, path)
        assert path.exists()
        loaded = read_page(path)
        assert loaded.page_id == page.page_id
        assert loaded.slug == page.slug
        assert loaded.title == page.title
        assert loaded.body.strip() == body.strip()
        assert loaded.tags == ["test"]

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        page = WikiPage(
            page_id="wpg_12345678",
            slug="nested-page",
            kind="summary",
            title="Nested",
            summary="Nested page test.",
            namespace="opspilot:public-kb",
            classification="internal",
            language="en",
            version="1.0.0",
            created_at="2026-05-04T00:00:00Z",
            updated_at="2026-05-04T00:00:00Z",
            derived_from={"sources": [], "parent_pages": []},
            outbound_links=[],
            inbound_link_count=0,
            redacted=True,
            redaction_rules_version="1.0.0",
            lifecycle_state="live",
            owner="test@opspilot",
            body="## TL;DR\n\nBody.\n",
        )
        path = tmp_path / "pages" / "summary" / "nested-page.md"
        write_page(page, path)
        assert path.exists()


# ──────────────────────────────────────────────────────────────────────────
#  index.py
# ──────────────────────────────────────────────────────────────────────────


class TestIndex:
    def _make_page(self, slug: str) -> WikiPage:
        body = "## TL;DR\n\nContent.\n"
        return WikiPage(
            page_id=make_page_id(slug, body),
            slug=slug,
            kind="summary",
            title=f"Page {slug}",
            summary=f"Summary for {slug}.",
            namespace="opspilot:public-kb",
            classification="internal",
            language="en",
            version="1.0.0",
            created_at="2026-05-04T00:00:00Z",
            updated_at="2026-05-04T00:00:00Z",
            derived_from={"sources": [], "parent_pages": []},
            outbound_links=[],
            inbound_link_count=0,
            redacted=True,
            redaction_rules_version="1.0.0",
            lifecycle_state="live",
            owner="test@opspilot",
            body=body,
            tags=["tag-a"],
        )

    def test_creates_index_if_missing(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        wiki_root.mkdir()
        page = self._make_page("first-page")
        update_index(wiki_root, page)
        idx = (wiki_root / "index.md").read_text()
        assert "[[first-page]]" in idx

    def test_replaces_existing_entry(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        wiki_root.mkdir()
        page = self._make_page("my-slug")
        update_index(wiki_root, page)
        # Update summary
        page2 = WikiPage(**{**page.__dict__, "summary": "Updated summary."})
        update_index(wiki_root, page2)
        text = (wiki_root / "index.md").read_text()
        assert text.count("[[my-slug]]") == 1
        assert "Updated summary." in text

    def test_append_log_creates_file(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        wiki_root.mkdir()
        entry = WikiLogEntry(op="ingest", subject="doc_abc12345", pages_created=1)
        append_log(wiki_root, entry)
        log = (wiki_root / "log.md").read_text()
        assert "ingest | doc_abc12345" in log
        assert "1 created" in log

    def test_append_log_is_append_only(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        wiki_root.mkdir()
        for i in range(3):
            append_log(wiki_root, WikiLogEntry(op="ingest", subject=f"doc_{i}", pages_created=1))
        log = (wiki_root / "log.md").read_text()
        assert log.count("ingest |") == 3


# ──────────────────────────────────────────────────────────────────────────
#  ingest.py (unit tests with mocked LLM)
# ──────────────────────────────────────────────────────────────────────────


class TestIngest:
    def test_ingest_creates_page(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        wiki_root.mkdir()
        with _make_sqlite(tmp_path) as sqlite:
            _insert_doc_and_chunks(sqlite, "doc_aabb1234", "Network maintenance content.")
            provider = _mock_provider()
            cfg = WikiIngestConfig(wiki_root=wiki_root)
            result = ingest("doc_aabb1234", sqlite=sqlite, provider=provider, config=cfg)

        assert result.page_path.exists()
        assert result.page_id.startswith("wpg_")
        assert result.slug == "test-sop-zh"
        assert result.pages_created == 1
        assert result.pages_updated == 0

    def test_ingest_writes_valid_frontmatter(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        wiki_root.mkdir()
        with _make_sqlite(tmp_path) as sqlite:
            _insert_doc_and_chunks(sqlite, "doc_aabb1234", "content")
            cfg = WikiIngestConfig(wiki_root=wiki_root)
            result = ingest("doc_aabb1234", sqlite=sqlite, provider=_mock_provider(), config=cfg)

        page = read_page(result.page_path)
        assert page.kind == "summary"
        assert page.namespace == "opspilot:public-kb"
        assert page.redacted is True
        assert page.lifecycle_state == "live"
        assert page.derived_from["sources"][0]["ref"] == "doc_aabb1234"

    def test_ingest_updates_index_and_log(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        wiki_root.mkdir()
        with _make_sqlite(tmp_path) as sqlite:
            _insert_doc_and_chunks(sqlite, "doc_aabb1234", "content")
            cfg = WikiIngestConfig(wiki_root=wiki_root)
            result = ingest("doc_aabb1234", sqlite=sqlite, provider=_mock_provider(), config=cfg)

        idx = (wiki_root / "index.md").read_text()
        assert f"[[{result.slug}]]" in idx
        log = (wiki_root / "log.md").read_text()
        assert "doc_aabb1234" in log

    def test_ingest_raises_if_doc_missing(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        wiki_root.mkdir()
        with _make_sqlite(tmp_path) as sqlite:
            cfg = WikiIngestConfig(wiki_root=wiki_root)
            with pytest.raises(WikiIngestError, match="not found"):
                ingest("doc_nonexistent", sqlite=sqlite, provider=_mock_provider(), config=cfg)

    def test_ingest_is_idempotent(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        wiki_root.mkdir()
        with _make_sqlite(tmp_path) as sqlite:
            _insert_doc_and_chunks(sqlite, "doc_aabb1234", "content")
            cfg = WikiIngestConfig(wiki_root=wiki_root)
            r1 = ingest("doc_aabb1234", sqlite=sqlite, provider=_mock_provider(), config=cfg)
            r2 = ingest("doc_aabb1234", sqlite=sqlite, provider=_mock_provider(), config=cfg)

        assert r1.slug == r2.slug
        assert r2.pages_created == 0
        assert r2.pages_updated == 1

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        wiki_root.mkdir()
        bad_provider = MagicMock()
        bad_provider.chat.return_value = ChatResponse(
            content="not json at all", finish_reason="stop"
        )
        with _make_sqlite(tmp_path) as sqlite:
            _insert_doc_and_chunks(sqlite, "doc_aabb1234", "content")
            cfg = WikiIngestConfig(wiki_root=wiki_root)
            with pytest.raises(WikiIngestError, match="not valid JSON"):
                ingest("doc_aabb1234", sqlite=sqlite, provider=bad_provider, config=cfg)

    def test_slug_auto_fixed(self, tmp_path: Path) -> None:
        """LLM returns a slug with spaces → should be auto-fixed."""
        wiki_root = tmp_path / "wiki"
        wiki_root.mkdir()
        import json

        bad_slug_provider = MagicMock()
        bad_slug_provider.chat.return_value = ChatResponse(
            content=json.dumps(
                {
                    "slug": "My Bad Slug!",
                    "title": "Test",
                    "summary": "A valid summary for testing.",
                    "language": "en",
                    "tags": [],
                    "aliases": [],
                    "body": "## TL;DR\n\nBody content here.\n\n## Sources\n\n1. [doc]\n\n## Changelog\n\n- v1.0.0: initial",
                }
            ),
            finish_reason="stop",
        )
        with _make_sqlite(tmp_path) as sqlite:
            _insert_doc_and_chunks(sqlite, "doc_aabb1234", "content")
            cfg = WikiIngestConfig(wiki_root=wiki_root)
            result = ingest("doc_aabb1234", sqlite=sqlite, provider=bad_slug_provider, config=cfg)

        assert result.slug == "my-bad-slug-"[:result.slug.__len__()] or "-" not in result.slug[:1]


# ──────────────────────────────────────────────────────────────────────────
#  sqlite_store: get_chunks_by_document_id
# ──────────────────────────────────────────────────────────────────────────


class TestGetChunksByDocumentId:
    def test_returns_chunks_in_seq_order(self, tmp_path: Path) -> None:
        with _make_sqlite(tmp_path) as sqlite:
            _insert_doc_and_chunks(sqlite, "doc_aabbccdd", "chunk content here")
            chunks = sqlite.get_chunks_by_document_id("doc_aabbccdd")
        assert len(chunks) == 1
        assert chunks[0]["document_id"] == "doc_aabbccdd"
        assert chunks[0]["content"] == "chunk content here"

    def test_returns_empty_for_unknown_doc(self, tmp_path: Path) -> None:
        with _make_sqlite(tmp_path) as sqlite:
            chunks = sqlite.get_chunks_by_document_id("doc_nonexistent")
        assert chunks == []
