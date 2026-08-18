# Roadmap

Coarse-grained direction, not a commitment. Concrete work items live in
[GitHub Issues](https://github.com/vicenteliu/OpsPilot/issues).

Every claim below was checked against the code on 2026-07-26. If a line here
disagrees with `src/`, the code wins and this file is the bug.

## Shipped

**Remote access foundation** — required by
[ADR-0010](docs/adr/0010-remote-access-foundation-before-channels.md), landed as
[ADR-0011](docs/adr/0011-remote-access-bearer-token-proxy-tls.md): Service-token
auth (fail-closed for non-loopback binds), TLS via reverse proxy or uvicorn
`--ssl-*`, PII boundary re-evaluated for remote callers.

**Channels** — external messaging surfaces connected to OpsPilot
([docs/channels.md](docs/channels.md)):

- Telegram assist — long-polling adapter fronting KB-augmented chat
  ([ADR-0012](docs/adr/0012-telegram-channel-long-polling.md))
- Telegram intake — `/intake`, `/incident`, `/request` file a message as a Work
  item and reply with the suggestion
  ([ADR-0014](docs/adr/0014-telegram-intake-rides-channel-adapter.md))
- WeCom notify — group-robot webhook pushes intake suggestions to an ops group
  ([ADR-0016](docs/adr/0016-wecom-notify-mode-group-robot.md))
- WeCom assist — self-built-app callback riding the API server
  ([ADR-0019](docs/adr/0019-wecom-assist-callback-on-server.md))

**Work-item intake (Sources)** — the poll → run → write-back loop
([docs/sources.md](docs/sources.md)):

- Jira Service Management polling (`opspilot source jsm`) — JQL-scoped
  auto-run, dedupe by issue key, suggestion posted back as a comment;
  comment-only, no field mutation
  ([ADR-0013](docs/adr/0013-jsm-intake-polling-comment-writeback.md))
- Persistent state, manual reruns, `--once`, and `--replay` fixture mode
- Generic inbound webhook — `POST /api/intake`, accept-async with key dedupe
  ([ADR-0015](docs/adr/0015-webhook-intake-accept-async.md))

**IT asset inventory** — OpsPilot's first owned domain, a scoped exception to
[ADR-0006](docs/adr/0006-processing-layer-not-system-of-record.md)
([ADR-0017](docs/adr/0017-inventory-owned-domain.md)):

- One device = one Asset; eight free-set statuses, no state machine; every
  change appends an Asset event whose actor comes from the caller's identity
- REST CRUD, cross-Asset event feed, `inventory` UI module, CSV import/export
- Fulfillment drafts Assets from a physical-device Service Request, idempotent
  per Work item ([ADR-0018](docs/adr/0018-fulfillment-drafts-assets.md))
- Procurement grouping with batch field sync, and
  `opspilot inventory warranty-check` (WeCom push when configured) — both were
  listed as extension directions and have since landed

**Multi-user auth** — three fixed roles, three identity sources
([ADR-0020](docs/adr/0020-multi-user-auth-three-roles-three-sources.md), which
supersedes [ADR-0002](docs/adr/0002-stage2-single-user-no-auth.md)):

- Local accounts, server-side cookie sessions, role enforcement, admin module
- LDAP connector (OpenLDAP + Active Directory), group→role mapping
- OIDC SSO (authorization code + PKCE); SAML rejected
- All-in-one Docker image — the web UI is built into the api image and served
  by FastAPI, so one `docker run` is a complete workbench

**Assistant and model control**:

- Admins curate a playbook's selectable model list in place
  ([ADR-0021](docs/adr/0021-admin-edits-playbook-model-list.md))
- Runtime Skills — hand-authored `SKILL.md` loaded on demand via `load_skill`,
  plus LLM-assisted drafting in the admin editor
  ([ADR-0022](docs/adr/0022-runtime-skills-for-the-assistant.md))
- Complexity-tiered model routing
  ([ADR-0023](docs/adr/0023-complexity-tiered-model-routing.md))
- Remote MCP server management from the admin UI; stdio stays file-only
  ([ADR-0024](docs/adr/0024-mcp-management-remote-ui-stdio-file-only.md))

**Public-facing polish** — repo hygiene, English as the canonical docs language
with Chinese translations, `CONTRIBUTING.md` / `SECURITY.md`, the dark-first web
UI, and a brand mark generated from a single SVG source.

## Open

**Model-comparison results that mean what they say.** Running the golden fixture
across four models turned up three defects in a row, two fixed and one open:

- `SqliteStore` shared one unguarded connection across the executor threads every
  API route uses — eight concurrent `upsert_document` calls raised three
  `InterfaceError`s and landed four rows, and concurrent corrections failed to
  read chunks that were present. Independent of `--workers`; fixed by serialising
  every connection-touching method behind one reentrant lock
  ([#166](https://github.com/vicenteliu/OpsPilot/issues/166), deliberately
  decoupled from any storage migration — [ADR-0033](docs/adr/0033-storage-posture-fix-the-defect-now-defer-postgres.md)).
- Sampling params were sent unconditionally, so Sonnet 5 and Opus 5 — already in
  six playbooks' `extra_models` — returned HTTP 400 on every run
  ([#172](https://github.com/vicenteliu/OpsPilot/issues/172)). Extended thinking
  had the same shape of bug against the same models
  ([#170](https://github.com/vicenteliu/OpsPilot/issues/170)). Both fixed; the
  posture behind them is [ADR-0034](docs/adr/0034-hosted-api-models-are-primary-local-inference-is-auxiliary.md).
- **Open:** a `ProviderError` silently retries on `extra_models[0]`, so a
  different model answers and the row keeps the primary's `model_ref`. Naming a
  model that does not exist currently scores 0.903 and passes
  ([#175](https://github.com/vicenteliu/OpsPilot/issues/175)). This is the next
  thing to do — until it is fixed, no comparison table can be trusted.

**Skill-shaped distillation targets.** The distillation *machinery* exists —
`wiki/query_to_page.py` turns a qualifying Session into a draft wiki page, and
`skill_drafter.py` drafts a Skill from a description. What is missing is the
Skill-shaped path: a trigger that recognises a **loop-shaped** resolution —
repeated tool calls narrowing on one hypothesis — which is a different signal
from the synthesis-worthy one `query_to_page` already uses
([ADR-0026](docs/adr/0026-distillation-target-follows-the-shape-of-the-knowledge.md)).
The gap is a target, not distillation. Note what is *not* coming: harness-gated
automatic promotion is rejected, not deferred
([ADR-0027](docs/adr/0027-skills-are-machine-drafted-and-human-admitted.md)), so
the iteration engine keeps evolving playbook variants and Skills stay outside it.

**Memory — the second owned domain**
([ADR-0031](docs/adr/0031-memory-is-the-second-owned-domain.md), revised by
[ADR-0035](docs/adr/0035-memory-revised-after-reading-the-spec-it-was-written-without.md)).
The store for environment constraints that have no table: one sentence, a
mandatory reason, an actor from the caller's identity, up to two anchors, a soft
review date. Team-global, superseded by appending rather than overwriting,
retrieved on its own anchor-filtered path rather than through hybrid search.

*Shipped:* the store (`opspilot/memory/`), admission with the global cap,
supersede, archive, anchor filtering, pick-or-create scopes,
`opspilot memory add / list / supersede / scopes`, `pin_to_memory` from a
Consultation, and **injection into a chat turn** — a labelled section of the
system prompt on its own path, never joining hybrid search.

REST: `GET/POST /api/memory`, `/memory/scopes`, `/memory/{id}/supersede`,
`/memory/{id}/archive`.

A `memory` UI module lists entries, admits them, supersedes and archives, with
pick-or-create scopes and a due-for-review mark.

**Answer-time conflict** against the KB is recorded: the assistant calls
`report_conflict` with both ids when a constraint and a document contradict each
other, and the row stays *open* until a human settles it —
`entry_superseded` / `chunk_superseded` / `dismissed`. `merged` is deliberately
absent, because merging would mean editing an entry in place. `GET
/api/memory/conflicts`, `PATCH /api/memory/conflicts/{id}/resolve`.

*Not yet:* a UI for settling them.

**Consultation — the conversational surface**
([ADR-0032](docs/adr/0032-a-consultation-is-read-only-escalate-to-a-session-to-act.md)).
`POST /api/chat/stream` is its stateless ancestor. Read-only by decision — no
proposed actions, no distillation.

*Shipped:* the store (`opspilot/consultation/`) — turns, an author, per-user
visibility (the repo's first), the 90-day sweep with pin-on-escalation and
pin-on-cited, `pin_to_memory` (Memory's other admission path, ADR-0035), and
`opspilot consultation list / show / purge`.

The **Working set** ships with it: one open problem per person, carrying the
anchors that let a chat turn see *anchored* Memory at all, with an unconditional
inactivity fallback that closes it and announces the closure once. `opspilot
workingset open / status / close / sweep`.

`POST /api/chat/stream` now persists each turn into a Consultation, resolves the
turn's Memory anchors from the caller's Working set, and delivers the
inactivity-closure notice as an SSE `notice` event. REST:
`GET /api/consultations`, `GET /api/consultations/{id}`,
`POST /api/consultations/{id}/messages/{mid}/pin`, and
`GET/POST/DELETE /api/working-set`.

The Chat tab carries a working-set bar, delivers the inactivity notice, and puts
a **Remember this** action on every assistant turn — the reason field is required,
because it is what the review date later asks a reader to judge.

*Not yet:* escalation actually creating the Session, and the deferred context
budget (trigger: when a stored Consultation's history can exceed the model's
window — `docs/specs/session/templates/context-budget.template.yaml`).

**Export and import for KB / Skills / Wiki / Memory**
([ADR-0033](docs/adr/0033-storage-posture-fix-the-defect-now-defer-postgres.md)).
A tar of per-domain native formats plus a manifest; KB exports source documents
and the receiver re-ingests, because vectors are bound to an embedding model.
Sessions and Consultations get no export interface, by decision.

**Live verification of the identity and channel integrations.** LDAP, OIDC, the
all-in-one image, and WeCom assist are implemented and covered by offline tests,
but their against-real-infrastructure checks are manual post-deployment steps
that have not been run. Not development work; still unfinished business.

## Later

- **Mobile companion, PWA-first** — the SvelteKit UI is already installable
  (manifest, icons, service worker, responsive breakpoints); what remains is
  deciding whether to invest in the mobile experience specifically. No separate
  codebase.
- **Voice input** — ingest voice recordings and files from device storage →
  transcription → KB-augmented answers. Nothing built. The engine is
  undecided, but it will not be a source-built runtime
  ([ADR-0025](docs/adr/0025-no-source-built-inference-runtimes.md)).
- **A native app** remains exploratory and is not committed.

- **Postgres + pgvector** — the intended destination if storage moves, in one
  step rather than by adding a third store
  ([ADR-0033](docs/adr/0033-storage-posture-fix-the-defect-now-defer-postgres.md)).
  Not scheduled: it costs ADR-0008's zero-infrastructure install, the all-in-one
  image, a golden-test recalibration when FTS5 becomes `tsvector`, and the
  migration of sessions / auth / inventory / settings along with the KB. Revisit
  when the #166 write lock is a measured bottleneck, a second machine is
  genuinely required, or an external constraint mandates a central database.
  Replacing LanceDB with ChromaDB was considered and rejected — the defect it was
  meant to solve is in SQLite.
