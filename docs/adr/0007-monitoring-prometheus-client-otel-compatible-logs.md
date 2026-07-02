# ADR-0007: Monitoring — prometheus_client metrics + OTel-compatible logs, no tracing SDK

**Status**: Accepted
**Date**: 2026-06-06
**Stage**: 5 (productionization)

## Context

Stage 5 (docs/zh/design/STAGES.md §7.5) calls for "Prometheus metrics + OTel-compatible
structured logging". The API already ships a **hand-rolled** version in
`src/opspilot/api/middleware.py`:

- `JsonFormatter` emits single-line JSON logs.
- `inc()` / `observe()` / `metrics_text()` keep in-memory counters and
  histograms and render Prometheus text on `GET /metrics`.
- `ObservabilityMiddleware` logs each request and updates HTTP counters.

Three concrete problems with the current code:

1. **Unbounded memory.** `observe()` appends every sample to a Python list
   that is never trimmed (`_histograms[metric]: list[float]`), so memory grows
   with request volume. The summary quantiles are also computed off-spec
   (sorted-list index, not a real Prometheus summary/histogram).
2. **Dropped log context.** `JsonFormatter` only serializes
   `ts/severity/logger/msg/exc`. The `extra={path, method, status, duration_s}`
   the middleware passes is silently discarded, so the "structured" logs carry
   no request context and no correlation handle.
3. **No domain metrics.** Only HTTP request counters exist; there is nothing
   for the things that actually matter operationally — runs, ingest, harness,
   LLM token usage.

The decision is how far to go: which metrics library, and whether to adopt a
full OpenTelemetry tracing SDK or keep "OTel-compatible" to mean structured
logs only.

## Decision

1. **Adopt `prometheus_client`** for metrics. Replace the hand-rolled
   counter/histogram registry and `metrics_text()` with `prometheus_client`
   collectors, and serve `GET /metrics` via `generate_latest()` +
   `CONTENT_TYPE_LATEST`.

2. **OTel-compatible structured logs only — no OpenTelemetry SDK, no tracing
   exporter.** Keep the JSON-log approach; add a per-request correlation id and
   standardized fields, and fix `JsonFormatter` to actually emit the contextual
   `extra` fields. No spans, no OTLP collector.

3. **Canonical metric set and log fields** are fixed here (see below) so the
   implementation slice (#21) has a spec rather than re-deciding shapes.

### Canonical metrics

| Metric | Type | Labels | Status |
|---|---|---|---|
| `opspilot_http_requests_total` | Counter | `path, method, status` | exists → port to `prometheus_client` |
| `opspilot_http_request_duration_seconds` | Histogram | `path, method` | exists → real histogram |
| `opspilot_runs_total` | Counter | `playbook, work_item_type, outcome` | new (`outcome` = `passed`/`failed`/`error`) |
| `opspilot_run_duration_seconds` | Histogram | `playbook` | new |
| `opspilot_llm_tokens_total` | Counter | `provider, direction` | new (`direction` = `input`/`output`) |
| `opspilot_ingest_documents_total` | Counter | `outcome` | new |
| `opspilot_harness_runs_total` | Counter | `provider, passed` | new |

Label cardinality stays bounded: `path` is the route template, not the raw URL.

### Canonical structured-log fields

Always: `ts` (RFC3339 UTC, ms), `severity`, `logger`, `msg`, `request_id`.
On error: `exc`. Contextual (merged from the record's `extra` when present):
`path, method, status, duration_s, session_id, playbook`.

`request_id` is a per-request UUID set in a `contextvar` and attached to every
log line for that request. It is the correlation handle; if real distributed
tracing is ever needed it maps cleanly onto an OTel `trace_id`.

## Rationale

- The project is **single-user, local-first, single-process** (ADR-0002). A
  full OTel tracing stack (spans + OTLP + a collector) assumes a distributed
  system with cross-service spans to correlate — there are none here. The
  complexity has no payoff at this scale.
- `prometheus_client` is a tiny, ubiquitous dependency that **fixes the
  unbounded-memory bug for free** (bounded histogram buckets), gives a
  spec-correct exposition format with content-type negotiation, and is what any
  scrape target expects. Hand-rolling means maintaining a leak fix and an
  off-spec format ourselves — reinventing a solved problem.
- Structured JSON logs with a `request_id` deliver the correlation value that
  matters operationally, fix the existing dropped-`extra` bug, and need no
  extra infrastructure. The door to OTel tracing stays open as a later,
  separately-ADR'd step if OpsPilot ever becomes multi-service.

## Consequences

- `prometheus_client` is added to `pyproject.toml` runtime deps. The
  `inc/observe/metrics_text` helpers are replaced by `prometheus_client`
  collectors; `metrics_text()` callers and the `/metrics` route move to
  `generate_latest()`.
- `JsonFormatter` is changed to merge the record's contextual fields, and a
  `request_id` contextvar + middleware wiring is added.
- Domain metrics are instrumented on the run / ingest / harness paths.
- All of the above is implementation, deferred to **#21** — this ADR changes no
  production code.
- No OpenTelemetry SDK dependency is introduced. Adopting one later is a
  deliberate reversal of decision (2), to be recorded in its own ADR.
