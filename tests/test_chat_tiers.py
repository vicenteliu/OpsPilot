"""Tier routing for chat, incl. auto complexity triage (#117, #118)."""

from __future__ import annotations

from opspilot.api.routes.chat import route_chat_model


def _never() -> bool:
    raise AssertionError("triage must not be called here")


def test_deep_thinking_forces_thinking_without_triage() -> None:
    mid, step = route_chat_model(
        cheap="c", thinking="t", deep_thinking=True, explicit="e", triage=_never
    )
    assert mid == "t"
    assert step is None


def test_both_tiers_complex_routes_thinking_with_step() -> None:
    mid, step = route_chat_model(
        cheap="c", thinking="t", deep_thinking=False, explicit="e", triage=lambda: True
    )
    assert mid == "t"
    assert step == {"type": "routing", "tier": "thinking"}


def test_both_tiers_simple_routes_cheap_with_step() -> None:
    mid, step = route_chat_model(
        cheap="c", thinking="t", deep_thinking=False, explicit="e", triage=lambda: False
    )
    assert mid == "c"
    assert step == {"type": "routing", "tier": "cheap"}


def test_no_thinking_tier_uses_cheap_without_triage() -> None:
    mid, step = route_chat_model(
        cheap="c", thinking=None, deep_thinking=False, explicit="e", triage=_never
    )
    assert mid == "c"
    assert step is None


def test_unconfigured_tiers_fall_back_to_explicit_without_triage() -> None:
    mid, step = route_chat_model(
        cheap=None, thinking=None, deep_thinking=False, explicit="e", triage=_never
    )
    assert mid == "e"
    assert step is None
