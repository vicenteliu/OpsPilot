"""Thinking has two shapes, and the model config picks one.

`{"type": "enabled", "budget_tokens": N}` is rejected by every current Anthropic
model. Verified against the live API on `claude-opus-5`:

    400 invalid_request_error: "thinking.type.enabled" is not supported
    {"type": "adaptive"}                                      → 200
    {"type": "adaptive"} + output_config {"effort": "high"}   → 200

That matters because ADR-0023 routes complex chat turns to a designated
*thinking tier*, and `pb_ticket_summary_en` designated `claude-opus-5` with
`thinking_budget_tokens: 4000` — a shipped configuration that failed on every
complex turn, which is precisely the turn the tier exists for.

Removing the budget was not a fix either: the chat agent decided "is this a
thinking turn?" by `thinking_budget > 0`, so a model with no budget silently
took the ordinary tool-loop path and never reasoned at all.

See #170.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

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
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> _Resp:
        self.kwargs = kwargs
        return _Resp()


class _Client:
    def __init__(self) -> None:
        self.messages = _Messages()


def _sent(params: SamplingParams) -> dict[str, Any]:
    provider = AnthropicProvider(api_key="test-key")
    client = _Client()
    provider._client = client  # type: ignore[assignment]
    provider.chat([Message(role="user", content="hi")], model="claude-opus-5", params=params)
    return client.messages.kwargs


def test_adaptive_sends_adaptive_and_no_budget() -> None:
    kwargs = _sent(SamplingParams(thinking="adaptive", max_tokens=2048))
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert "budget_tokens" not in str(kwargs["thinking"])
    # The pre-4.6 branch forced temperature=1; adaptive models reject it.
    assert "temperature" not in kwargs


def test_effort_rides_output_config() -> None:
    kwargs = _sent(SamplingParams(thinking="adaptive", effort="high", max_tokens=2048))
    assert kwargs["output_config"] == {"effort": "high"}


def test_adaptive_without_effort_omits_output_config() -> None:
    kwargs = _sent(SamplingParams(thinking="adaptive", max_tokens=2048))
    assert "output_config" not in kwargs


def test_budget_shape_still_works_for_older_models() -> None:
    kwargs = _sent(SamplingParams(thinking_budget_tokens=4000, max_tokens=1000))
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 4000}
    assert kwargs["max_tokens"] > 4000
    assert kwargs["temperature"] == 1.0


def test_thinks_covers_both_shapes() -> None:
    assert SamplingParams(thinking="adaptive").thinks
    assert SamplingParams(thinking_budget_tokens=4000).thinks
    assert not SamplingParams().thinks


def test_no_shipped_playbook_gives_a_token_budget_to_an_adaptive_model() -> None:
    adaptive_only = {
        "claude-sonnet-5",
        "claude-opus-5",
        "claude-opus-4-7",
        "claude-opus-4-8",
        "claude-fable-5",
    }
    offenders = []
    for pb in sorted(Path("playbooks").glob("*/playbook.yaml")):
        spec = yaml.safe_load(pb.read_text())
        for model in [spec["model"], *(spec.get("extra_models") or [])]:
            params = model.get("params") or {}
            if model["name"] in adaptive_only and params.get("thinking_budget_tokens"):
                offenders.append(f"{pb.parent.name}:{model['name']}")
    assert offenders == [], f'these send "thinking.type.enabled" and get a 400: {offenders}'
