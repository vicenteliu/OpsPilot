"""Complexity triage classifier (#118)."""

from __future__ import annotations

import types
from typing import Any

from opspilot.api.routes.chat import _triage_is_complex
from opspilot.orchestrator.triage import triage_complexity
from opspilot.providers.types import ChatResponse, Usage


class FakeProvider:
    def __init__(self, content: str) -> None:
        self._content = content

    def chat(self, messages, *, model, params, tools=None, timeout_ms=90_000):  # type: ignore[no-untyped-def]
        return ChatResponse(content=self._content, finish_reason="stop", usage=Usage())


class RaisingProvider:
    def chat(self, *a: Any, **k: Any) -> ChatResponse:
        raise RuntimeError("provider down")


def test_complex_label_is_complex() -> None:
    is_complex, label = triage_complexity(FakeProvider("COMPLEX"), model_name="m", text="q")
    assert is_complex is True
    assert label == "complex"


def test_simple_and_garbage_are_not_complex() -> None:
    assert triage_complexity(FakeProvider("SIMPLE"), model_name="m", text="q")[0] is False
    assert triage_complexity(FakeProvider(""), model_name="m", text="q")[0] is False
    assert triage_complexity(FakeProvider("¯\\_(ツ)_/¯"), model_name="m", text="q")[0] is False


def _state(provider: Any) -> Any:
    model = types.SimpleNamespace(provider_id="anthropic", kind="anthropic", name="m", params={})
    return types.SimpleNamespace(
        playbook=types.SimpleNamespace(model=model, extra_models=[]),
        cfg=types.SimpleNamespace(anthropic_api_key="k", ollama_base_url="http://x"),
        chat_provider=provider,
    )


def test_triage_helper_returns_bool() -> None:
    assert _triage_is_complex(_state(FakeProvider("COMPLEX")), None, "hard") is True
    assert _triage_is_complex(_state(FakeProvider("SIMPLE")), None, "easy") is False


def test_triage_helper_degrades_to_simple_on_error() -> None:
    # A provider failure must not break chat — routing falls back to the cheap tier.
    assert _triage_is_complex(_state(RaisingProvider()), None, "q") is False
