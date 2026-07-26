"""Tier resolution for chat routing (issue #117)."""

from __future__ import annotations

from opspilot.api.routes.chat import resolve_tier_model_id


def test_deep_thinking_prefers_thinking_then_cheap_then_explicit() -> None:
    r = resolve_tier_model_id
    assert r(cheap="c", thinking="t", deep_thinking=True, explicit="e") == "t"
    assert r(cheap="c", thinking=None, deep_thinking=True, explicit="e") == "c"
    assert r(cheap=None, thinking=None, deep_thinking=True, explicit="e") == "e"


def test_normal_prefers_cheap_then_explicit_ignoring_thinking() -> None:
    r = resolve_tier_model_id
    assert r(cheap="c", thinking="t", deep_thinking=False, explicit="e") == "c"
    assert r(cheap=None, thinking="t", deep_thinking=False, explicit="e") == "e"
    assert r(cheap=None, thinking=None, deep_thinking=False, explicit="e") == "e"


def test_unconfigured_tiers_leave_explicit_untouched() -> None:
    assert (
        resolve_tier_model_id(cheap=None, thinking=None, deep_thinking=False, explicit=None) is None
    )
    assert resolve_tier_model_id(cheap=None, thinking=None, deep_thinking=True, explicit="x") == "x"
