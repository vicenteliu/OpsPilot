"""Escalating a Consultation into a Session (ADR-0032).

A Consultation reads. To act on what it found it is escalated, and a Session is
what runs — carrying **a Work item description and nothing else**.

Not the transcript, and the reason is the harness. A **Fixture** is a frozen,
versioned input package, and a Session's replayability rests on its input having
edges; an arbitrarily long conversation — small talk, dead ends, pasted logs — is
not freezable, and the harness is the gate a Stage is declared complete against.

Nothing is lost: the Consultation records ``→ session_id``, the Session's trace
records ``← consultation_id``, and escalating **pins** the Consultation, because
the Session's trace is permanent and its back-reference must not point at
something the sweep deleted.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from opspilot.consultation import ConsultationStore, EscalationError, escalate


class _Result:
    session_id = "sess_01ESCALATED"
    artifact_id = "art_abc"
    schema_valid = True


class _Trace:
    def __init__(self, sink: list[Any]) -> None:
        self.sink = sink

    def write(self, event: Any) -> None:
        self.sink.append(event)

    def __enter__(self) -> _Trace:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _Manager:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def trace(self, session_id: str) -> _Trace:
        return _Trace(self.events)


@pytest.fixture
def store(tmp_path: Path) -> ConsultationStore:
    return ConsultationStore(sqlite3.connect(tmp_path / "a.db"))


def _run(store: ConsultationStore, consultation_id: str, monkeypatch, **over: Any) -> Any:
    seen: dict[str, Any] = {}

    def _fake_run(request: Any, **kwargs: Any) -> _Result:
        seen["input"] = json.loads(Path(request.input_path).read_text(encoding="utf-8"))
        seen["owner"] = request.owner
        return _Result()

    monkeypatch.setattr("opspilot.consultation.escalation.run_ticket_summary", _fake_run)
    manager = _Manager()
    kwargs: dict[str, Any] = {
        "description": "Three VMs on esxi-07 froze; storage latency suspected.",
        "actor": "user:alice",
        "session_manager": manager,
        "playbook": object(),
        "provider": object(),
        "redactor": object(),
        "embed_fn": object(),
        "sqlite_store": object(),
        "lance_store": object(),
    }
    kwargs.update(over)
    result = escalate(store, consultation_id, **kwargs)
    return result, seen, manager


def _consultation(store: ConsultationStore) -> str:
    con = store.start(author="alice", title="esxi-07 frozen VMs")
    store.append(con.id, role="user", content="Three VMs froze, and here is a 4000-line log dump")
    store.append(con.id, role="assistant", content="Check the storage paths first")
    return con.id


class TestWhatTravels:
    def test_only_the_description_reaches_the_session(self, store, monkeypatch) -> None:
        """The transcript stays behind — a Fixture has to be freezable."""
        cid = _consultation(store)
        _, seen, _ = _run(store, cid, monkeypatch)
        blob = json.dumps(seen["input"])
        assert "Three VMs on esxi-07 froze" in blob
        assert "4000-line log dump" not in blob
        assert "Check the storage paths first" not in blob

    def test_the_escalating_person_owns_the_session(self, store, monkeypatch) -> None:
        cid = _consultation(store)
        _, seen, _ = _run(store, cid, monkeypatch)
        assert seen["owner"] == "user:alice"

    def test_an_empty_description_is_refused(self, store, monkeypatch) -> None:
        cid = _consultation(store)
        with pytest.raises(EscalationError, match="description is required"):
            _run(store, cid, monkeypatch, description="   ")

    def test_an_unowned_escalation_is_refused(self, store, monkeypatch) -> None:
        cid = _consultation(store)
        with pytest.raises(EscalationError, match="actor is required"):
            _run(store, cid, monkeypatch, actor="")


class TestTheLink:
    def test_both_directions_are_recorded(self, store, monkeypatch) -> None:
        cid = _consultation(store)
        _, _, manager = _run(store, cid, monkeypatch)
        after = store.get(cid)
        assert after is not None and after.session_id == "sess_01ESCALATED"
        back = [e for e in manager.events if e.payload.get("event") == "escalated_from"]
        assert back and back[0].payload["details"]["consultation_id"] == cid
        assert back[0].payload["details"]["escalated_by"] == "user:alice"

    def test_escalating_pins_the_consultation(self, store, monkeypatch) -> None:
        """The Session's trace is permanent; its back-reference must not dangle."""
        cid = _consultation(store)
        _run(store, cid, monkeypatch)
        after = store.get(cid)
        assert after is not None and after.is_pinned and after.pinned_reason == "escalated"
        assert store.purge(now="2030-01-01T00:00:00Z") == []

    def test_escalating_twice_is_refused(self, store, monkeypatch) -> None:
        cid = _consultation(store)
        _run(store, cid, monkeypatch)
        with pytest.raises(EscalationError, match="already escalated"):
            _run(store, cid, monkeypatch)

    def test_an_unknown_consultation_raises(self, store, monkeypatch) -> None:
        with pytest.raises(KeyError):
            _run(store, "con_deadbeef", monkeypatch)
