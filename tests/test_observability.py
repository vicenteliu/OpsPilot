"""Tests for ``opspilot.observability`` — metric helpers + exposition (ADR-0007)."""

from __future__ import annotations

from opspilot import observability as obs


def test_render_metrics_returns_prometheus_text() -> None:
    body, content_type = obs.render_metrics()
    assert isinstance(body, bytes)
    assert "text/plain" in content_type


def test_record_run_emits_counters_and_tokens() -> None:
    before = obs.RUNS.labels(
        playbook="pb_x", work_item_type="incident", outcome="passed"
    )._value.get()
    in_before = obs.LLM_TOKENS.labels(provider="anthropic", direction="input")._value.get()

    obs.record_run(
        playbook="pb_x",
        work_item_type="incident",
        outcome="passed",
        duration_s=0.5,
        provider="anthropic",
        input_tokens=10,
        output_tokens=3,
    )

    after = obs.RUNS.labels(
        playbook="pb_x", work_item_type="incident", outcome="passed"
    )._value.get()
    in_after = obs.LLM_TOKENS.labels(provider="anthropic", direction="input")._value.get()
    assert after == before + 1
    assert in_after == in_before + 10


def test_record_run_skips_zero_token_series() -> None:
    # Zero tokens must not create/increment a token series.
    before = obs.LLM_TOKENS.labels(provider="ollama-local", direction="output")._value.get()
    obs.record_run(
        playbook="pb_y",
        work_item_type="task",
        outcome="failed",
        duration_s=0.1,
        provider="ollama-local",
        input_tokens=0,
        output_tokens=0,
    )
    after = obs.LLM_TOKENS.labels(provider="ollama-local", direction="output")._value.get()
    assert after == before


def test_record_ingest_counts_by_outcome() -> None:
    s_before = obs.INGEST_DOCUMENTS.labels(outcome="succeeded")._value.get()
    f_before = obs.INGEST_DOCUMENTS.labels(outcome="failed")._value.get()
    obs.record_ingest(succeeded=3, failed=1)
    assert obs.INGEST_DOCUMENTS.labels(outcome="succeeded")._value.get() == s_before + 3
    assert obs.INGEST_DOCUMENTS.labels(outcome="failed")._value.get() == f_before + 1


def test_record_harness_uses_string_passed_label() -> None:
    before = obs.HARNESS_RUNS.labels(provider="grok", passed="true")._value.get()
    obs.record_harness(provider="grok", passed=True)
    assert obs.HARNESS_RUNS.labels(provider="grok", passed="true")._value.get() == before + 1
