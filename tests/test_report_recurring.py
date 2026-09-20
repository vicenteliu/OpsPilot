"""``opspilot report recurring`` — the rollup over archived incident summaries (#220).

* Only archived sessions in the period count; aborted runs and runs outside
  the window are left out.
* The cause class comes from the artifact; an artifact without one rolls up
  as ``unclassified``, sorted last.
* Pages are counted by citation ``source_path``; the fix per class is fixed
  text.
* The CLI renders md and json and honours ``--since`` / ``--out``.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opspilot.cli import app
from opspilot.report import UNCLASSIFIED, build_recurring_report
from opspilot.session import Model, Playbook, SessionManager


def _summary(ref: str, *, cause: str | None, severity: str = "P3", page: str = "kb/vpn.md") -> str:
    d = {
        "schema_version": "incident_summary_v1",
        "work_item_ref": ref,
        "work_item_type": "incident",
        "summary": "s",
        "symptoms": ["x"],
        "scope": "single_user",
        "tried_steps": [],
        "missing_fields": [],
        "tasks": [
            {"ref": "task-1", "action": "a", "rationale": "r", "tier": "L1", "citations": ["kb-1"]},
            {"ref": "task-2", "action": "a", "rationale": "r", "tier": "L1"},
            {"ref": "task-3", "action": "a", "rationale": "r", "tier": "L2"},
        ],
        "severity_suggested": severity,
        "citations": [
            {
                "id": "kb-1",
                "chunk_id": "chk_abcd1234",
                "document_id": "doc_abcd1234",
                "source_path": page,
            }
        ],
    }
    if cause is not None:
        d["cause_class"] = cause
    return json.dumps(d)


def _run(
    sm: SessionManager, ref: str, *, cause: str | None, status: str = "archived", **kw: str
) -> str:
    sess = sm.create(
        owner="u@example.com",
        playbook=Playbook(id="pb_ticket_summary_en", version="1.0.0"),
        model=Model(provider_id="anthropic", kind="anthropic", name="m", version="1"),
    )
    sm.artifacts(sess.id).put(
        _summary(ref, cause=cause, **kw), kind="application/json", source="model:assistant"
    )
    sm.transition(sess.id, "active")
    if status == "archived":
        sm.transition(sess.id, "archived")
    elif status == "aborted":
        sm.transition(sess.id, "aborted")
    return sess.id


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPSPILOT_HOME", str(tmp_path))
    return tmp_path


def test_rollup_groups_by_cause_class_and_leaves_out_unfinished_runs(home: Path) -> None:
    sm = SessionManager(home=home)
    _run(sm, "T-1", cause="user_error", page="kb/vpn.md")
    _run(sm, "T-2", cause="user_error", page="kb/vpn.md", severity="P2")
    _run(sm, "T-3", cause="server_side", page="kb/dns.md")
    _run(sm, "T-4", cause=None)  # predates cause_class
    _run(sm, "T-5", cause="user_error", status="aborted")  # never finished

    report = build_recurring_report(sm)

    assert report.sessions_seen == 4
    assert report.incidents == 4
    assert [r.cause_class for r in report.rows] == ["user_error", "server_side", UNCLASSIFIED]
    top = report.rows[0]
    assert top.count == 2 and top.share == 0.5
    assert top.severities == {"P3": 1, "P2": 1}
    assert top.top_pages == [("kb/vpn.md", 2)]
    assert top.work_item_refs == ["T-1", "T-2"]
    assert "cited page" in top.recommended_fix
    assert report.rows[-1].recommended_fix.startswith("Runs from before cause_class")


def test_period_bounds_use_session_created_at(home: Path) -> None:
    sm = SessionManager(home=home)
    sid = _run(sm, "T-old", cause="unknown")
    # Age the session by rewriting its meta — created_at is what the report reads.
    meta = sm.session_dir(sid) / "meta.yaml"
    old = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    meta.write_text(meta.read_text().replace(sm.load(sid).created_at, old))
    _run(sm, "T-new", cause="unknown")

    since = datetime.now(UTC) - timedelta(days=30)
    assert build_recurring_report(sm, since=since).incidents == 1
    assert build_recurring_report(sm).incidents == 2


def test_unknown_cause_value_rolls_up_as_unclassified(home: Path) -> None:
    sm = SessionManager(home=home)
    _run(sm, "T-1", cause="user-error")  # not a member of the enum
    report = build_recurring_report(sm)
    assert [r.cause_class for r in report.rows] == [UNCLASSIFIED]


def test_empty_period_renders_a_sentence_not_a_table(home: Path) -> None:
    md = build_recurring_report(SessionManager(home=home)).to_markdown()
    assert "No archived incident summaries" in md
    assert "|" not in md


def test_cli_renders_markdown_and_json(home: Path) -> None:
    sm = SessionManager(home=home)
    _run(sm, "T-1", cause="process_or_kb_gap", page="kb/onboarding.md")
    runner = CliRunner()

    md = runner.invoke(app, ["report", "recurring", "--since", "all"])
    assert md.exit_code == 0, md.output
    assert "`process_or_kb_gap` | 1 | 100%" in md.output
    assert "`kb/onboarding.md` ×1" in md.output
    assert "Work items: T-1" in md.output

    out = home / "reports" / "recurring.json"
    js = runner.invoke(
        app, ["report", "recurring", "--since", "7d", "--format", "json", "--out", str(out)]
    )
    assert js.exit_code == 0, js.output
    data = json.loads(out.read_text())
    assert data["report"] == "recurring_classes_v1"
    assert data["classes"][0]["cause_class"] == "process_or_kb_gap"
    assert data["classes"][0]["top_pages"] == [{"page": "kb/onboarding.md", "citations": 1}]
    assert data["since"] is not None


def test_cli_rejects_a_period_it_cannot_read(home: Path) -> None:
    res = CliRunner().invoke(app, ["report", "recurring", "--since", "yesterday"])
    assert res.exit_code != 0
    # rich renders the usage error with ANSI styling on a colour terminal (CI),
    # which splits option names; read the message, not the decoration.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", res.output)
    assert "expected 30d / 2w / 12h or a date" in plain
