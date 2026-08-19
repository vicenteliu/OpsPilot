"""Per-model token prices, in USD per million tokens.

The Anthropic API does not return a charge, so one has to be computed, and
computing it needs a table. This one is a **list-price estimate**, checked on
the date below. Introductory and promotional rates are deliberately not encoded:
a promotion that expires turns a correct number into a wrong one at a moment
nobody is watching for.

A model absent from the table costs ``0.0``, which every surface already renders
as nothing (``{#if cost_usd > 0}``). An unknown price shows nothing rather than
a wrong number — which is the whole point, because the number it replaces was
one hardcoded Sonnet rate applied to every Anthropic model, overstating Haiku
4.5 about threefold and understating Opus 5.

OpenRouter is deliberately absent: it returns the real charge on the response
(``usage.cost``), and a figure the provider computed cannot go stale.
"""

from __future__ import annotations

from typing import Final

# Checked against the published Anthropic price list on 2026-06-24.
# (input $/1M, output $/1M), keyed by model-name prefix so dated snapshots
# like `claude-haiku-4-5-20251001` resolve to their family.
_USD_PER_MILLION: Final[dict[str, tuple[float, float]]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """List-price estimate for one call, or ``0.0`` for a model we do not price.

    Longest prefix wins, so `claude-opus-4-8` is not matched by a shorter entry
    that happens to share its start.
    """
    for prefix in sorted(_USD_PER_MILLION, key=len, reverse=True):
        if model.startswith(prefix):
            per_input, per_output = _USD_PER_MILLION[prefix]
            return (input_tokens * per_input + output_tokens * per_output) / 1_000_000
    return 0.0
