"""A Session proposes an action; a human executes it (ADR-0028).

The value of this step is not saved keystrokes. It is that **the boundary
between proposing and doing becomes visible in the product and recorded in the
trace** — and that record is the prerequisite for ever widening it: you cannot
argue for unattended execution from a system that has never logged an attended
one.

Two constraints are pinned here because they are the ones that would erode.

**The first batch is read-only diagnostics.** `intent` is a const in the artifact
schema, so a mutating action cannot be expressed at all; `to_request` refuses one
arriving by any other route as a second line.

**The approval verdict is computed, never read from the proposal.** A model that
could set its own approval flag would be deciding whether it needs approval.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from opspilot.sandbox import ProposalError, execute_proposal, preview_proposal, to_request

SCHEMA = json.loads(
    Path("docs/specs/orchestrator/schemas/incident_summary_v1.schema.json").read_text()
)


def _proposal(**over: Any) -> dict[str, Any]:
    base = {
        "ref": "pa-1",
        "intent": "diagnose",
        "type": "shell",
        "command": "esxcli storage core path list",
        "target": "esxi-07.dc-1",
        "why": "shows whether a path is dead before anyone touches the array",
    }
    base.update(over)
    return base


class _Result:
    status = "applied"
    stdout = "path list output"
    stderr = ""
    exit_code = 0


class _Engine:
    def __init__(self) -> None:
        self.dry_runs: list[Any] = []
        self.executions: list[Any] = []

    def dry_run(self, request: Any) -> _Result:
        self.dry_runs.append(request)
        return _Result()

    def execute(self, request: Any, *, force_approve: bool = False) -> _Result:
        self.executions.append(request)
        return _Result()


class _Trace:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def write(self, event: Any) -> None:
        self.events.append(event)


class TestReadOnlyByConstruction:
    def test_the_schema_cannot_express_a_mutation(self) -> None:
        """`intent` is a const, so widening it later is a visible, reviewable diff."""
        item = SCHEMA["properties"]["proposed_actions"]["items"]
        assert item["properties"]["intent"] == {"const": "diagnose"}
        assert item["properties"]["type"]["enum"] == ["shell", "sql_readonly"]

    def test_a_non_diagnostic_intent_is_refused(self) -> None:
        with pytest.raises(ProposalError, match="read-only diagnostics"):
            to_request(_proposal(intent="remediate"), session_id="sess_1", proposed_by="model")

    def test_an_unknown_type_is_refused(self) -> None:
        with pytest.raises(ProposalError, match="not one of"):
            to_request(_proposal(type="http"), session_id="sess_1", proposed_by="model")

    def test_an_empty_command_is_refused(self) -> None:
        with pytest.raises(ProposalError, match="no command"):
            to_request(_proposal(command="   "), session_id="sess_1", proposed_by="model")


class TestVerdict:
    def test_the_gate_verdict_is_computed_not_taken_from_the_proposal(self) -> None:
        """A model setting its own approval flag would decide whether it needs approval."""
        req = to_request(
            {**_proposal(), "approval_required": False},  # ignored — not a schema field either
            session_id="sess_1",
            proposed_by="model",
        )
        assert isinstance(req.approval_required, bool)

    def test_a_dangerous_command_is_flagged(self) -> None:
        req = to_request(
            _proposal(command="rm -rf /var/log"), session_id="sess_1", proposed_by="model"
        )
        assert req.approval_required is True


class TestPreviewAndExecute:
    def test_preview_applies_nothing(self) -> None:
        engine = _Engine()
        result = preview_proposal(engine, _proposal(), session_id="sess_1", proposed_by="model")
        assert engine.executions == []
        assert engine.dry_runs and engine.dry_runs[0].dry_run is True
        assert result.dry_run_status == "applied"

    def test_execute_records_who_pressed_it(self) -> None:
        engine, trace = _Engine(), _Trace()
        execute_proposal(
            engine,
            _proposal(),
            session_id="sess_1",
            proposed_by="model",
            actor="user:alice",
            trace_writer=trace,
        )
        assert engine.executions and engine.executions[0].dry_run is False
        event = trace.events[-1]
        assert event.payload["event"] == "action_executed"
        assert event.payload["details"]["executed_by"] == "user:alice"
        assert event.payload["details"]["command"].startswith("esxcli")

    def test_an_execution_nobody_owns_is_refused(self) -> None:
        with pytest.raises(ProposalError, match="actor is required"):
            execute_proposal(
                _Engine(), _proposal(), session_id="sess_1", proposed_by="model", actor="  "
            )


class TestOptIn:
    def test_playbooks_do_not_propose_unless_they_opt_in(self) -> None:
        from opspilot.orchestrator.types import load_playbook

        pb = load_playbook(Path("playbooks/pb_ticket_summary_en"))
        assert pb.propose_actions is False
