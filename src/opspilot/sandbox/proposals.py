"""Turning a Session's proposed action into something a human can run (ADR-0028).

`SandboxEngine` has been reachable from the CLI and `/api/sandbox` since Stage 4,
and unreachable from the orchestrator. A Session produced a suggestion and
stopped; anything that ran was driven by a person who retyped it somewhere else.

This closes the loop **one notch, and only one**:

1. a Session may emit a **proposed action** in its artifact;
2. it is surfaced with its dry-run preview and the **approval gate**'s verdict;
3. **a human presses execute**;
4. request, preview, verdict, actor and outcome append to the Session's trace.

**Automatic execution is not here**, including for actions the gate does not
flag. The gate is a heuristic denylist and says so in its own docstring — it is a
defence-in-depth signal, not a security boundary, and it is not the thing that
should decide whether something runs unattended.

The first batch is **read-only diagnostics**, and that constraint lives in the
artifact schema rather than here: `intent` is a const, so a mutating action
cannot be expressed. What is being tuned first is proposal *quality*, and tuning
that at the same time as blast radius makes a failure impossible to attribute.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..session.types import TraceEvent
from ..timeutil import now_rfc3339
from .gate import check_approval_required
from .types import ActionRequest

# Only these reach a sandbox. The schema already forbids anything else, and this
# is the second place that says so — a proposal arriving by another route (an
# older artifact, a hand-edited file) still cannot become a mutation.
DIAGNOSTIC_TYPES = ("shell", "sql_readonly")


class ProposalError(Exception):
    """The proposal cannot be turned into a runnable request."""


@dataclass(frozen=True)
class Preview:
    """What a human sees before deciding: the command, the gate, the dry run."""

    ref: str
    request: ActionRequest
    approval_required: bool
    dry_run_stdout: str
    dry_run_status: str


def to_request(proposal: dict[str, Any], *, session_id: str, proposed_by: str) -> ActionRequest:
    """Build an :class:`ActionRequest` from an artifact's proposed action."""
    intent = proposal.get("intent")
    if intent != "diagnose":
        raise ProposalError(
            f"intent {intent!r} is not runnable: the first batch is read-only diagnostics"
        )
    action_type = proposal.get("type")
    if action_type not in DIAGNOSTIC_TYPES:
        raise ProposalError(f"type {action_type!r} is not one of {DIAGNOSTIC_TYPES}")
    command = str(proposal.get("command") or "").strip()
    if not command:
        raise ProposalError("the proposal carries no command")

    request = ActionRequest(
        id=f"act_{session_id[-8:]}_{proposal.get('ref', 'pa-0')}",
        session_id=session_id,
        proposed_by=proposed_by,
        created_at=now_rfc3339(),
        type=action_type,
        payload={"command": command, "target": str(proposal.get("target") or "")},
        dry_run=True,
        description=str(proposal.get("why") or ""),
    )
    # The verdict is computed, never taken from the proposal: a model that could
    # set its own approval flag would be deciding whether it needs approval.
    return request.model_copy(update={"approval_required": check_approval_required(request)})


def preview_proposal(
    engine: Any, proposal: dict[str, Any], *, session_id: str, proposed_by: str
) -> Preview:
    """Dry-run it and compute the gate verdict. Nothing is applied."""
    request = to_request(proposal, session_id=session_id, proposed_by=proposed_by)
    result = engine.dry_run(request)
    return Preview(
        ref=str(proposal.get("ref", "pa-0")),
        request=request,
        approval_required=bool(request.approval_required),
        dry_run_stdout=str(getattr(result, "stdout", "") or ""),
        dry_run_status=str(getattr(result, "status", "unknown")),
    )


def execute_proposal(
    engine: Any,
    proposal: dict[str, Any],
    *,
    session_id: str,
    proposed_by: str,
    actor: str,
    trace_writer: Any = None,
) -> Any:
    """Run it, because a human said so. ``actor`` is who pressed execute.

    ``actor`` comes from the caller's identity and never from the request — the
    whole point of this step is that the trace can answer *who decided this ran*,
    and a self-reported answer is not evidence.
    """
    if not actor.strip():
        raise ProposalError("actor is required: an execution nobody owns is not an execution")
    request = to_request(proposal, session_id=session_id, proposed_by=proposed_by)
    runnable = request.model_copy(update={"dry_run": False})
    # force_approve records that a human took responsibility for a gate-flagged
    # action; it does not bypass the sandbox, which is the actual boundary
    # (ADR-0005).
    result = engine.execute(runnable, force_approve=True)

    if trace_writer is not None:
        trace_writer.write(
            TraceEvent.system(
                event="action_executed",
                details={
                    "ref": str(proposal.get("ref", "pa-0")),
                    "action_id": request.id,
                    "command": request.payload.get("command", ""),
                    "approval_required": request.approval_required,
                    "executed_by": actor,
                    "status": str(getattr(result, "status", "unknown")),
                    "exit_code": getattr(result, "exit_code", None),
                },
                actor=actor,
            )
        )
    return result


def record_proposals(trace_writer: Any, proposals: list[dict[str, Any]]) -> None:
    """Write the proposals to the trace as they are made.

    Proposing is not doing, and it is still worth a record: a Session that
    suggested something and was never acted on is evidence about proposal
    quality, which is the thing this first batch exists to tune.
    """
    for p in proposals:
        trace_writer.write(
            TraceEvent.system(
                event="action_proposed",
                details={
                    "ref": p.get("ref"),
                    "intent": p.get("intent"),
                    "type": p.get("type"),
                    "command": p.get("command"),
                    "target": p.get("target"),
                    "why": p.get("why"),
                },
                actor="system",
            )
        )
