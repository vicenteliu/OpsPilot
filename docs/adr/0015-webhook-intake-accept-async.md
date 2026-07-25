# Webhook intake: accept-async endpoint, no write-back, at-least-once

Status: accepted (2026-07-25)

The inbound-push option ADR-0013 reserved for high-traffic deployments:
`POST /api/intake` accepts a normalized Work item from any pushing system
(ITSM automation rules, monitoring alerts, scripts) and runs it through
the pipeline. This complements — never replaces — the polling adapters:
polling remains the local-first default; the endpoint exists for
deployments that already run remote-exposed (ADR-0011) and want push.

- **Accept fast, process in the background.** Webhook senders time out in
  seconds; an LLM run takes tens of seconds. The endpoint validates,
  dedupes, schedules the run as a background task, and returns `202` with
  the key. Results land as normal Sessions/Artifacts, browsable via the
  UI and API.
- **No write-back.** A pusher delivers and leaves — there is no comment
  destination in a generic payload. The closed loop (suggestion posted
  back to the ticket) stays with the polling Source adapters; a JSM
  deployment that wants comments keeps using `opspilot source jsm`.
- **At-least-once, deduped by key.** Webhook senders redeliver. A repeated
  `key` is acknowledged (`duplicate: true`, HTTP 200) and not re-run. The
  seen-set is in-process, mirroring ADR-0013's run semantics: a run that
  *raises* (provider outage) is forgotten so a redelivery retries it; a
  run that *returns* a deterministic outcome (error, needs_confirmation)
  stays consumed.
- **Auth posture unchanged.** Same ADR-0011 rules as every endpoint:
  loopback needs nothing, non-loopback binds are fail-closed on the
  bearer token, public exposure goes through the reverse-proxy TLS path.
  The endpoint spends tokens, so exposing it without a token is already
  impossible remotely by construction.

**Rejected:** synchronous processing (senders time out; retries would
double-spend); caller-supplied callback URLs for write-back (SSRF surface
and a second delivery contract to get wrong — revisit only with a real
consumer); a durable server-side dedupe store (the in-process set covers
redelivery bursts; a restart re-running a rare straggler is acceptable
for advisory suggestions, and the polling adapters already own durable
state where it matters).
