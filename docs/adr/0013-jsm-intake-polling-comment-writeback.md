# Work-item intake: JSM polling Source, comment-only write-back

Status: accepted (2026-07-25)

The first **Source** (an external system of record OpsPilot pulls Work items
from — see ADR-0006 for the processing-layer stance) is **Jira Service
Management**, connected through a polling **Intake** adapter that runs as a
separate process calling the OpsPilot HTTP API — the same shape ADR-0012
established for the Telegram channel.

- **Polling, not webhooks.** Same rationale as ADR-0012: outbound connections
  only, so Intake works from behind any NAT with zero inbound exposure and no
  public HTTPS endpoint. A webhook-first design would force every deployment
  through the remote-access setup (ADR-0011) before the flagship feature
  works. A generic inbound webhook can be added later for high-traffic
  deployments without changing the intake contract.
- **Scope by JQL, auto-run.** A configured JQL filter (e.g.
  `project = IT AND status = Open`) defines exactly which work items are
  processed. Each new match runs the pipeline automatically — zero clicks —
  and is deduped by issue key (one run per key; reruns are manual). Token
  cost is bounded by the filter, not by human gating; summaries and
  decompositions are read-only suggestions, so no approval step is needed.
- **Comment-only write-back.** The suggestion (summary, suggested Severity,
  Tasks with Tiers, KB citations) is posted back to the issue as one
  structured comment. OpsPilot never mutates Source fields — this keeps
  ADR-0006's suggest-don't-decide boundary intact, and a comment is
  deletable, so the blast radius of a bad run is minimal.
- **Adapter as API client.** `opspilot source jsm` polls JSM, calls
  `POST /api/run`, and posts the comment. It honors bearer-token auth
  (ADR-0011), can run on a different machine from the server, and leaves the
  server sync-first (ADR-0003). A `--once` flag supports cron-style
  operation; a `--replay <fixtures>` mode replays recorded JSM API responses
  for offline demos and CI regression, reusing the harness Fixture concept.

**Rejected:** webhook-first intake (couples the flagship path to public
HTTPS exposure); in-server background poller (turns the API server into a
scheduler and breaks the one-adapter-pattern from ADR-0012); field-mutation
write-back (crosses the suggest/decide line and demands permission and
rollback design); human-triggered queue (kills the zero-click value — in
practice engineers stop clicking within a week); a bundled mock JSM server
(a second product surface to maintain; fixture replay covers demo and CI).
