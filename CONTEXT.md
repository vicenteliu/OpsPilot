# OpsPilot

AI-augmented IT operations workbench that turns tickets, logs, runbooks, and docs into compounding knowledge assets. Each session feeds back into the KB and skill registry, making the system incrementally better over time.

## Language

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
Structured output written by a session — a JSON file validated against a versioned schema (e.g. `ticket_summary_v1`).
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

## Relationships

- A **Playbook** specifies the **retrieval mode** and output schema for a **Session**
- A **Session** reads from the **KB** (via retrieval) and writes one or more **Artifacts**
- A **Session** appends **trace events** (prompt / response / tool_call / tool_result / redaction / user_action / system) to an append-only log
- A **Harness** run takes a **Fixture** as input and scores the resulting **Artifact**
- A **Chunk** is the unit of both storage (in KB) and citation (in Artifact)
- A **Skill** is distilled from high-scoring **Sessions** and can be instantiated as a new **Playbook**

## Example dialogue

> **Dev:** "When a user submits a ticket, does the system create a new session immediately?"
> **Domain expert:** "Yes — a session is created before any LLM call. The playbook determines the retrieval mode: if it's `prefetch`, we fetch KB chunks first and inject them; if it's `tool`, the model calls `kb_search` itself during the run."
> **Dev:** "And what goes in the artifact?"
> **Domain expert:** "The artifact is the validated JSON output — summary, symptoms, next actions, citations. Citations reference chunk IDs from the KB. The harness checks whether those chunk IDs actually exist and whether the right ones were retrieved."

## Flagged ambiguities

- "tool" was used to mean both a retrieval mode (`tool` mode) and a callable function (`kb_search` tool) — context disambiguates: retrieval mode is a playbook setting, tool is a callable registered with the provider.
- "session" in some LLM frameworks means a conversation window — in OpsPilot it means a single playbook run with its full audit trail, not a multi-turn conversation.
