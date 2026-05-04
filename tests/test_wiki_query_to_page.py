"""Tests for wiki query→page engine (PR-24)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from opspilot.wiki.query_to_page import (
    QueryToPageConfig,
    _build_user_message,
    _parse_kb_hits,
    _qualify,
    _read_trace,
    query_to_page,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_trace_events(*events: dict) -> str:
    """Serialise a list of event dicts to newline-joined JSONL."""
    return "\n".join(json.dumps(e) for e in events) + "\n"


def _make_session(
    tmp_path: Path,
    *,
    session_id: str = "sess_abc00001",
    status: str = "archived",
    sensitivity: str = "internal",
    trace_events: list[dict] | None = None,
) -> tuple[Path, MagicMock]:
    """Create a minimal fake session directory and mock SessionManager."""
    sess_dir = tmp_path / "sessions" / session_id
    sess_dir.mkdir(parents=True)

    if trace_events is not None:
        (sess_dir / "trace.jsonl").write_text(_make_trace_events(*trace_events), encoding="utf-8")

    mock_sess = MagicMock()
    mock_sess.status = status
    mock_sess.sensitivity = sensitivity

    sm = MagicMock()
    sm.load.return_value = mock_sess
    sm.session_dir.return_value = sess_dir
    sm.list.return_value = [session_id]

    return sess_dir, sm


# ── _parse_kb_hits ─────────────────────────────────────────────────────────────


class TestParseKbHits:
    def test_inline_json(self) -> None:
        payload = json.dumps({"hits": [{"chunk_id": "chk_00000001", "content": "foo"}]})
        hits = _parse_kb_hits(payload, Path("."))
        assert len(hits) == 1
        assert hits[0]["chunk_id"] == "chk_00000001"

    def test_empty_string(self) -> None:
        assert _parse_kb_hits("", Path(".")) == []

    def test_invalid_json_returns_empty(self) -> None:
        assert _parse_kb_hits("not json", Path(".")) == []

    def test_file_path(self, tmp_path: Path) -> None:
        f = tmp_path / "response.json"
        f.write_text(json.dumps({"hits": [{"chunk_id": "chk_aabb0001"}]}), encoding="utf-8")
        hits = _parse_kb_hits(str(f), tmp_path)
        assert hits[0]["chunk_id"] == "chk_aabb0001"


# ── _read_trace ────────────────────────────────────────────────────────────────


class TestReadTrace:
    def test_empty_trace_returns_defaults(self, tmp_path: Path) -> None:
        d = _read_trace(tmp_path / "nonexistent.jsonl")
        assert d.final_response == ""
        assert d.kb_search_count == 0
        assert not d.has_user_accept

    def test_counts_kb_search_tool_calls(self, tmp_path: Path) -> None:
        f = tmp_path / "trace.jsonl"
        f.write_text(
            _make_trace_events(
                {"type": "tool_call", "tool": "kb_search"},
                {"type": "tool_call", "tool": "kb_search"},
                {"type": "response", "content": "hello", "finish_reason": "stop"},
            ),
            encoding="utf-8",
        )
        d = _read_trace(f)
        assert d.kb_search_count == 2
        assert d.final_response == "hello"

    def test_kb_dot_search_counts(self, tmp_path: Path) -> None:
        f = tmp_path / "trace.jsonl"
        f.write_text(
            _make_trace_events({"type": "tool_call", "tool": "kb.search"}),
            encoding="utf-8",
        )
        assert _read_trace(f).kb_search_count == 1

    def test_user_accept_detected(self, tmp_path: Path) -> None:
        f = tmp_path / "trace.jsonl"
        f.write_text(
            _make_trace_events(
                {"type": "user_action", "action": "accept"},
                {"type": "response", "content": "ok", "finish_reason": "stop"},
            ),
            encoding="utf-8",
        )
        d = _read_trace(f)
        assert d.has_user_accept
        assert d.final_response == "ok"

    def test_kb_hits_deduplicated(self, tmp_path: Path) -> None:
        hits_json = json.dumps({"hits": [
            {"chunk_id": "chk_11111111", "content": "A"},
            {"chunk_id": "chk_22222222", "content": "B"},
        ]})
        f = tmp_path / "trace.jsonl"
        f.write_text(
            _make_trace_events(
                {"type": "tool_call", "tool": "kb_search"},
                {"type": "tool_result", "tool": "kb_search", "stdout_ref": hits_json},
                # second call returns same chunk → should be deduplicated
                {"type": "tool_call", "tool": "kb_search"},
                {"type": "tool_result", "tool": "kb_search", "stdout_ref": hits_json},
            ),
            encoding="utf-8",
        )
        d = _read_trace(f)
        assert d.kb_search_count == 2
        assert len(d.kb_hits) == 2  # deduped


# ── _qualify ───────────────────────────────────────────────────────────────────


class TestQualify:
    def _cfg(self, tmp_path: Path) -> QueryToPageConfig:
        return QueryToPageConfig(wiki_root=tmp_path / "wiki", min_kb_searches=2)

    def test_not_archived_skipped(self, tmp_path: Path) -> None:
        _, sm = _make_session(tmp_path, status="active")
        trigger, reason = _qualify("sess_abc00001", sm, self._cfg(tmp_path))
        assert trigger == ""
        assert "archived" in reason

    def test_restricted_blocked(self, tmp_path: Path) -> None:
        _, sm = _make_session(tmp_path, sensitivity="restricted")
        trigger, reason = _qualify("sess_abc00001", sm, self._cfg(tmp_path))
        assert trigger == ""
        assert "restricted" in reason

    def test_qualifies_by_kb_search_count(self, tmp_path: Path) -> None:
        events = [
            {"type": "tool_call", "tool": "kb_search"},
            {"type": "tool_call", "tool": "kb_search"},
            {"type": "response", "content": "answer", "finish_reason": "stop"},
        ]
        _, sm = _make_session(tmp_path, trace_events=events)
        trigger, reason = _qualify("sess_abc00001", sm, self._cfg(tmp_path))
        assert trigger == "kb_search_count"
        assert reason == ""

    def test_qualifies_by_user_accept(self, tmp_path: Path) -> None:
        events = [
            {"type": "response", "content": "answer", "finish_reason": "stop"},
            {"type": "user_action", "action": "accept"},
        ]
        _, sm = _make_session(tmp_path, trace_events=events)
        trigger, reason = _qualify("sess_abc00001", sm, self._cfg(tmp_path))
        assert trigger == "user_accept"
        assert reason == ""

    def test_no_trigger_skipped(self, tmp_path: Path) -> None:
        events = [
            {"type": "tool_call", "tool": "kb_search"},  # only 1, need 2
            {"type": "response", "content": "answer", "finish_reason": "stop"},
        ]
        _, sm = _make_session(tmp_path, trace_events=events)
        trigger, reason = _qualify("sess_abc00001", sm, self._cfg(tmp_path))
        assert trigger == ""
        assert "does not qualify" in reason

    def test_no_response_content_skipped(self, tmp_path: Path) -> None:
        events = [
            {"type": "tool_call", "tool": "kb_search"},
            {"type": "tool_call", "tool": "kb_search"},
            # no response event
        ]
        _, sm = _make_session(tmp_path, trace_events=events)
        trigger, reason = _qualify("sess_abc00001", sm, self._cfg(tmp_path))
        assert trigger == ""
        assert "response" in reason


# ── _build_user_message ────────────────────────────────────────────────────────


class TestBuildUserMessage:
    def test_includes_session_id(self) -> None:
        msg = _build_user_message("sess_abc00001", "my response", [])
        assert "sess_abc00001" in msg

    def test_includes_response(self) -> None:
        msg = _build_user_message("s1", "the final answer is 42", [])
        assert "the final answer is 42" in msg

    def test_includes_kb_hits(self) -> None:
        hits = [{"chunk_id": "chk_aaaa0001", "document_id": "doc_aaaa0001", "content": "hi"}]
        msg = _build_user_message("s1", "resp", hits)
        assert "chk_aaaa0001" in msg


# ── query_to_page integration (mocked LLM) ────────────────────────────────────


class TestQueryToPage:
    def _cfg(self, wiki_root: Path) -> QueryToPageConfig:
        return QueryToPageConfig(wiki_root=wiki_root, min_kb_searches=2)

    def _mock_provider(self, slug: str = "synthesis-vpn-auth-2026") -> MagicMock:
        proposal = {
            "slug": slug,
            "title": "VPN Auth Synthesis",
            "summary": "Synthesis of VPN auth failure session.",
            "language": "en",
            "tags": ["vpn", "auth"],
            "aliases": [],
            "body": (
                "## Thesis\nVPN auth failures are server-side.\n"
                "## Evidence\n1. Chunk data.\n"
                "## Counter-evidence\nNone.\n"
                "## Gaps\nNone.\n"
                "## Cross-links\nNone.\n"
                "## Sources\n1. chk_aaaa0001.\n"
                "## Changelog\n- v1.0.0 (2026-05-04): initial; from session <session_id>"
            ),
        }
        provider = MagicMock()
        provider.chat.return_value.content = json.dumps(proposal)
        return provider

    def test_creates_page_for_qualifying_session(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        events = [
            {"type": "tool_call", "tool": "kb_search"},
            {"type": "tool_call", "tool": "kb_search"},
            {"type": "response", "content": "VPN auth fails server-side.", "finish_reason": "stop"},
        ]
        _, sm = _make_session(tmp_path, trace_events=events)

        result = query_to_page(
            "sess_abc00001",
            session_manager=sm,
            provider=self._mock_provider(),
            config=self._cfg(wiki_root),
        )

        assert not result.skipped
        assert result.slug == "synthesis-vpn-auth-2026"
        assert result.page_path.exists()
        assert result.trigger == "kb_search_count"

    def test_skips_non_qualifying_session(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        events = [{"type": "response", "content": "hi", "finish_reason": "stop"}]
        _, sm = _make_session(tmp_path, trace_events=events)

        result = query_to_page(
            "sess_abc00001",
            session_manager=sm,
            provider=self._mock_provider(),
            config=self._cfg(wiki_root),
        )

        assert result.skipped
        assert "does not qualify" in result.skip_reason

    def test_skips_when_slug_already_exists(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        existing = wiki_root / "pages" / "synthesis" / "synthesis-vpn-auth-2026.md"
        existing.parent.mkdir(parents=True)
        existing.write_text("---\nexisting: true\n---\nbody", encoding="utf-8")

        events = [
            {"type": "tool_call", "tool": "kb_search"},
            {"type": "tool_call", "tool": "kb_search"},
            {"type": "response", "content": "answer", "finish_reason": "stop"},
        ]
        _, sm = _make_session(tmp_path, trace_events=events)

        result = query_to_page(
            "sess_abc00001",
            session_manager=sm,
            provider=self._mock_provider(),
            config=self._cfg(wiki_root),
        )

        assert result.skipped
        assert "already exists" in result.skip_reason

    def test_page_written_as_draft(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        events = [
            {"type": "tool_call", "tool": "kb_search"},
            {"type": "tool_call", "tool": "kb_search"},
            {"type": "response", "content": "answer", "finish_reason": "stop"},
        ]
        _, sm = _make_session(tmp_path, trace_events=events)

        result = query_to_page(
            "sess_abc00001",
            session_manager=sm,
            provider=self._mock_provider(),
            config=self._cfg(wiki_root),
        )

        assert not result.skipped
        content = result.page_path.read_text(encoding="utf-8")
        assert "lifecycle_state: draft" in content

    def test_session_id_substituted_in_changelog(self, tmp_path: Path) -> None:
        wiki_root = tmp_path / "wiki"
        events = [
            {"type": "tool_call", "tool": "kb_search"},
            {"type": "tool_call", "tool": "kb_search"},
            {"type": "response", "content": "answer", "finish_reason": "stop"},
        ]
        _, sm = _make_session(tmp_path, trace_events=events)

        result = query_to_page(
            "sess_abc00001",
            session_manager=sm,
            provider=self._mock_provider(),
            config=self._cfg(wiki_root),
        )

        content = result.page_path.read_text(encoding="utf-8")
        assert "sess_abc00001" in content
        assert "<session_id>" not in content
