"""Reported cost has to be either right or absent — never confidently wrong.

Two independent defects, both found by one real turn that reported
``cost_usd: 0.0`` for 6484 input / 1834 output tokens on OpenRouter:

- ``openai_compat`` hardcoded ``cost_usd=0.0``, so every paid OpenAI /
  OpenRouter / Gemini / Grok call read as free.
- ``anthropic`` hardcoded ``(in*3 + out*15)/1M`` — one Sonnet rate applied to
  every Anthropic model, overstating Haiku 4.5 threefold.

ADR-0023 routes between a cheap tier and a thinking tier, and cost is the number
that justifies the routing, so a wrong one is worse than none.
"""

from __future__ import annotations

import types
from typing import Any

from opspilot.providers.openai_compat import OpenAIProvider
from opspilot.providers.pricing import estimate_cost_usd
from opspilot.providers.types import Message, SamplingParams


class TestPriceTable:
    def test_each_family_gets_its_own_price(self) -> None:
        m = 1_000_000
        assert estimate_cost_usd("claude-haiku-4-5", m, 0) == 1.0
        assert estimate_cost_usd("claude-sonnet-5", m, 0) == 3.0
        assert estimate_cost_usd("claude-opus-5", m, 0) == 5.0
        assert estimate_cost_usd("claude-fable-5", 0, m) == 50.0

    def test_a_dated_snapshot_resolves_to_its_family(self) -> None:
        """The playbook names models like `claude-haiku-4-5-20251001`."""
        assert estimate_cost_usd("claude-haiku-4-5-20251001", 1_000_000, 0) == 1.0

    def test_longest_prefix_wins(self) -> None:
        """`claude-opus-4-8` must not be captured by a shorter entry."""
        assert estimate_cost_usd("claude-opus-4-8", 1_000_000, 0) == 5.0

    def test_an_unpriced_model_reports_nothing_rather_than_something_wrong(self) -> None:
        assert estimate_cost_usd("some-model-we-do-not-price", 10_000, 10_000) == 0.0


def _fake_response(usage: Any) -> Any:
    msg = types.SimpleNamespace(content="ok", tool_calls=None)
    choice = types.SimpleNamespace(message=msg, finish_reason="stop")
    return types.SimpleNamespace(choices=[choice], usage=usage)


def _provider(provider_id: str, usage: Any) -> tuple[OpenAIProvider, dict[str, Any]]:
    p = OpenAIProvider(provider_id, api_key="x")
    captured: dict[str, Any] = {}

    def _create(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_response(usage)

    p._client = types.SimpleNamespace(  # type: ignore[assignment]
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=_create))
    )
    return p, captured


_ASK = [Message(role="user", content="hi")]


class TestOpenRouterReportsWhatItCharged:
    def test_the_charge_is_requested_and_used(self) -> None:
        usage = types.SimpleNamespace(prompt_tokens=90, completion_tokens=10, cost=1.45e-05)
        p, captured = _provider("openrouter", usage)
        resp = p.chat(_ASK, model="deepseek/deepseek-v4-flash", params=SamplingParams())
        assert captured["extra_body"] == {"usage": {"include": True}}
        assert resp.usage.cost_usd == 1.45e-05

    def test_other_providers_are_not_sent_the_extension(self) -> None:
        """`usage: {include}` is an OpenRouter field; OpenAI would reject it."""
        usage = types.SimpleNamespace(prompt_tokens=1, completion_tokens=1)
        for provider_id in ("openai", "gemini", "grok"):
            p, captured = _provider(provider_id, usage)
            p.chat(_ASK, model="m", params=SamplingParams())
            assert "extra_body" not in captured, provider_id

    def test_a_response_without_a_cost_field_reports_nothing(self) -> None:
        usage = types.SimpleNamespace(prompt_tokens=5, completion_tokens=5)
        p, _ = _provider("openrouter", usage)
        assert p.chat(_ASK, model="m", params=SamplingParams()).usage.cost_usd == 0.0
