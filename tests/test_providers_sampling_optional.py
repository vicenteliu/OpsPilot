"""An unset sampling knob must not be sent.

Current Anthropic models — Sonnet 5, Opus 5, Opus 4.7/4.8, Fable 5 — **reject**
``temperature`` / ``top_p`` / ``top_k`` outright:

    400 invalid_request_error: `temperature` is deprecated for this model.

``SamplingParams`` used to default ``temperature=0.2`` / ``top_p=0.9``, and every
call site passed ``params.get("temperature", 0.2)`` on top of that, so a model
config had **no way to opt out**. ``claude-sonnet-5`` and ``claude-opus-5`` were
already listed in the playbooks' ``extra_models``, which meant selecting either
one from the UI produced an HTTP 400 before the run started.

Unset now means unset, end to end: the model config is the only thing that
decides. See #172.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from opspilot.providers import AnthropicProvider, Message, SamplingParams


def _mock_response() -> MagicMock:
    resp = MagicMock()
    resp.content = [SimpleNamespace(type="text", text="ok")]
    resp.stop_reason = "end_turn"
    resp.usage = SimpleNamespace(input_tokens=1, output_tokens=1)
    return resp


def _sent_kwargs(params: SamplingParams) -> dict[str, object]:
    """Return the kwargs the provider would send to the Anthropic client."""
    with patch("opspilot.providers.anthropic.Anthropic") as mock_cls:
        client = MagicMock()
        client.messages.create.return_value = _mock_response()
        mock_cls.return_value = client
        provider = AnthropicProvider(api_key="test-key")
        provider.chat([Message(role="user", content="hi")], model="claude-sonnet-5", params=params)
        return dict(client.messages.create.call_args.kwargs)


def test_sampling_params_default_to_unset() -> None:
    p = SamplingParams()
    assert p.temperature is None
    assert p.top_p is None
    assert p.max_tokens > 0  # required by every provider; keeps its default


def test_unset_temperature_is_not_sent() -> None:
    kwargs = _sent_kwargs(SamplingParams(max_tokens=256))
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs


def test_set_temperature_is_still_sent() -> None:
    kwargs = _sent_kwargs(SamplingParams(temperature=0.2, max_tokens=256))
    assert kwargs["temperature"] == pytest.approx(0.2)


def test_shipped_playbooks_omit_sampling_params_for_models_that_reject_them() -> None:
    """The two models already offered in the UI dropdown must be selectable."""
    rejects = {"claude-sonnet-5", "claude-opus-5", "claude-opus-4-7", "claude-opus-4-8"}
    offenders = []
    for pb in sorted(Path("playbooks").glob("*/playbook.yaml")):
        spec = yaml.safe_load(pb.read_text())
        for model in [spec["model"], *(spec.get("extra_models") or [])]:
            if model["name"] not in rejects:
                continue
            params = model.get("params") or {}
            for knob in ("temperature", "top_p", "top_k"):
                if knob in params:
                    offenders.append(f"{pb.parent.name}:{model['name']}.{knob}")
    assert offenders == [], f"these would fail with HTTP 400: {offenders}"
