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
A reusable AI task template distilled from high-scoring sessions. Has a lifecycle (draft → enabled → deprecated) and a trust level (internal / community / unknown).
_Avoid_: tool, capability, agent

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
The Stage-level end-to-end harness run that must pass before a Stage is considered complete. Requires a live Ollama instance.
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
A discrete UI feature (e.g. `run`, `ingest`, `harness`) that can be toggled on/off via `ui.modules` in config. Not an auth concept — single-user local deployment only.
_Avoid_: feature, page, view

### Action execution (Stage 4+)

**Approval gate**:
A heuristic check that *flags* an action as requiring human sign-off before apply (denylist of risky command patterns + prod-env / irreversibility flags). It is a **defense-in-depth signal and audit aid, not a security boundary** — the real boundary is the Docker L2 hardened container plus network policy. See ADR-0005.
_Avoid_: security boundary, sandbox (the gate is not the sandbox)

**Sandbox (L2)**:
The ephemeral hardened Docker container an action runs inside: read-only rootfs, `cap-drop ALL`, no-new-privileges, seccomp, tmpfs workdir, no host mounts. This — not the **approval gate** — is what actually contains an action's blast radius.
_Avoid_: container, jail, isolation layer

### Channels (Roadmap)

**Channel**:
An external messaging surface (e.g. Telegram, WeCom) connected to OpsPilot, through which a user converses with the assistant; later phases may accept **Work items** through it. Gated on the remote-access foundation (see ADR-0010).
_Avoid_: integration, connector, bot (the bot is the Channel's client-side agent, not the concept)

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
- A **Skill** is distilled from high-scoring **Sessions** and can be instantiated as a new **Playbook**
- A **Channel** (roadmap) fronts the KB chat in assist mode; **Work item** intake through a Channel is a later phase

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
- "signed" was used (in older README copy) for the **trace** and **artifact** — resolved: nothing is cryptographically signed. Artifacts are *content-addressed* (`art_<sha256[:16]>`); traces are *append-only, seq-stamped*. Both give tamper-evidence against accidental corruption, not signatures. Say "content-addressed" / "append-only", never "signed".
