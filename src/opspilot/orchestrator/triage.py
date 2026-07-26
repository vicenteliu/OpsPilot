"""Complexity triage — a cheap-model classifier for chat tier routing (#118).

Before answering, a cheap model judges whether the user's turn is SIMPLE
(routine, direct) or COMPLEX (ambiguous, multi-step, needs careful reasoning),
so the chat agent can route to the cheap or thinking tier (ADR-0023). Mirrors
the classify_work_item pattern: one cheap call, then routing follows.
"""

from __future__ import annotations

from ..providers.base import ProviderProtocol
from ..providers.types import Message, SamplingParams

_TRIAGE_SYSTEM = (
    "You route IT support questions to a model tier. Decide whether the user's "
    "question is SIMPLE (routine, direct, single-step) or COMPLEX (ambiguous, "
    "multi-step diagnosis, or needing careful reasoning). "
    "Reply with exactly one word: SIMPLE or COMPLEX."
)


def triage_complexity(
    provider: ProviderProtocol, *, model_name: str, text: str
) -> tuple[bool, str]:
    """Return ``(is_complex, raw_label)`` for *text* via one cheap classification.

    Any label containing "complex" counts as complex; everything else (including
    an empty or unexpected reply) is treated as simple.
    """
    resp = provider.chat(
        [Message(role="system", content=_TRIAGE_SYSTEM), Message(role="user", content=text)],
        model=model_name,
        params=SamplingParams(temperature=0.0, max_tokens=8),
    )
    label = (resp.content or "").strip().lower()
    return ("complex" in label), label
