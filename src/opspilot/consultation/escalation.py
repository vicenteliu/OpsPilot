"""Escalating a Consultation into a Session (ADR-0032).

A Consultation reads. To *act* on what it found — to propose an action, or to
sink the result as knowledge — it is escalated, and a **Session** is what runs.

**It carries a Work item description and nothing else.** Not the transcript. A
**Fixture** is a frozen, versioned input package, and a Session's replayability
rests on its input having edges; feeding an arbitrarily long conversation —
small talk, dead ends, pasted logs — makes it unfreezable, and the harness is the
gate a Stage is declared complete against.

Nothing is lost. The Consultation records ``→ session_id``, the Session's trace
records ``← consultation_id``, and the two can be walked in either direction.
**The escalation is itself an audit record** — the kind ADR-0028 wants at the
moment a boundary is crossed.

Escalating also **pins** the Consultation. The Session's trace is permanent; its
back-reference must not point at something the 90-day sweep deleted.
"""

from __future__ import annotations

import contextlib
import json
import tempfile
from pathlib import Path
from typing import Any

from ..orchestrator.ticket_summary import run_ticket_summary
from ..orchestrator.types import RunRequest
from ..session.types import TraceEvent


class EscalationError(Exception):
    """The Consultation cannot be escalated as asked."""


def escalate(
    consultations: Any,
    consultation_id: str,
    *,
    description: str,
    actor: str,
    session_manager: Any,
    playbook: Any,
    provider: Any,
    redactor: Any,
    embed_fn: Any,
    sqlite_store: Any,
    lance_store: Any,
    mcp_registry: Any = None,
) -> Any:
    """Run a Session from *description*, then link and pin the Consultation.

    ``description`` is the Work item — written by the person escalating, or
    drafted by the assistant and edited by them. It is deliberately the only
    thing that travels.
    """
    description = description.strip()
    if not description:
        raise EscalationError(
            "a Work item description is required: the conversation does not travel, "
            "so this is the only thing the Session will see"
        )
    if not actor.strip():
        raise EscalationError("actor is required and comes from the caller's identity")
    con = consultations.get(consultation_id)
    if con is None:
        raise KeyError(f"consultation {consultation_id!r} not found")
    if con.session_id:
        raise EscalationError(f"already escalated into {con.session_id}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(
            {
                "subject": (con.title or description)[:120],
                "body": description,
                "source": "consultation",
            },
            f,
            ensure_ascii=False,
        )
        ticket_path = Path(f.name)

    try:
        result = run_ticket_summary(
            RunRequest(playbook=playbook, input_path=ticket_path, owner=actor),
            session_manager=session_manager,
            provider=provider,
            redactor=redactor,
            embed_fn=embed_fn,
            sqlite_store=sqlite_store,
            lance_store=lance_store,
            mcp_registry=mcp_registry,
        )
    finally:
        ticket_path.unlink(missing_ok=True)

    # The back-reference, written into the permanent side. Best-effort: a lost
    # trace line must not lose the Session that was just run.
    with contextlib.suppress(Exception), session_manager.trace(result.session_id) as tw:
        tw.write(
            TraceEvent.system(
                event="escalated_from",
                details={
                    "consultation_id": consultation_id,
                    "escalated_by": actor,
                    "description": description[:2000],
                },
                actor=actor,
            )
        )
    consultations.escalate(consultation_id, session_id=result.session_id)
    return result
