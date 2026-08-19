"""Rendering Memory into a turn (ADR-0031, revised by ADR-0035).

Memory reaches an answer on **its own path**: filtered by anchor, injected
directly. It never joins hybrid search and never enters the RRF ranking, for
three reasons, the first decisive.

**Conflict between Memory and the KB is detected when an answer is composed**,
which requires the assistant to tell "this came from Memory" from "this came from
the knowledge base". A shared ranking erases that distinction, and with it the
only chance to notice that a recorded constraint and an ingested document
disagree — the moment nobody knows both statements exist.

Second, the volumes differ by orders of magnitude: tens of entries against tens
of thousands of chunks. In one ranking Memory is either drowned or needs a
hand-tuned weight, and *needing a weight is itself the proof they do not belong
in one ranking.*

Third, Memory's retrieval condition is not semantic relevance but "does this
constraint apply at this address". That is a filter, not a ranking.
"""

from __future__ import annotations

from ..timeutil import now_rfc3339
from .store import MemoryEntry, MemoryStore

_HEADER = """## Memory — standing facts about this environment

Your team recorded and admitted these. They are **not** knowledge-base documents:
each was written by a named person, with a reason, and describes how *this*
environment actually behaves. Treat them as binding constraints on what you
recommend.

If one of them contradicts something you find in the knowledge base, **say so
explicitly and name both** rather than silently preferring either. A recorded
constraint and an ingested document disagreeing is worth a human's attention, and
this turn is the only place anyone will notice."""


# The other half of ADR-0030. The header above is what an *existing* entry says;
# this is how a new one starts, and without it the assistant has no idea Memory
# exists — `memory_block` returns "" on an empty store, which is every fresh
# install, so the store stays empty for the same reason it is empty.
#
# Observed before this existed: asked "is there a standing fact about this
# cluster I should record?", the model produced a textbook Memory entry and
# directed it to a **Wiki page**. It was not wrong to want it written down; it
# had never been told where such a thing goes.
#
# The assistant proposes, a person admits (ADR-0030). Admission is a human
# pinning the message, so all this asks for is a label a person can act on.
PROPOSAL_HINT = """

## Recording a standing fact

Some answers turn up a fact about *this* environment that will still be true
next month and has no table of its own: what manages this cluster's Secrets,
which vendor's firmware bricks on a rolling upgrade, why one site's VPN needs a
longer timeout. Someone re-derives each of those at every incident until it is
written down.

When your answer contains one, end with exactly this line:

**Worth recording as a Memory entry:** <the one sentence to record> — <why it matters>

A person admits it by pinning your message; you never write one yourself, and
you should not offer to. Do not route the fact to the knowledge base or a wiki
page instead — those hold documents that came from somewhere else. Memory holds
what this team learned about this place.

A question you answered from general knowledge alone turned up no such fact.
Leave the line off."""


def render_entry(entry: MemoryEntry, *, now: str) -> str:
    """One line: what holds, where, why, who said so — and whether it is stale."""
    where = entry.scope or entry.asset_id or "everywhere"
    line = f"- [{entry.id}] {entry.statement} — applies at {where}; {entry.reason}"
    if entry.review_overdue_at(now):
        # A label, never a withholding: hard expiry would drop a still-correct
        # constraint at an unknown moment. The reader decides, not a timer.
        line += f" ⚠ due for review since {entry.review_after}"
    return line


def memory_block(
    store: MemoryStore,
    *,
    asset_id: str | None = None,
    scope: str | None = None,
    now: str | None = None,
) -> str:
    """The Memory section for a turn's system prompt, or ``""`` when nothing applies.

    Un-anchored entries always apply — which is why they are capped. Anchored ones
    apply only at the address given here; without an anchor a turn sees the global
    constraints and nothing else, which is correct rather than a degradation: a
    constraint about another site has no business steering this answer.
    """
    entries = store.applicable(asset_id=asset_id, scope=scope)
    if not entries:
        return ""
    stamp = now or now_rfc3339()
    lines = "\n".join(render_entry(e, now=stamp) for e in entries)
    return f"\n\n{_HEADER}\n\n{lines}"
