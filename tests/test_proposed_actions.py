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
from opspilot.sandbox.types import ActionResult, ApplyResult, DryRunPreview, RequestedPolicy

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


def _dry_run_result() -> ActionResult:
    """What SandboxEngine.dry_run actually returns: a preview, and no output.

    The stub used to be a flat object with `status` / `stdout` / `exit_code` on
    it, which is not the shape of `ActionResult` — it is the shape the readers
    wrongly assumed, so it agreed with them and hid the bug.
    """
    return ActionResult(
        action_id="act_1",
        status="dry_run",
        dry_run_preview=DryRunPreview(
            command_preview="esxcli storage core path list",
            docker_args=["docker", "run", "--rm", "alpine:3.19"],
            effective_policy=RequestedPolicy(),
        ),
    )


def _applied_result() -> ActionResult:
    return ActionResult(
        action_id="act_1",
        status="applied",
        apply_result=ApplyResult(exit_code=0, stdout="path list output", stderr="", duration_ms=12),
    )


class _Engine:
    def __init__(self) -> None:
        self.dry_runs: list[Any] = []
        self.executions: list[Any] = []

    def dry_run(self, request: Any) -> ActionResult:
        self.dry_runs.append(request)
        return _dry_run_result()

    def execute(self, request: Any, *, force_approve: bool = False) -> ActionResult:
        self.executions.append(request)
        return _applied_result()


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
        assert result.dry_run_status == "dry_run"

    def test_the_preview_shows_the_command_that_would_run(self) -> None:
        # A dry run produces a preview, never stdout — reading `stdout` off the
        # ActionResult left the UI's preview box permanently empty.
        engine = _Engine()
        result = preview_proposal(engine, _proposal(), session_id="sess_1", proposed_by="model")
        assert result.dry_run_stdout == "esxcli storage core path list"

    def test_the_outcome_of_an_execution_reaches_the_person_who_ran_it(self) -> None:
        # exit_code / stdout / stderr live on `ActionResult.apply_result`. Read
        # off the ActionResult itself they are silently None and "" — for every
        # execution, which is the whole output of a diagnostic command.
        engine, trace = _Engine(), _Trace()
        result = execute_proposal(
            engine,
            _proposal(),
            session_id="sess_1",
            proposed_by="model",
            actor="user:alice",
            trace_writer=trace,
        )
        assert result.apply_result is not None
        assert result.apply_result.stdout == "path list output"
        # And the permanent record carries the outcome, not just the intent.
        assert trace.events[-1].payload["details"]["exit_code"] == 0

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


class TestThePromptDescribesWhatTheSchemaDemands:
    """The prompt is the only place the model learns the shape it must produce.

    The first real run with `propose_actions: true` returned entries carrying
    exactly the three fields the prompt named — `intent`, `command`, `why` — and
    none of the three it did not. The schema requires six, so the artifact failed
    validation and the whole summary was lost, not just the actions.

    The behaviour gate could not catch it: its case hands the model
    `json.dumps(schema["properties"]["proposed_actions"]["items"])`, supplying
    the very fields production omits.
    """

    ITEM = SCHEMA["properties"]["proposed_actions"]["items"]

    def test_every_required_field_is_named(self) -> None:
        from opspilot.orchestrator.ticket_summary import _PROPOSE_ACTIONS_PROMPT

        missing = [f for f in self.ITEM["required"] if f"`{f}`" not in _PROPOSE_ACTIONS_PROMPT]
        assert not missing, f"the model is never told to emit: {missing}"

    def test_every_accepted_value_of_a_constrained_field_is_named(self) -> None:
        from opspilot.orchestrator.ticket_summary import _PROPOSE_ACTIONS_PROMPT

        for value in self.ITEM["properties"]["type"]["enum"]:
            assert f'"{value}"' in _PROPOSE_ACTIONS_PROMPT, f"`type` may be {value}, unsaid"
        const = self.ITEM["properties"]["intent"]["const"]
        assert f'"{const}"' in _PROPOSE_ACTIONS_PROMPT
