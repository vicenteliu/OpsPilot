"""AnthropicProvider honors the extended-thinking param (issue #117)."""

from __future__ import annotations

from typing import Any

from opspilot.providers.anthropic import AnthropicProvider
from opspilot.providers.types import Message, SamplingParams


class _Usage:
    input_tokens = 1
    output_tokens = 1


class _Resp:
    content: list[Any] = []
    stop_reason = "end_turn"
    usage = _Usage()


class _Messages:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> _Resp:
        self.kwargs = kwargs
        return _Resp()


class _Client:
    def __init__(self) -> None:
        self.messages = _Messages()


def _provider() -> tuple[AnthropicProvider, _Client]:
    p = AnthropicProvider(api_key="x")
    fake = _Client()
    p._client = fake  # type: ignore[assignment]
    return p, fake


def test_thinking_budget_sets_kwargs() -> None:
    p, fake = _provider()
    p.chat(
        [Message(role="user", content="hi")],
        model="claude",
        params=SamplingParams(temperature=0.2, max_tokens=2000, thinking_budget_tokens=4000),
    )
    k = fake.messages.kwargs
    assert k is not None
    assert k["thinking"] == {"type": "enabled", "budget_tokens": 4000}
    assert k["temperature"] == 1.0  # required when thinking is on
    assert k["max_tokens"] > 4000  # bumped above the budget
    assert "top_p" not in k


def test_no_thinking_by_default() -> None:
    p, fake = _provider()
    p.chat(
        [Message(role="user", content="hi")],
        model="claude",
        params=SamplingParams(temperature=0.3, max_tokens=100),
    )
    k = fake.messages.kwargs
    assert k is not None
    assert "thinking" not in k
    assert k["temperature"] == 0.3
    assert k["max_tokens"] == 100
