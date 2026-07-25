# Sources

A **Source** is an external system of record OpsPilot pulls **Work items**
from — the system that owns the ticket lifecycle. **Intake** is the loop
that connects a Source to the pipeline: poll a configured scope → normalize
into a Work item → dedupe → run the matching playbook → post the suggestion
back to the Source as a structured comment
([ADR-0013](adr/0013-jsm-intake-polling-comment-writeback.md)).

Two hard rules, both inherited from the processing-layer stance
([ADR-0006](adr/0006-processing-layer-not-system-of-record.md)):

- **Comment-only write-back.** OpsPilot posts one structured comment
  (summary, suggested Severity, Tasks with Tiers, KB citations) and never
  mutates a field. The Source decides; OpsPilot suggests.
- **Polling, outbound-only.** No webhooks, no inbound exposure — the
  adapter works from behind any NAT, same as the Telegram channel
  ([ADR-0012](adr/0012-telegram-channel-long-polling.md)).

Source adapters run as separate processes and talk to a running
`opspilot serve` over HTTP, so they honor the API token (ADR-0011) and can
live on a different machine than the server.

## Try it offline first (no JSM needed)

The repo ships recorded JSM fixtures; one pass runs them through the full
pipeline and writes the would-be comments to a local directory:

```bash
opspilot serve &                                  # if not already running
opspilot source jsm --replay tests/fixtures/jsm_replay/
cat intake_comments/IT-101.md                     # the rendered suggestion
```

## Jira Service Management in ten minutes

### 1. Get a site and an API token

- Free tier: <https://www.atlassian.com/software/jira/service-management/free>
  (up to 3 agents) — note your site URL, e.g. `https://yoursite.atlassian.net`.
- API token: <https://id.atlassian.com/manage-profile/security/api-tokens> →
  **Create API token** → copy it. Basic auth = your Atlassian account email +
  this token.

### 2. Pick the intake scope (JQL)

The JQL filter is mandatory and is the **only** thing OpsPilot will ever
fetch — it is both the intake scope and the cost boundary. Start narrow:

```
project = IT AND status = "Open"
```

### 3. Run

```bash
export JSM_API_TOKEN="<your API token>"
opspilot serve &                                  # if not already running
opspilot source jsm \
  --base-url https://yoursite.atlassian.net \
  --email you@example.com \
  --jql 'project = IT AND status = "Open"'
```

Create a test ticket in the project; within one poll interval (default 60s)
it is classified, summarised, decomposed into tiered tasks — and the
suggestion appears as a comment on the ticket.

### Operation modes

| Flag | Effect |
|---|---|
| *(default)* | Poll forever; a failed pass logs and retries next interval |
| `--once` | One pass, then exit (0 on success, 1 on a failed pass) — for cron |
| `--interval 300` | Change the poll interval (seconds) |
| `--replay DIR` | One offline pass from recorded fixtures; comments go to `--out` |
| `--rerun IT-123` | Forget a key so it runs again this pass (repeatable) |
| `--state PATH` | Where processed keys live (default `intake_state.json`) |

### State and reruns

Intake state is a small JSON file (`--state`) holding the processed issue
keys and any comments that could not be posted yet. It survives restarts:
already-processed issues are not re-run, and issues created while the
adapter was down are picked up on the next pass (every pass re-fetches the
full JQL scope — there is deliberately no time cursor to miss things).

- A run that **fails** (server or provider outage) is *not* marked and
  retries automatically next pass.
- A comment that fails to **post** is queued and re-posted next pass —
  the LLM is not re-run for it.
- `--rerun IT-123` forces a fresh run for one key (the key must still
  match the JQL scope). The new suggestion is posted as a new comment.

Double-posting is prevented by an idempotency marker: the run's session id
is part of the comment footer, and the adapter checks existing comments for
it before posting.

### Security notes

- The Atlassian API token is read from `JSM_API_TOKEN` only; never pass it
  as a CLI argument (it would land in shell history and process listings).
- Grant the Atlassian account the least access that works: browse + comment
  on the intake project. OpsPilot never edits fields, transitions, or
  assignees — a comment is the entire blast radius.
- Ticket text is redacted before it reaches any model, same as every other
  input path.

## Docker Compose

`docker-compose.prod.yml` ships a `jsm-source` service behind the `jsm`
profile. Fill in the `JSM_*` variables in `.env.prod`, then:

```bash
docker compose -f docker-compose.prod.yml --profile jsm up -d
```

This starts the API server, Ollama, nginx, and the JSM intake adapter; the
adapter stores its state under the shared `opspilot-data` volume.
