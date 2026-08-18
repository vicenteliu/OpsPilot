"""Memory reaches an answer on its own path, not through hybrid search.

The decisive reason is downstream: **conflict between Memory and the KB is
detected when an answer is composed**, and that needs the assistant to tell
"this came from Memory" from "this came from the knowledge base". A shared
ranking erases the distinction, and with it the only chance to notice that a
recorded constraint and an ingested document disagree.

So the block is a labelled section of the system prompt, and it carries the
instruction to *name both* on a contradiction rather than silently prefer one.
"""

from __future__ import annotations

import sqlite3

import pytest

from opspilot.memory import MemoryStore, memory_block, render_entry


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore(sqlite3.connect(":memory:"))


def _admit(store: MemoryStore, statement: str, **kw):
    kw.setdefault("reason", "finance runs its batch then")
    kw.setdefault("actor", "user:alice")
    return store.admit(statement=statement, **kw)


class TestBlock:
    def test_empty_store_injects_nothing(self, store: MemoryStore) -> None:
        assert memory_block(store) == ""

    def test_global_entries_apply_without_an_anchor(self, store: MemoryStore) -> None:
        _admit(store, "No production change on a Friday")
        block = memory_block(store)
        assert "No production change on a Friday" in block
        assert "applies at everywhere" in block

    def test_an_unanchored_turn_does_not_see_another_site(self, store: MemoryStore) -> None:
        """Not a degradation — a constraint about another site must not steer this answer."""
        _admit(store, "Vendor manages the firewall here", scope="site-b")
        assert memory_block(store) == ""
        assert "Vendor manages" in memory_block(store, scope="site-b")

    def test_the_block_says_what_to_do_on_a_contradiction(self, store: MemoryStore) -> None:
        _admit(store, "anything")
        block = memory_block(store)
        assert "contradicts" in block and "name both" in block

    def test_the_block_marks_itself_as_not_the_knowledge_base(self, store: MemoryStore) -> None:
        _admit(store, "anything")
        assert "not** knowledge-base documents" in memory_block(store)


class TestEntryLine:
    def test_a_line_carries_where_and_why_and_the_id(self, store: MemoryStore) -> None:
        entry = _admit(store, "No ESXi restarts Tuesday evening", scope="dc-1")
        line = render_entry(entry, now="2026-08-18T00:00:00Z")
        assert entry.id in line
        assert "applies at dc-1" in line
        assert "finance runs its batch then" in line

    def test_an_overdue_entry_is_labelled_and_still_present(self, store: MemoryStore) -> None:
        """Hard expiry was rejected: it drops a still-correct constraint at an unknown moment."""
        entry = _admit(store, "still true", review_after="2020-01-01T00:00:00Z")
        line = render_entry(entry, now="2026-08-18T00:00:00Z")
        assert "still true" in line
        assert "due for review" in line

    def test_a_current_entry_carries_no_warning(self, store: MemoryStore) -> None:
        entry = _admit(store, "fresh", review_after="2099-01-01T00:00:00Z")
        assert "due for review" not in render_entry(entry, now="2026-08-18T00:00:00Z")


class TestChatAgentWiring:
    def test_the_prefix_is_empty_without_a_store(self) -> None:
        from opspilot.orchestrator.chat_agent import _memory_prefix

        assert _memory_prefix(object(), asset_id=None, scope=None) == ""

    def test_the_prefix_renders_from_state(self, store: MemoryStore) -> None:
        from opspilot.orchestrator.chat_agent import _memory_prefix

        _admit(store, "No production change on a Friday")

        class _State:
            memory = store

        assert "No production change on a Friday" in _memory_prefix(
            _State(), asset_id=None, scope=None
        )
