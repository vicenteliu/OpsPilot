"""Tests for ``opspilot.session`` (PR-6).

Covers:
* :class:`Session` / :class:`TraceEvent` round-trip via JSON schemas.
* :class:`ArtifactStore` content-addressed put/get + dedup.
* :class:`AuditLog` append-only behaviour.
* :class:`TraceWriter` auto seq + ts + per-row schema validation.
* :class:`SessionManager` full lifecycle, including the **PR-6 exit
  criterion** from ``docs/zh/design/IMPLEMENTATION_STAGE_1.md §758``: 10 trace events
  + an artifact + an audit log; ``trace.jsonl`` validates row-by-row.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opspilot.errors import SchemaError
from opspilot.schemas import validate as schema_validate
from opspilot.session import (
    LIFECYCLE_TRANSITIONS,
    ArtifactStore,
    AuditLog,
    IllegalTransition,
    Model,
    Playbook,
    Session,
    SessionError,
    SessionManager,
    TraceEvent,
)

# ── Fixtures ──────────────────────────────────────────────────────────


def _model() -> Model:
    return Model(
        provider_id="ollama-local",
        kind="ollama",
        name="gemma4:e4b",
        version="2026-04",
        params={"temperature": 0.2, "max_tokens": 256},
    )


def _playbook() -> Playbook:
    return Playbook(id="pb_ticket_summary_zh", version="1.2.0")


@pytest.fixture
def manager(tmp_path: Path) -> SessionManager:
    return SessionManager(home=tmp_path)


# ── types.Session round-trip ──────────────────────────────────────────


def test_session_roundtrip_through_schema(manager: SessionManager) -> None:
    sess = manager.create(
        owner="vicente@example.com",
        playbook=_playbook(),
        model=_model(),
    )
    d = sess.to_dict()
    schema_validate("session", d)  # should not raise

    sess2 = Session.from_dict(d)
    assert sess2.id == sess.id
    assert sess2.model.provider_id == "ollama-local"


def test_session_id_format(manager: SessionManager) -> None:
    sess = manager.create(owner="x@y", playbook=_playbook(), model=_model())
    # ULID is 26 chars from Crockford alphabet.
    assert sess.id.startswith("sess_")
    assert len(sess.id) == len("sess_") + 26


def test_initial_status_is_draft(manager: SessionManager) -> None:
    sess = manager.create(owner="x@y", playbook=_playbook(), model=_model())
    assert sess.status == "draft"


# ── Lifecycle state machine ──────────────────────────────────────────


def test_legal_transition_draft_to_active(manager: SessionManager) -> None:
    sess = manager.create(owner="x@y", playbook=_playbook(), model=_model())
    sess2 = manager.transition(sess.id, "active")
    assert sess2.status == "active"
    assert manager.load(sess.id).status == "active"


def test_active_to_archived(manager: SessionManager) -> None:
    sess = manager.create(owner="x@y", playbook=_playbook(), model=_model())
    manager.transition(sess.id, "active")
    manager.transition(sess.id, "archived")
    assert manager.load(sess.id).status == "archived"


def test_illegal_transition_raises(manager: SessionManager) -> None:
    sess = manager.create(owner="x@y", playbook=_playbook(), model=_model())
    # draft → archived is not allowed (must go via active first).
    with pytest.raises(IllegalTransition, match="cannot transition"):
        manager.transition(sess.id, "archived")


def test_purged_is_terminal() -> None:
    """purged has no outgoing edges per spec §1."""
    assert LIFECYCLE_TRANSITIONS["purged"] == frozenset()


def test_aborted_only_to_archived() -> None:
    assert LIFECYCLE_TRANSITIONS["aborted"] == frozenset({"archived"})


# ── ArtifactStore ────────────────────────────────────────────────────


def test_artifact_put_returns_meta_with_sha8_id(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    meta = store.put(b"hello", kind="text/plain", source="tool:test")
    assert meta.artifact_id.startswith("art_")
    assert len(meta.artifact_id) == len("art_") + 16
    assert meta.size_bytes == 5
    assert meta.encoding == "binary"


def test_artifact_dedup_same_content_same_id(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    a = store.put(b"hello", kind="text/plain", source="tool:test")
    b = store.put(b"hello", kind="text/plain", source="tool:test")
    assert a.artifact_id == b.artifact_id
    # First meta wins (idempotent re-put).
    assert a.created_at == b.created_at


def test_artifact_text_round_trip(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    text = "中文 + english\nline2"
    meta = store.put(text, kind="text/plain", source="tool:test")
    assert meta.encoding == "utf-8"
    assert store.read_text(meta.artifact_id) == text


def test_artifact_read_text_on_binary_raises(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    meta = store.put(b"\x00\x01\x02", kind="application/octet-stream", source="tool:test")
    with pytest.raises(SessionError, match="binary"):
        store.read_text(meta.artifact_id)


def test_artifact_get_meta_missing(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(SessionError, match="not found"):
        store.get_meta("art_0000000000000000")


def test_artifact_list_ids(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.put(b"one", kind="text/plain", source="x")
    store.put(b"two", kind="text/plain", source="x")
    ids = store.list_ids()
    assert len(ids) == 2
    assert all(i.startswith("art_") for i in ids)


# ── AuditLog ─────────────────────────────────────────────────────────


def test_audit_append_and_read(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    log.write(actor="user:alice", action="create", target="sess_X", details={"status": "draft"})
    log.write(
        actor="user:alice",
        action="transition",
        target="sess_X",
        details={"from": "draft", "to": "active"},
    )
    rows = log.read_all()
    assert len(rows) == 2
    assert rows[0].action == "create"
    assert rows[1].details == {"from": "draft", "to": "active"}


def test_audit_empty_when_missing(tmp_path: Path) -> None:
    assert AuditLog(tmp_path).read_all() == []


def test_audit_write_via_manager(manager: SessionManager) -> None:
    sess = manager.create(owner="x@y", playbook=_playbook(), model=_model())
    manager.transition(sess.id, "active")
    rows = manager.audit(sess.id).read_all()
    assert len(rows) == 2  # create + transition
    assert rows[0].action == "create"
    assert rows[1].action == "transition"


# ── TraceWriter ──────────────────────────────────────────────────────


def test_trace_writer_auto_increments_seq(manager: SessionManager) -> None:
    sess = manager.create(owner="x@y", playbook=_playbook(), model=_model())
    manager.transition(sess.id, "active")
    with manager.trace(sess.id) as tw:
        tw.write(TraceEvent.prompt(role="user", content="a"))
        tw.write(TraceEvent.response(content="b", finish_reason="stop"))
        tw.write(TraceEvent.system(event="state_change"))
    lines = (manager.session_dir(sess.id) / "trace.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines]
    assert [r["seq"] for r in rows] == [0, 1, 2]


def test_trace_writer_resumes_seq_after_reopen(manager: SessionManager) -> None:
    sess = manager.create(owner="x@y", playbook=_playbook(), model=_model())
    manager.transition(sess.id, "active")
    with manager.trace(sess.id) as tw:
        tw.write(TraceEvent.prompt(role="user", content="x"))
    with manager.trace(sess.id) as tw2:
        assert tw2.next_seq == 1
        tw2.write(TraceEvent.prompt(role="user", content="y"))
    rows = [
        json.loads(line)
        for line in (manager.session_dir(sess.id) / "trace.jsonl").read_text().splitlines()
    ]
    assert [r["seq"] for r in rows] == [0, 1]


def test_trace_writer_validates_each_row(manager: SessionManager) -> None:
    """Manually-built bad payload should be rejected by schema_validate."""
    sess = manager.create(owner="x@y", playbook=_playbook(), model=_model())
    manager.transition(sess.id, "active")
    bad = TraceEvent(type="prompt", payload={"role": "user"})  # missing content
    with manager.trace(sess.id) as tw, pytest.raises(SchemaError):
        tw.write(bad)


def test_trace_writer_outside_context_raises(manager: SessionManager) -> None:
    sess = manager.create(owner="x@y", playbook=_playbook(), model=_model())
    manager.transition(sess.id, "active")
    tw = manager.trace(sess.id)
    with pytest.raises(SessionError, match="not open"):
        tw.write(TraceEvent.prompt(role="user", content="x"))


def test_trace_writer_actor_propagated(manager: SessionManager) -> None:
    sess = manager.create(owner="x@y", playbook=_playbook(), model=_model())
    manager.transition(sess.id, "active")
    with manager.trace(sess.id) as tw:
        tw.write(TraceEvent.prompt(role="user", content="hi", actor="user:vicente"))
    rows = [
        json.loads(line)
        for line in (manager.session_dir(sess.id) / "trace.jsonl").read_text().splitlines()
    ]
    assert rows[0]["actor"] == "user:vicente"


# ── SessionManager misc ──────────────────────────────────────────────


def test_load_unknown_session_raises(manager: SessionManager) -> None:
    with pytest.raises(SessionError, match="not found"):
        manager.load("sess_01KZZZZZZZZZZZZZZZZZZZZZZZZZ")


def test_list_returns_all_session_ids(manager: SessionManager) -> None:
    a = manager.create(owner="x", playbook=_playbook(), model=_model())
    b = manager.create(owner="x", playbook=_playbook(), model=_model())
    ids = manager.list()
    assert {a.id, b.id} <= set(ids)


def test_meta_yaml_validates_against_schema(manager: SessionManager) -> None:
    """The on-disk meta.yaml must round-trip back through the validator."""
    sess = manager.create(owner="x@y", playbook=_playbook(), model=_model())
    sess2 = manager.load(sess.id)
    assert sess2.owner == "x@y"
    assert sess2.id == sess.id


# ── Exit criterion ───────────────────────────────────────────────────


def test_exit_criterion_full_session_lifecycle(manager: SessionManager) -> None:
    """PR-6 exit criterion (docs/zh/design/IMPLEMENTATION_STAGE_1.md §758).

    create session + write 10 trace events + write artifact + audit log;
    the produced trace.jsonl validates against trace-event.schema.json.
    """
    sess = manager.create(
        owner="vicente@example.com",
        playbook=_playbook(),
        model=_model(),
    )
    manager.transition(sess.id, "active")

    # 10 events spanning the full type union.
    with manager.trace(sess.id) as tw:
        tw.write(TraceEvent.prompt(role="system", content="you are an ops bot"))
        tw.write(TraceEvent.prompt(role="user", content="vpn 认证失败 怎么排查"))
        tw.write(
            TraceEvent.tool_call(
                tool="kb.search", args={"q": "VPN 认证失败"}, action_id=f"act_{'A' * 26}"
            )
        )
        tw.write(
            TraceEvent.tool_result(
                tool="kb.search", status="ok", action_id=f"act_{'A' * 26}", artifact_ids=[]
            )
        )
        tw.write(TraceEvent.redaction(pattern="rule.email", count=1))
        tw.write(
            TraceEvent.response(
                content="排查步骤一: ...",
                finish_reason="stop",
                usage={"input_tokens": 12, "output_tokens": 50},
            )
        )
        tw.write(TraceEvent.user_action(action="approve", target="seq:5"))
        tw.write(TraceEvent.system(event="state_change", details={"to": "checkpoint"}))
        tw.write(TraceEvent.tool_call(tool="bash", args={"cmd": "echo done"}))
        tw.write(TraceEvent.tool_result(tool="bash", status="ok", exit_code=0, duration_ms=12))

    # Write an artifact.
    art = manager.artifacts(sess.id).put("stdout: done\n", kind="text/plain", source="tool:bash")

    manager.transition(sess.id, "archived")

    # ── Verify ──────────────────────────────────────────────────────

    sdir = manager.session_dir(sess.id)
    trace_path = sdir / "trace.jsonl"
    audit_path = sdir / "audit.log"

    # All 10 trace lines schema-valid.
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 10
    for line in lines:
        schema_validate("trace-event", json.loads(line))

    # Artifact bodies + sidecars on disk.
    assert manager.artifacts(sess.id).exists(art.artifact_id)
    body_paths = list((sdir / "artifacts").glob(f"{art.artifact_id}.*"))
    # 2 files: body + .meta.yaml
    assert len(body_paths) == 2

    # Audit covers create + 2 transitions = 3 rows.
    audit_rows = audit_path.read_text(encoding="utf-8").splitlines()
    assert len(audit_rows) == 3
    actions = [json.loads(r)["action"] for r in audit_rows]
    assert actions == ["create", "transition", "transition"]
