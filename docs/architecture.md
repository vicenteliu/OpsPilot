# Architecture

How a work item flows through OpsPilot, how the layers fit together, and the
key design decisions. Decision records live in [`docs/adr/`](adr/); the domain
language is defined in [`CONTEXT.md`](../CONTEXT.md).

## Request flow

```
Browser (Svelte 5 / SvelteKit)
  │  POST /api/run[/stream] { input, model_id }
  │  GET  /api/models  ·  GET /api/sessions
  ▼
FastAPI  (opspilot.api)
  │  GET /health · GET /metrics (Prometheus)
  │  picks the playbook: playbook_id › declared work_item_type ›
  │    Judgments stage (off by default, ADR-0040) › Classification
  │  then the provider from model_id
  ▼
Orchestrator  (opspilot.orchestrator)
  ├─▶ Redactor ──────────────── strips PII from work-item text
  │
  ├─▶ KB Search  ─────────────── hybrid retrieval over ingested KB
  │     ├── SqliteStore  (FTS5 full-text search)
  │     └── LanceStore   (LanceDB vector search)
  │           ▲
  │     embedded by OpenAI text-embedding-3-small (768 dims) by default,
  │     or Ollama nomic-embed-text-v2-moe on request
  │
  ├─▶ Provider  ──────────────── sends redacted prompt + KB chunks to LLM
  │     ├── AnthropicProvider   (Claude Haiku / Sonnet / Opus)
  │     ├── OpenAIProvider      (OpenAI · OpenRouter · Gemini · Grok)
  │     └── OllamaProvider      (local Gemma, Phi, …)
  │           │ ProviderError → retry with fallback provider
  │
  └─▶ SessionManager ─────────── archives trace + validated artifact
        │  trace.jsonl  (every prompt, tool call, response, redaction event)
        └─ artifact.json (schema-validated, content-addressed)
  │
  ▼
ApiRunResponse { result, usage, session_id, error, classification, needs_confirmation }
```

## Module map

```
src/opspilot/
  api/          FastAPI app and routes: /run /chat /sessions /kb /memory /inventory /intake /admin /health /metrics …
  orchestrator/ Playbook runner: chat loop, tool dispatch, Classification, schema validation
  judgment.py   Judgments (ADR-0040): Question · Judgment · engines; the stage behind OPSPILOT_JUDGMENTS
  providers/    AnthropicProvider · OpenAIProvider (OpenAI, OpenRouter, Gemini, Grok) · OllamaProvider
  kb/           The KB: SqliteStore (FTS5) · LanceStore (vectors) · ingestion · hybrid retrieval · chunk conflicts
  memory/       Memory, the second owned domain (ADR-0031): store, injection, Memory ↔ KB conflicts
  consultation/ Consultations and Working sets (ADR-0032, ADR-0036): pin to Memory, escalation, distillation
  session/      SessionManager · TraceWriter · ArtifactStore · audit log
  inventory/    Assets, the first owned domain (ADR-0017): store, events, CSV, fulfillment drafts
  intake/       Sources and the intake loop: JSM polling, comment write-back (ADR-0013)
  channels/     Telegram and WeCom adapters
  auth/         Users, roles, local / LDAP / OIDC sources (ADR-0020)
  sandbox/      L2 Docker-hardened + L3 gVisor execution engine + approval gate
  mcp/          MCP JSON-RPC 2.0 client — stdio + HTTP transports
  wiki/         ingest · query_to_page · lint · promote — compounding KB layer
  harness/      Fixtures, golden tests, evaluators
  iteration/    Skill feedback, variant evaluation, promotion, lineage
  report/       Reports over archived traces: `opspilot report recurring` (ADR-0039)
  portability/  Knowledge bundles: export / import (ADR-0033)
  tui/          Textual REPL shell with slash commands
  redaction.py  PII scrubbing rules + placeholder injection
  schemas.py    JSON Schema registry + validator
  label_set.py  The label set the Judgments are measured on: drafting and blind labelling (#224)
crates/         Rust hot paths (chunker, tokenizer) via PyO3, with a Python fallback
web/            Svelte 5 frontend (tabbed UI)
playbooks/      YAML playbook specs + system prompts
judgments/      Decision files (answer spaces) and the label set (ADR-0040)
examples/       Frozen e2e scenarios + sample KBs (sample_data_en, …)
deploy/         systemd unit + nginx config for Linux production
```

