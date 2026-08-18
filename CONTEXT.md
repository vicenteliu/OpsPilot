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

**Consultation**:
A multi-turn conversation between a **User** and the assistant — the surface where an operator actually works a problem, grounded in the **KB**, **Memory**, and **Skills**. Deliberately weaker than a **Session**: it reads, and the only thing it may put forward is a **Memory entry** for the human present to admit. It cannot emit a **Proposed action** and cannot be **Distilled** (ADR-0032); to act or to sink knowledge it is *escalated* into a Session, carrying a **Work item** description and nothing else — a transcript is not freezable, and a **Fixture** must be. Visible to its author and to admins only, and cleaned up after a retention period — **unless it escalated**, which pins it, so that the Session's back-reference does not point at something the system later deleted. The retention limit is what pays for calling it low-risk: it collects pasted logs and configs that never passed a Work item's redaction.
_Avoid_: chat (the surface's colloquial name), session (a Session is one playbook run), thread, conversation (fine in prose, not in schemas)

**Working set**:
The problem a **User** is currently chasing, carried across a chain of their **Consultations** and expiring when the problem does. Per-user by construction, because a **Consultation** is — which is why it is **not part of Memory**: Memory is team-global and standing, a Working set is one person's short-lived focus. Opened and closed by hand, with an unconditional inactivity fallback that closes it anyway, because nobody returns to press "close" at the moment a problem is solved. **The fallback announces itself in the next Consultation** — a Working set that expired silently leaves the operator misreading why the assistant lost the thread.
_Avoid_: short-term memory (the plain-language name that produced it; it is not a kind of **Memory**), context window, focus, current task

**Playbook**:
A human-authored workflow spec that orchestrates one or more LLM calls. Defines the prompt, retrieval mode, tool permissions, and output schema for a scenario.
_Avoid_: pipeline, workflow, prompt template

**Skill**:
A reusable, self-contained troubleshooting/task package — a `SKILL.md` (a "use-when" trigger description + procedure + tool permissions) the assistant loads on demand to guide its work. **Hand-authored** Skills live in `agent_skills/<id>/` (git-reviewable, like a Playbook) and are loaded at runtime via a `load_skill` tool: the model sees a compact catalog (name + trigger) and pulls in the full `SKILL.md` when a problem matches (progressive disclosure); weak models fall back to retrieval-injection (mirrors **retrieval mode** `tool`/`prefetch`). **One Skill covers a subsystem, not a single failure and not a methodology.** "vSphere cluster troubleshooting" is the right size; "vMotion fails on an EVC mismatch" fragments the bank into hundreds of entries, and the `load_skill` catalog is carried in context — a long catalog spends the tokens progressive disclosure was meant to save and gives the model more chances to pick wrong. "Cross-layer fault isolation" is the opposite failure: true, and not executable.

A Skill may be **drafted** by a model — from a description, or by **Distillation** from a Session whose resolution was loop-shaped — but it is admitted only by a human review and a commit (ADR-0027). **Admission is a pull request**, and the review has exactly two items: is the stopping condition present, and is `allowed_tools` right. The procedure's prose is not reviewed — it is the recoverable part. What the PR buys, even in a team of one, is a timestamp and a diff for every movement of the boundary. **Harness-gated automatic promotion is rejected, not deferred**: a Skill's load-bearing content is its stopping condition and its `allowed_tools`, and a Session that went well never exercised either, so neither a transcript nor a score can supply them. The iteration engine evolves *playbook* variants; Skills are outside it. Has a lifecycle (draft → enabled → deprecated) and a trust level (internal / community / unknown).
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
A **Conflict** may also be raised between a **Memory entry** and a **Chunk**, and that one is detected **when an answer is composed, not when the entry is written** (ADR-0031). At write time the human has just confirmed the entry and will dismiss the prompt; the moment worth interrupting is months later, a different person, an unrelated investigation — the moment nobody knows both statements exist. Against a **Memory entry** the available **Resolutions** are narrower: the entry is superseded (by appending, never editing), the **Chunk** is superseded, or dismissed — `merged` is unavailable, because merging would mean editing the entry in place.
_Avoid_: duplicate, contradiction (that is one of the three types), error

**Correction**:
A human overriding a **Chunk**'s content in place, with a reason. The old content is kept on the correction record — the Chunk is what retrieval reads, the correction is why it changed. **In-place overwrite is right for a Chunk and wrong for a Memory entry**: a Chunk is a *projection* of an external document, so editing it repairs a projection error, whereas a Memory entry is the original — it is superseded by appending, never overwritten (ADR-0031).
_Avoid_: edit, fix, update

**Wiki page**:
A written page under `wiki/pages/<kind>/<slug>.md` carrying its own lifecycle — `draft` → `reviewed` → `live` → `stale` → `archived` — plus an index and an append-only log. Distinct from a **Chunk** (retrieval's unit) and from a KB document (ingested from outside): a page is *authored here*, most often by distilling a **Session**. Holds **declarative** knowledge — what a thing is, why it exists, how it fits together.
_Avoid_: doc, article, KB entry, note

**Distillation**:
Turning a qualifying **Session** into reusable knowledge. The target follows the shape of what was learned (ADR-0026): declarative → a **Wiki page**; procedural, meaning it has a stopping condition → a **Skill**. Both land as drafts; a human admits them. Distinct from **Ingest**, which brings documents in from outside, and from **Intake**, which brings Work items in.
_Avoid_: extraction, learning, synthesis (that is one page *kind*), auto-improvement

Both a **Resolution** and a **Correction** record who acted, taken from the caller's identity and never from what the caller claims — the same rule as an **Asset event**, and for the same reason: these are the decisions about which knowledge is trustworthy, so the one thing that must not be self-reported is who decided. Records written before this rule carry per-client placeholders (`web-user`, `cli-user`, `tui-user`, `api-user`) and are left as they are.

### Memory (owned domain)

**Memory**:
The store of standing facts about the environment that have no table of their own — constraints, gotchas, and relationships an operator would otherwise carry in their head. OpsPilot's **second owned domain** (ADR-0031, after **Inventory**), a second scoped exception to ADR-0006. Team-global: an environment constraint belongs to the environment, not to whoever found it, and there is no per-**User** layer. One instance serves one team.

The boundary against everything else is *shape*, not subject: if its natural form is a set of fields it belongs in a table, and if its natural form is one sentence it belongs here. "This gateway is a Fortigate 60F" is an **Asset**; "the firewall rules at this site are the vendor's and we have no access" is Memory. The rule that keeps the boundary honest runs the other way: **when entries accumulate until you want to query them by field, that is the signal to build a table — not to give Memory fields.**
_Avoid_: context, notes, facts, knowledge base (that is the **KB**), long-term memory (implies a short-term Memory; there is none — a **Working set** is not part of Memory)

**Memory entry**:
One unit of **Memory**: a sentence, a reason, the actor, and the time. Carries up to two **Anchors** and a review date. Admitted, never harvested (ADR-0030): a human **pins** a sentence in a **Consultation** and supplies the reason, or writes both directly — author and admitter in one act, which is the strongest form. A **Session** may not propose one: unattended, its proposals could only reach a queue, and a queue is batch approval. The **reason is mandatory** — six months on it is the only way to tell a real finding from a misdiagnosis someone enshrined, which is what the review date asks a reader to judge (ADR-0035). Superseded by appending a new entry and marking the old one, so that "we recorded it wrong" stays distinguishable from "the world changed".
_Avoid_: memory (bare word — that is the store), fact, note, rule

**Anchor**:
The address a **Memory entry** applies at — an **Asset** reference, or a scope tag (site, environment, system) offered **pick-or-create** from those already in use, because free text drifts into "HQ" / "hq" / "head office" and anchor-filtered retrieval then silently misses. Both optional; an entry with neither is a *global* constraint and is injected on every turn, which is why global entries carry a hard cap. **Exactly two anchors exist and a third will not be added**: an anchor is where a sentence applies, not a field about a thing, and wanting a third is evidence that what is wanted is a table.
_Avoid_: tag, scope (that is one of the two), key, dimension

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

**Staged failure**:
A fault introduced on purpose to exercise the system — the source of most **Fixtures**, reproducible, and safe to film or demo. Useful and honest as long as it is labelled: a run that handled a drill is evidence the pipeline works, not evidence it helps.

**Wild failure**:
A fault nobody arranged and nobody saw coming. The only kind that can demonstrate the system is worth running: the operator did not know where it would break, and OpsPilot still shortened the path. Cannot be scheduled, which is precisely why it counts.
_Avoid_: real failure (a **Staged failure** is real too — the difference is foreknowledge), incident (that is a **Work item type**)

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

**Proposed action**:
An action a **Session** puts forward as part of its **Artifact** — the command, the target, the level, and why. It is surfaced with its dry-run preview and the **approval gate**'s verdict, and it runs only when a human presses execute; the request, verdict, actor, and outcome then append to the Session's trace (ADR-0028). Unattended execution is deliberately not part of this: the gate is a heuristic, and it is not what should decide that something runs unwatched. **The first batch is read-only diagnostics — collect state, run queries, pull logs — and contains no mutation at all**, because the thing being tuned first is proposal quality, and tuning that at the same time as blast radius makes a failure impossible to attribute.
_Avoid_: auto-remediation, self-healing, action item (that is a **Task**)

**Responsibility Shape**:
Which of three forms a unit of work takes — **harness-shaped** (inputs, outputs, and acceptance definable up front), **loop-shaped** (converged on by repeated attempts; the human owns the stopping condition), **graph-shaped** (cross-system dependencies and genuinely conflicting goals; the decision stays human). Used here to decide a **Distillation** target (ADR-0026) and to reason about where a **Proposed action** stops. ⚠️ **Imported term** — defined in the `Operation_Undock` workspace's `CONTEXT.md`, which owns it; cited here, never re-defined here.
_Avoid_: automation tier, complexity class

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
- A **Skill** is hand-authored in `agent_skills/`, or model-drafted and then admitted by a human review; the assistant loads a matching Skill on demand (`load_skill`) to guide troubleshooting. No Skill is promoted automatically (ADR-0027)
- **Distillation** turns a qualifying **Session** into either a **Wiki page** (declarative) or a **Skill** (procedural, has a stopping condition), chosen by **Responsibility Shape** (ADR-0026); both land as drafts and a human admits them
- A **Session** may emit a **Proposed action**; the **approval gate** verdict and dry-run preview are shown, a human presses execute, the **Sandbox** runs it, and the outcome appends to the Session's trace (ADR-0028)
- A **Channel** fronts the KB chat in assist mode; Telegram also acts as a **Source** (message → Work item → suggestion reply, ADR-0014)
- A notify-mode **Channel** receives a courtesy copy of each delivered **Intake** suggestion — best-effort; the comment on the **Source** remains the durable record
- An **Asset** may reference the **Work item** (Service Request) that initiated its procurement via `work_item_ref` — optional: existing stock enters with no Work item
- A schema-valid fulfillment **Artifact** with an `asset_draft` block auto-drafts requested-status **Assets** for its Work item — once per Work item, event-stamped with the **Session** (ADR-0018)
- Every change to an **Asset** appends one **Asset event**; the current row is a projection, the event log is the history — so deleting the Asset deletes the projection, and the log survives it
- A **Source** owns the lifecycle of the **Work items** pulled from it; **Intake** turns each new Source item into one **Session** and posts the resulting suggestion back as a comment
- A **Consultation** reads the **KB**, **Memory**, and **Skills**, and may propose a **Memory entry**; it cannot emit a **Proposed action** and cannot be **Distilled**. It *escalates* into a **Session** to do either, carrying only a **Work item** description; the two then reference each other (ADR-0032)
- A **Memory entry** is admitted by a human at the end of a **Consultation** (ADR-0030); a **Session** never proposes one
- A **Memory entry** reaches an answer on its own path — filtered by **Anchor**, injected directly — and never joins **Hybrid search** or its ranking, because a shared ranking would erase the distinction that cross-store **Conflict** detection depends on
- A **Working set** spans several **Consultations** and closes by hand or by inactivity fallback
- **Memory**, **KB**, **Wiki pages**, and **Skills** can be exported and imported; **Sessions** and **Consultations** cannot, and travel only by whole-directory backup — an append-only ledger stops being one the moment it becomes an editable file (ADR-0033). An imported **Skill** lands as a draft

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
- "intake" vs "ingest" — near-homophones, never interchangeable: **Ingest** brings *documents* into the KB; **Intake** brings *Work items* from a **Source** into the pipeline. **Distillation** is a third: it makes knowledge *out of a Session that already ran here*, rather than bringing anything in.
- "tier" — two unrelated meanings. A **Tier** is the support line a **Task** is routed to (L1/L2/L3). ADR-0023's *model tiers* (`cheap` / `thinking`) are a chat-routing setting and have nothing to do with support lines; say "model tier" whenever both could be meant, and never bare "tier" in an ADR-0023 context.
- "skills" — two directories, two unrelated meanings. `agent_skills/` holds runtime **Skills** the assistant loads (ADR-0022). The root `skills/` holds development skills for people working *on* OpsPilot (grilling, tdd, to-spec …) and has nothing to do with the product. Unresolved; renaming the root directory is the obvious fix and has not been done.
- The `wiki/` module ships a page lifecycle, an index and log, a linter, session→page conversion, and API routes, but appears in neither `ROADMAP.md` nor — until **Wiki page** was added on 2026-08-14 — this glossary. The term is now defined; the module's full surface is still undocumented.
- "PR" — in Inventory context always Purchase Requisition (`pr_number`), never pull request.
- "user" — three different people: a **User** is an authenticated IT team member; an **Assignee** is whoever holds a device (often not a User); an end employee is neither — they reach OpsPilot through Channels/ITSM. Never interchange.
- "memory" — two meanings, one of them wrong; **resolved** (#167). The package holding the **KB** implementation (chunker, ingestion, retrieval, conflict) was `src/opspilot/memory/` and is now `src/opspilot/kb/`, so the word is free for **Memory**, the environment-constraint store defined above. Same shape as the `skills/` vs `agent_skills/` collision below it — that one is still open, and this entry is the argument for closing it: the fix cost one mechanical commit. Note `docs/specs/memory/` keeps its name deliberately; unlike the package, it genuinely holds both KB schemas and a `memory-record` schema, so it is a separate question.
- "long-term / short-term memory" — the plain-language framing that produced this domain. Resolved into two terms with different lifetimes and different owners: **Memory** (standing environment facts, team-global, admitted one at a time) and **Working set** (the problem currently being chased, per-**Consultation** chain, expires). A Working set is **not** a kind of Memory — different owner, different lifetime. Neither is called "memory" bare.
- "signed" was used (in older README copy) for the **trace** and **artifact** — resolved: nothing is cryptographically signed. Artifacts are *content-addressed* (`art_<sha256[:16]>`); traces are *append-only, seq-stamped*. Both give tamper-evidence against accidental corruption, not signatures. Say "content-addressed" / "append-only", never "signed".
