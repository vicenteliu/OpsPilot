"""Metrics + log correlation, shared across the CLI, API, and core paths.

Decision recorded in ADR-0007: metrics via ``prometheus_client``; "OTel-
compatible" means structured JSON logs with a ``request_id`` correlation
handle, not an OpenTelemetry tracing SDK.

This module is dependency-neutral (it imports neither ``api`` nor any other
opspilot subpackage), so core code — orchestrator, ingestion, harness — can
record domain metrics without depending on the API layer.
"""

from __future__ import annotations

from contextvars import ContextVar

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# ── Request correlation ────────────────────────────────────────────────────

# Set per request by the API middleware; read by the JSON log formatter so
# every log line emitted while handling a request carries the same id.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


# ── Canonical metrics (ADR-0007) ───────────────────────────────────────────

HTTP_REQUESTS = Counter(
    "opspilot_http_requests_total",
    "HTTP requests handled by the API.",
    ["path", "method", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "opspilot_http_request_duration_seconds",
    "HTTP request latency.",
    ["path", "method"],
)

RUNS = Counter(
    "opspilot_runs_total",
    "Playbook runs by outcome.",
    ["playbook", "work_item_type", "outcome"],  # outcome: passed | failed | error
)
RUN_DURATION = Histogram(
    "opspilot_run_duration_seconds",
    "Playbook run latency.",
    ["playbook"],
)
LLM_TOKENS = Counter(
    "opspilot_llm_tokens_total",
    "LLM tokens consumed.",
    ["provider", "direction"],  # direction: input | output
)
INGEST_DOCUMENTS = Counter(
    "opspilot_ingest_documents_total",
    "Documents processed by ingestion.",
    ["outcome"],  # outcome: succeeded | failed
)
HARNESS_RUNS = Counter(
    "opspilot_harness_runs_total",
    "Harness fixture runs.",
    ["provider", "passed"],  # passed: true | false
)


# ── Recording helpers (keep call sites at the domain layer one-liners) ──────


def record_run(
    *,
    playbook: str,
    work_item_type: str,
    outcome: str,
    duration_s: float,
    provider: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    RUNS.labels(playbook=playbook, work_item_type=work_item_type, outcome=outcome).inc()
    RUN_DURATION.labels(playbook=playbook).observe(duration_s)
    if input_tokens:
        LLM_TOKENS.labels(provider=provider, direction="input").inc(input_tokens)
    if output_tokens:
        LLM_TOKENS.labels(provider=provider, direction="output").inc(output_tokens)


def record_ingest(*, succeeded: int, failed: int) -> None:
    if succeeded:
        INGEST_DOCUMENTS.labels(outcome="succeeded").inc(succeeded)
    if failed:
        INGEST_DOCUMENTS.labels(outcome="failed").inc(failed)


def record_harness(*, provider: str, passed: bool) -> None:
    HARNESS_RUNS.labels(provider=provider, passed="true" if passed else "false").inc()


def render_metrics() -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for the ``/metrics`` exposition."""
    return generate_latest(), CONTENT_TYPE_LATEST
