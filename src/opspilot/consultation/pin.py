"""``pin_to_memory`` — admitting a sentence from a Consultation (ADR-0035).

ADR-0031 had the assistant propose a **Memory entry** at the end of a
Consultation. Pinning is better, and the reason is ADR-0030's: *the admitter must
hold what the judgement needs.* Deciding whether a sentence was a conclusion or a
guess floated mid-investigation is legible only to someone who was there. The
person marking it as it is said has the context; the person reviewing a summary
afterwards has already moved on.

Two things happen together, and neither is optional:

* the entry is admitted, carrying a **reason the human types** — an entry nobody
  can judge later is not admissible, and the review date exists to ask exactly
  that question;
* the Consultation is **pinned**, because the entry now cites it permanently and
  a citation aimed at something the 90-day sweep deletes survives in name only.
"""

from __future__ import annotations

from ..memory import MemoryEntry, MemoryStore
from .store import ConsultationStore


def pin_to_memory(
    consultations: ConsultationStore,
    memory: MemoryStore,
    *,
    message_id: str,
    reason: str,
    actor: str,
    consultation_id: str | None = None,
    statement: str | None = None,
    asset_id: str | None = None,
    scope: str | None = None,
    review_after: str | None = None,
) -> MemoryEntry:
    """Admit the message's text as a Memory entry and pin its Consultation.

    ``statement`` overrides the message text — a pinned turn is usually longer
    than the standing fact inside it, and Memory holds one sentence. ``actor``
    comes from the caller's Identity and never from a request body.

    Raises ``KeyError`` if the message is unknown, and
    :class:`~opspilot.memory.AdmissionError` if the entry is not admissible.
    """
    message = consultations.message(message_id)
    if message is None:
        raise KeyError(f"message {message_id!r} not found")
    # A message id is globally unique but says nothing about who may read it.
    # The caller was cleared for *one* Consultation; without this check they can
    # name their own and pin a message out of somebody else's, which admits its
    # text as a team-visible entry, echoes it back, and pins the victim's
    # conversation against the retention sweep.
    if consultation_id is not None and message.consultation_id != consultation_id:
        raise KeyError(f"message {message_id!r} is not in {consultation_id!r}")

    entry = memory.admit(
        statement=statement if statement is not None else message.content,
        reason=reason,
        actor=actor,
        asset_id=asset_id,
        scope=scope,
        review_after=review_after,
        source_ref=message.ref,
    )
    consultations.pin(message.consultation_id, reason="memory_source")
    return entry