## Full system design

Six layers form a closed AI task loop:

```
   ┌───────────┐  ┌─────────────────┐  ┌───────────────────────────┐
   │ providers │  │    skills       │  │  kb + memory              │
   │  models   │  │  registry +     │  │  KB: SQLite FTS5 +        │
   │           │  │  distillation   │  │  LanceDB, hybrid search   │
   │           │  │  + tool/MCP     │  │  Memory: admitted facts,  │
   │           │  │  bindings       │  │  on its own anchored path │
   └─────┬─────┘  └────────┬────────┘  └──────────┬────────────────┘
         │ model_ref        │ skill_ref +           │ kb.search results
         ▼                  ▼ tool/mcp bindings     ▼ + Memory entries
    playbooks   ──▶  Session(create) ◀─────────────┘
                            │
                            ▼
                      proposed_action ──▶ sandbox ──▶ artifact
                            │                             │
                            ▼                             ▼
                      Session.trace  ◀────────────  recording
                            │   (a closed Working set, not a Session, is
                            │    what a Skill is distilled from: ADR-0036)
                            ▼
                      harness (eval) ──▶ case-studies
```

- **providers** — pluggable LLM backends (Ollama / OpenRouter / OpenAI / Anthropic / Gemini / Grok); unified auth, capability declarations, cost and fallback
- **skills** — skill registry + authoring + distillation + iteration + tool/MCP bindings; a Skill is drafted from a problem description or distilled from a closed Working set, and admitted only by a commit (ADR-0027, ADR-0036)
- **kb + memory** — the KB holds ingested documents (SQLite FTS5 + LanceDB, fused by RRF); Memory holds the standing facts a person admits, reaches an answer on its own anchor-filtered path, and opens a Conflict when it and the KB disagree (ADR-0031, ADR-0035)
- **wiki** — LLM-maintained synthesis layer on top of the KB: 5 page kinds + cross-links + lint; query answers can be written back as new pages
- **session** — "context + trace + artifact + audit" bundle for every AI task; the carrier for compliance
- **sandbox** — isolated execution layer for AI-proposed actions; L2: Docker hardened (seccomp + cap-drop + RO rootfs); L3: + gVisor `runsc` user-space kernel; default deny-all
- **harness** — unit tests and regression gates for prompts and playbooks; required before model upgrades

> The spec directories under [`docs/specs/`](specs/) define these contracts and
> templates — the schema registry and redaction rules are loaded from there at
> runtime. The working implementation lives under `src/opspilot/`.

## Provider routing

The active playbook declares a primary model plus selectable alternates
(`extra_models`); the first alternate doubles as the runtime fallback when a
chat round errors:

```yaml
model:
  provider_id: anthropic
  kind: anthropic
  name: claude-haiku-4-5-20251001

extra_models:
  - provider_id: anthropic
    kind: anthropic
    name: claude-sonnet-5
  - provider_id: ollama-local
    kind: ollama
    name: gemma4:e4b
```

The UI model selector switches among these per-run without editing YAML.
When a weak tool-calling model (kind `ollama`) is selected, retrieval mode
switches automatically to `prefetch` so it still cites KB chunks correctly.
(The legacy `model.fallback` key is still accepted and promoted into
`extra_models` for backward compatibility.)

## Retrieval modes

| Mode | How it works | Best for |
|------|-------------|----------|
| `tool` | Model decides when to call `kb_search` via tool-use protocol (ReAct loop) | Strong models (Claude, GPT-4) |
| `prefetch` | Orchestrator runs `kb_search` once, injects chunks into system prompt | Weak local models (Gemma, Phi) |

See [ADR-0001](adr/0001-retrieval-mode-prefetch-for-weak-models.md) for the
rationale.
