"""Tests for harness/reporter.py (PR-32 coverage)."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from opspilot.harness.reporter import _short_details, render_result_table
from opspilot.harness.types import EvalResult, EvaluatorResult


def _make_result(**kwargs) -> EvalResult:
    ev = EvaluatorResult(id="ev_a", type="rule.regex", score=1.0, passed=True, details={})
    defaults = {
        "run_id": "run_test",
        "fixture_id": "fix_test",
        "fixture_version": "1.0.0",
        "playbook_ref": "pb_test@1.0.0",
        "model_ref": "test/model@v1",
        "ts": "2026-05-05T00:00:00Z",
        "evaluators": [ev],
        "scores": {"weighted": 1.0, "by_type": {}},
        "passed": True,
        "output": {"session_id": "sess_test"},
        "latency_ms": {"total": 123},
    }
    defaults.update(kwargs)
    return EvalResult(**defaults)


# ── render_result_table ───────────────────────────────────────────────────


def test_render_result_table_runs_without_error():
    result = _make_result()
    buf = StringIO()
    console = Console(file=buf, width=120)
    render_result_table(result, console=console)
    output = buf.getvalue()
    assert "fix_test" in output
    assert "pb_test@1.0.0" in output


def test_render_shows_pass_for_passing():
    result = _make_result(passed=True)
    buf = StringIO()
    console = Console(file=buf, width=120, highlight=False, markup=False)
    render_result_table(result, console=console)
    assert "PASS" in buf.getvalue()


def test_render_shows_fail_for_failing():
    ev = EvaluatorResult(id="ev_b", type="rule.regex", score=0.0, passed=False, details={})
    result = _make_result(evaluators=[ev], passed=False)
    buf = StringIO()
    console = Console(file=buf, width=120, highlight=False, markup=False)
    render_result_table(result, console=console)
    assert "FAIL" in buf.getvalue()


def test_render_shows_run_id():
    result = _make_result(run_id="run_UNIQUE123")
    buf = StringIO()
    console = Console(file=buf, width=120)
    render_result_table(result, console=console)
    assert "run_UNIQUE123" in buf.getvalue()


def test_render_uses_default_console_when_none():
    result = _make_result()
    # Should not raise
    render_result_table(result, console=None)


# ── _short_details ────────────────────────────────────────────────────────


def test_short_details_empty():
    assert _short_details({}) == ""


def test_short_details_missing():
    assert "missing" in _short_details({"missing": ["key1"]})


def test_short_details_missing_empty_list_falls_through():
    # missing=[] is falsy, should fall to next branch
    result = _short_details({"missing": [], "error": "oops"})
    assert "error" in result


def test_short_details_leaked():
    assert "leaked" in _short_details({"leaked": ["email@x.com"]})


def test_short_details_error():
    assert "error=oops" in _short_details({"error": "oops"})


def test_short_details_invalid():
    assert "invalid" in _short_details({"invalid": ["bad_ref"]})


def test_short_details_expected_retrieved():
    d = {"expected": ["chk_1"], "retrieved": ["chk_1", "chk_2"]}
    out = _short_details(d)
    assert "expected=" in out
    assert "retrieved=" in out


def test_short_details_fallback():
    d = {"some_key": "some_value"}
    out = _short_details(d)
    assert "some_key" in out
    assert "some_value" in out
