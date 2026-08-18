# OpsPilot

AI-augmented IT operations workbench that turns tickets, logs, runbooks, and docs into compounding knowledge assets. Each session feeds back into the KB and skill registry, making the system incrementally better over time.

## Language

### Work item types

**Work item**:
The umbrella for any inbound unit of IT support work OpsPilot processes. Its authoritative state lives in an external system of record (ITSM or a JSON input) — OpsPilot is a *processing layer*, not the owner (see ADR-0006). Subtypes: **Incident**, **Service Request**, **Task**.
_Avoid_: ticket (colloquial — conflates the subtypes), case, issue

**Incident**:
An unplanned disruption or degradation of a service — "something is broken." Carries a suggested **Severity** (P0–P4).
_Avoid_: outage (that is a P0/P1 incident), ticket, bug

**Service Request**:
A standard, pre-approved ask for something — access, a reset, provisioning — not a break.
_Avoid_: request (bare word is overloaded), order

**Task**:
A concrete, assignable unit of work with a target **Tier**. Primarily an *output* — OpsPilot decomposes an **Incident**/**Service Request** into Tasks — but a standalone Task can also be an input that gets triaged on its own.
_Avoid_: action, step, next_action, subtask

**Work item type**:
The discriminator (`incident` | `service_request` | `task`). Trusted from the input when declared; otherwise assigned by **Classification**.
_Avoid_: category, kind

**Classification**:
The step that assigns a **Work item type** when the input does not declare one. Skipped when the type is already declared.
_Avoid_: triage (broader), detection, routing

**Severity**:
The impact/urgency grade of an **Incident**: P0 (critical / site-wide) → P4 (minimal). OpsPilot *suggests* it; the system of record owns the final value.
_Avoid_: priority (often a separate ITSM field), criticality

**Tier**:
The support line a **Task** is routed to — L1 (service desk), L2 (specialist), L3 (engineering / vendor). A suggestion, not an assignment.
_Avoid_: level, line (ambiguous), group

### Core execution units

**Session**:
An atomic unit of AI work — one playbook run tied to one input. Produces a trace, artifacts, and audit log. Never deleted; only soft-purged.
_Avoid_: job, task, request

**Playbook**:
A human-authored workflow spec that orchestrates one or more LLM calls. Defines the prompt, retrieval mode, tool permissions, and output schema for a scenario.
_Avoid_: pipeline, workflow, prompt template

**Skill**:
A reusable, self-contained troubleshooting/task package — a `SKILL.md` (a "use-when" trigger description + procedure + tool permissions) the assistant loads on demand to guide its work. **Hand-authored** Skills live in `agent_skills/<id>/` (git-reviewable, like a Playbook) and are loaded at runtime via a `load_skill` tool: the model sees a compact catalog (name + trigger) and pulls in the full `SKILL.md` when a problem matches (progressive disclosure); weak models fall back to retrieval-injection (mirrors **retrieval mode** `tool`/`prefetch`). Skills may *also* be **distilled** from high-scoring **Sessions** and evolved by the iteration engine (variant → harness-gated promotion → lineage) — a separate path, not wired into runs in v1. Has a lifecycle (draft → enabled → deprecated) and a trust level (internal / community / unknown).
_Avoid_: tool (a Skill *uses* tools; it is not one), capability, agent, Playbook (a Playbook is the pipeline spec for a Session; a Skill is loaded into a conversation)

**Artifact**:
Structured output written by a session — a JSON file validated against a versioned schema (e.g. `incident_summary_v1`).
_Avoid_: result, output, response

### Knowledge layer

**KB (Knowledge Base)**:
The long-term store of ingested documents, split into chunks, embedded, and indexed for hybrid retrieval. Grows over time as new documents are ingested.
_Avoid_: vector store, database, RAG store

**Chunk**:
A segment of a KB document produced by the `headings_then_size` splitter. The atomic unit of retrieval — identified by `chk_<sha8>`.
_Avoid_: passage, segment, document fragment

**Ingest**:
The pipeline that converts raw documents (markdown, PDF, DOCX) → redact PII → split into chunks → embed → upsert into KB.
_Avoid_: index, import, upload

**Source authority**:
How far a KB document's origin is trusted — `official` (your own signed-off SOPs), `vendor` (the manufacturer's documentation), `internal` (default: written by someone on the team), `unverified` (a forum answer, a scraped page). Recorded per document at ingest and returned on every **Hit**, so a reader can see what a citation rests on. It is *descriptive only*: retrieval ordering is relevance, and a lower tier is never demoted. Whether it should influence ranking is open — see issue #150.
_Avoid_: trust level, source quality, confidence (that is the model's, not the document's)

**Conflict**:
Two **Chunks** the detector believes cannot both be trusted — one of `temporal_supersede` (one doc is clearly newer), `scope_overlap` (near-duplicates), or `direct_contradiction` (opposing claims). Detected automatically, settled by a human: a **Resolution** (`a_wins` / `b_wins` / `merged` / `dismissed`) marks the losing Chunk superseded. Until settled it is *open*, and answers citing either Chunk are flagged.
_Avoid_: duplicate, contradiction (that is one of the three types), error

**Correction**:
A human overriding a **Chunk**'s content in place, with a reason. The old content is kept on the correction record — the Chunk is what retrieval reads, the correction is why it changed.
_Avoid_: edit, fix, update

Both a **Resolution** and a **Correction** record who acted, taken from the caller's identity and never from what the caller claims — the same rule as an **Asset event**, and for the same reason: these are the decisions about which knowledge is trustworthy, so the one thing that must not be self-reported is who decided. Records written before this rule carry per-client placeholders (`web-user`, `cli-user`, `tui-user`, `api-user`) and are left as they are.

### Retrieval

**Retrieval mode**:
A playbook-level setting (`tool` or `prefetch`) that determines how KB chunks reach the LLM.
- `tool`: model calls `kb_search` autonomously during a ReAct loop (requires strong tool-calling support).
- `prefetch`: system fetches top-k chunks before the LLM call and injects them into the system prompt; model cites directly without calling tools.
_Avoid_: RAG mode, search mode

**Hybrid search**:
The retrieval strategy that combines vector ANN search and FTS5 keyword search, fused with RRF (Reciprocal Rank Fusion).
_Avoid_: semantic search, keyword search (when referring to the combined approach)

### Evaluation

**Harness**:
The evaluation framework that runs a fixture through a session and scores the artifact against a set of evaluator rules.
_Avoid_: test suite, eval framework, benchmark

**Fixture**:
A frozen, versioned input package (KB docs + input ticket + expected ground truth) used to make harness runs reproducible.
_Avoid_: test case, sample, example

**Golden test**:
The Stage-level end-to-end harness run that must pass before a Stage is considered complete. Needs the target chat provider's API key and an embedding provider — Ollama satisfies the second only when no `OPENAI_API_KEY` is set, and is required outright only by the `golden-ollama` variant.
_Avoid_: integration test, smoke test, e2e test

**Weighted score**:
The harness output (0–1) computed as a weighted average across all evaluator rules. Stage 1 exit threshold: ≥ 0.85.
_Avoid_: score, grade, result

### Identity

**model_ref**:
A fully-pinned model identifier: `<provider_id>/<model_name>@<version>`. No `latest`, `auto`, or `stable` allowed.
_Avoid_: model name, model string

### UI / API (Stage 2+)

**Module**:
A discrete UI feature (e.g. `run`, `ingest`, `harness`) that can be toggled on/off via `ui.modules` in config, and — since the multi-user pivot (ADR-0020) — visible only to **Roles** that include it.
_Avoid_: feature, page, view

### Identity & access (ADR-0020)

**User**:
An authenticated member of the IT support team operating OpsPilot — runs work items, manages the inventory, asks the KB. End employees are *not* Users: they reach OpsPilot through Channels and the ITSM. Identified by a stable username; carries exactly one **Role** and an **Auth source**.
_Avoid_: account, operator (that is a Role), member

**Role**:
One of three fixed access levels: `viewer` (read: history, inventory, KB search) → `operator` (act: run work items, KB chat, edit inventory, rerun intake) → `admin` (govern: user management, group→role mapping, module toggles, MCP, sandbox execution). Assigned by directory-group / OIDC-claim mapping, overridable per User in the admin module. Deliberately not custom-editable (ADR-0020).
_Avoid_: permission (a Role implies permissions; it is not one), group (that is the directory side)

**Auth source**:
Where a **User**'s identity is verified: `local` (bootstrap admin + break-glass accounts), `ldap` (one connector covering OpenLDAP and Active Directory), or `oidc` (SSO via OpenID Connect — the only SSO protocol, SAML rejected). Connection parameters and secrets live in environment variables only; the admin module shows status and tests connectivity but never stores secrets.
_Avoid_: provider (taken by LLM providers), IdP (that is the remote end, not the concept)

**Service token**:
A machine credential — the continuation of the ADR-0011 bearer token — used by Channel adapters and Source adapters (Telegram, JSM polling, webhook callers). Authenticates as a synthetic `svc:` identity with operator rights; never tied to a human User and unaffected by directory outages.
_Avoid_: API key (colloquial), bot account

### Action execution (Stage 4+)

**Approval gate**:
A heuristic check that *flags* an action as requiring human sign-off before apply (denylist of risky command patterns + prod-env / irreversibility flags). It is a **defense-in-depth signal and audit aid, not a security boundary** — the real boundary is the Docker L2 hardened container plus network policy. See ADR-0005.
_Avoid_: security boundary, sandbox (the gate is not the sandbox)

**Sandbox (L2)**:
The ephemeral hardened Docker container an action runs inside: read-only rootfs, `cap-drop ALL`, no-new-privileges, seccomp, tmpfs workdir, no host mounts. This — not the **approval gate** — is what actually contains an action's blast radius.
_Avoid_: container, jail, isolation layer

### Channels

**Channel**:
An external messaging surface (e.g. Telegram, WeCom) connected to OpsPilot. Three modes: **assist** (conversational KB chat), **intake** (explicit commands file **Work items** — the Channel doubles as a **Source**), and **notify** (push-only delivery of intake suggestions; nobody replies). Implementations: Telegram assist + intake (ADR-0012, ADR-0014); WeCom notify via group-robot webhook (ADR-0016) and WeCom assist via self-built-app callback (ADR-0019 — the one Channel requiring inbound exposure, WeCom has no long polling).
_Avoid_: integration, connector, bot (the bot is the Channel's client-side agent, not the concept)

### Intake

**Source**:
An external system of record OpsPilot pulls **Work items** from — the authoritative owner of their lifecycle (ADR-0006). First Source: Jira Service Management, polled via REST (outbound-only, same deployment posture as ADR-0012). A **Channel** may double as a Source (first: Telegram via intake commands, ADR-0014), but the concepts stay distinct: a Channel is a conversational surface; a Source is where Work items live.
_Avoid_: connector, integration, upstream system

**Intake**:
The loop that connects a **Source** to the pipeline: poll a configured scope (e.g. a JQL filter) → normalize into a **Work item** → dedupe (one run per source key; reruns are manual) → run the matching **Playbook** → write the suggestion back to the Source as a structured comment (summary, suggested Severity, Tasks with Tiers, KB citations). Comment-only write-back: OpsPilot never mutates Source fields — suggest, don't decide. Runs as a separate adapter process calling the HTTP API, like a Channel adapter (ADR-0012).
_Avoid_: ingest (that is documents → KB; Intake is Work items → pipeline), sync, import

### Inventory (owned domain)

**Asset**:
A physical IT device tracked by OpsPilot — one device, one Asset (a batch purchase of 5 laptops is 5 Assets sharing procurement fields). This is the one domain OpsPilot **owns** as system of record (ADR-0017, a scoped exception to ADR-0006): small teams have no CMDB, so the authoritative data lives here, with CSV import/export as the migration path in and out. Carries identity fields (asset tag, category, brand/model, serial number — unique when set), procurement fields (**PR number**, order number, tracking number, vendor, cost), lifecycle fields (status, **Handler**, **Assignee**, location, warranty), and an append-only event log.
_Avoid_: device (colloquial — fine in prose, not in schemas), item, equipment

**Asset status**:
One of eight free-set values: `requested → ordered → shipped → received → in_stock → deployed → in_repair → retired`. A convention, not a state machine — any status can be set directly (corrections, back-filling, and mid-flow entry of existing stock are normal), and the event log records what actually happened. There is no separate "approved" status: a filled PR number is the approval evidence.
_Avoid_: state, stage, phase

**Asset event**:
An append-only, timestamped entry recording one change to an **Asset** (status transition, field change, note) and who made it. The source of date/time tracking — never edited, never deleted, and **outliving the Asset**: deleting an Asset removes the row, not its events; the closing `deleted` event carries a snapshot of the identity fields so the orphaned log still names the device.
The **actor** is derived by the system from the caller's identity — the authenticated **User**, the service identity, the `session:` that drafted it, or the OS user for CLI writes — never taken from the request. A self-reported actor is not evidence. (Events written before this rule carry placeholder actors such as `web-user`; they are left untouched, because rewriting the log to make it look better is the one thing an append-only log may not do.)
_Avoid_: history entry, audit row (it is both, but call it an event)

**PR number**:
Purchase Requisition number — the approval artifact for a procurement. In this repo "PR" otherwise means pull request; in Inventory context it is always Purchase Requisition, and schemas spell the field `pr_number`.
_Avoid_: pull request (different domain), requisition id

**Handler**:
The IT staff member processing an **Asset** (free text in v1 — no user directory). The doer, not the owner of the device.
_Avoid_: operator, processor, owner

**Assignee**:
The person an **Asset** is issued to — who uses the device (free text in v1). Distinct from **Handler**, and unrelated to Work item Task routing (Tasks get a **Tier**, not an assignee).
_Avoid_: user (collides with system user), custodian, owner

## Relationships

- A **Work item** has exactly one **Work item type** — declared by the source, or assigned by **Classification** when absent
- A **Session** processes one **Work item** and writes a type-specific **Artifact** (e.g. `incident_summary`, `request_fulfillment`)
- Processing an **Incident** or **Service Request** decomposes it into zero or more **Tasks**, each with a suggested **Tier**
- An **Incident** carries a suggested **Severity** (P0–P4); the external system of record owns the final value
- A **Playbook** specifies the **retrieval mode** and output schema for a **Session**
- A **Session** reads from the **KB** (via retrieval) and writes one or more **Artifacts**
- A **Session** appends **trace events** (prompt / response / tool_call / tool_result / redaction / user_action / system) to an append-only log
- A **Harness** run takes a **Fixture** as input and scores the resulting **Artifact**
- A **Chunk** is the unit of both storage (in KB) and citation (in Artifact)
- A **Skill** is either hand-authored (in `agent_skills/`) or distilled from high-scoring **Sessions**; the assistant loads a matching Skill on demand (`load_skill`) to guide troubleshooting. Distilled Skills are evolved by the iteration engine via harness-gated promotion (not wired into runs in v1)
- A **Channel** fronts the KB chat in assist mode; Telegram also acts as a **Source** (message → Work item → suggestion reply, ADR-0014)
- A notify-mode **Channel** receives a courtesy copy of each delivered **Intake** suggestion — best-effort; the comment on the **Source** remains the durable record
- An **Asset** may reference the **Work item** (Service Request) that initiated its procurement via `work_item_ref` — optional: existing stock enters with no Work item
- A schema-valid fulfillment **Artifact** with an `asset_draft` block auto-drafts requested-status **Assets** for its Work item — once per Work item, event-stamped with the **Session** (ADR-0018)
- Every change to an **Asset** appends one **Asset event**; the current row is a projection, the event log is the history — so deleting the Asset deletes the projection, and the log survives it
- A **Source** owns the lifecycle of the **Work items** pulled from it; **Intake** turns each new Source item into one **Session** and posts the resulting suggestion back as a comment

## Example dialogue

> **Dev:** "When a user submits a ticket, does the system create a new session immediately?"
> **Domain expert:** "Yes — a session is created before any LLM call. The playbook determines the retrieval mode: if it's `prefetch`, we fetch KB chunks first and inject them; if it's `tool`, the model calls `kb_search` itself during the run."
> **Dev:** "And what goes in the artifact?"
> **Domain expert:** "The artifact is the validated JSON output — summary, symptoms, next actions, citations. Citations reference chunk IDs from the KB. The harness checks whether those chunk IDs actually exist and whether the right ones were retrieved."

> **Dev:** "A 'VPN down site-wide' comes in with no type field. What happens?"
> **Domain expert:** "Classification assigns it `incident` — it's a break, not a request. The incident playbook runs, suggests a Severity (probably P1), and decomposes it into Tasks: 'restart gateway' → L2, 'notify affected users' → L1, 'open vendor case' → L3. Each Task is a first-class assignable item, not just a line in the summary."
> **Dev:** "Who owns the incident's status after that?"
> **Domain expert:** "Not us. OpsPilot is a processing layer — the ITSM system of record owns the lifecycle. We suggest severity and tiers; it decides."

## Flagged ambiguities

- "tool" was used to mean both a retrieval mode (`tool` mode) and a callable function (`kb_search` tool) — context disambiguates: retrieval mode is a playbook setting, tool is a callable registered with the provider.
- "session" in some LLM frameworks means a conversation window — in OpsPilot it means a single playbook run with its full audit trail, not a multi-turn conversation.
- "ticket" was the catch-all for any inbound work — resolved: the umbrella is **Work item**, with subtypes **Incident** / **Service Request** / **Task**. "ticket" is colloquial and conflates them; avoid it in specs/schemas. The legacy code names `ticket_ref` / `ticket_summary_v1` are pre-Work-item and migrate toward `work_item_ref` / `incident_summary_*`.
- "task" (lowercase: a step or next-action in prose) is **not** a **Task** work item. A **Task** is a first-class, assignable unit with a **Tier**; a summary's "next steps" only become **Tasks** once decomposed. (Note: a **Session** is also not a **Task** — see the Session entry's _Avoid_ list.)
- "intake" vs "ingest" — near-homophones, never interchangeable: **Ingest** brings *documents* into the KB; **Intake** brings *Work items* from a **Source** into the pipeline.
- "tier" — two unrelated meanings. A **Tier** is the support line a **Task** is routed to (L1/L2/L3). ADR-0023's *model tiers* (`cheap` / `thinking`) are a chat-routing setting and have nothing to do with support lines; say "model tier" whenever both could be meant, and never bare "tier" in an ADR-0023 context.
- "PR" — in Inventory context always Purchase Requisition (`pr_number`), never pull request.
- "user" — three different people: a **User** is an authenticated IT team member; an **Assignee** is whoever holds a device (often not a User); an end employee is neither — they reach OpsPilot through Channels/ITSM. Never interchange.
- "signed" was used (in older README copy) for the **trace** and **artifact** — resolved: nothing is cryptographically signed. Artifacts are *content-addressed* (`art_<sha256[:16]>`); traces are *append-only, seq-stamped*. Both give tamper-evidence against accidental corruption, not signatures. Say "content-addressed" / "append-only", never "signed".
