"""OpenAIProvider param handling — OpenAI vs OpenRouter token param (bugfix)."""

from __future__ import annotations

import types
from typing import Any

from opspilot.providers.openai_compat import OpenAIProvider
from opspilot.providers.types import Message, SamplingParams


def _fake_response() -> Any:
    msg = types.SimpleNamespace(content="ok", tool_calls=None)
    choice = types.SimpleNamespace(message=msg, finish_reason="stop")
    usage = types.SimpleNamespace(prompt_tokens=1, completion_tokens=1)
    return types.SimpleNamespace(choices=[choice], usage=usage)


def _provider(provider_id: str) -> tuple[OpenAIProvider, dict[str, Any]]:
    p = OpenAIProvider(provider_id, api_key="x")
    captured: dict[str, Any] = {}

    def _create(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_response()

    p._client = types.SimpleNamespace(  # type: ignore[assignment]
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=_create))
    )
    return p, captured


def test_openai_uses_max_completion_tokens_and_omits_temperature() -> None:
    p, captured = _provider("openai")
    p.chat(
        [Message(role="user", content="hi")],
        model="gpt-5",
        params=SamplingParams(temperature=0.2, top_p=0.9, max_tokens=1000),
    )
    assert captured["max_completion_tokens"] == 1000
    assert "max_tokens" not in captured
    assert "temperature" not in captured  # gpt-5/o-series only allow the default
    assert "top_p" not in captured


def test_openrouter_keeps_max_tokens_and_temperature() -> None:
    p, captured = _provider("openrouter")
    p.chat(
        [Message(role="user", content="hi")],
        model="deepseek/deepseek-v4-flash",
        params=SamplingParams(temperature=0.2, top_p=0.9, max_tokens=1000),
    )
    assert captured["max_tokens"] == 1000
    assert captured["temperature"] == 0.2
    assert captured["top_p"] == 0.9
    assert "max_completion_tokens" not in captured
