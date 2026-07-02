# Architecture

How a work item flows through OpsPilot, how the layers fit together, and the
key design decisions. Decision records live in [`docs/adr/`](adr/); the domain
language is defined in [`CONTEXT.md`](../CONTEXT.md).

## Request flow

```
Browser (Svelte 5 / SvelteKit)
  │  POST /api/run { ticket_json, model_id }
  │  GET  /api/models  ·  GET /api/sessions
  ▼
FastAPI  (opspilot.api)
  │  GET /health · GET /metrics (Prometheus)
  │  resolves playbook + provider from model_id
  ▼
Orchestrator  (opspilot.orchestrator)
  ├─▶ Redactor ──────────────── strips PII from work-item text
  │
  ├─▶ KB Search  ─────────────── hybrid retrieval over ingested KB
  │     ├── SqliteStore  (FTS5 full-text search)
  │     └── LanceStore   (LanceDB vector search)
  │           ▲
  │     embedded by OllamaProvider (nomic-embed-text-v2-moe)
  │
  ├─▶ Provider  ──────────────── sends redacted prompt + KB chunks to LLM
  │     ├── AnthropicProvider   (Claude Haiku / Sonnet / Opus)
  │     ├── OpenAIProvider      (OpenAI · OpenRouter · Gemini)
  │     └── OllamaProvider      (local Gemma, Phi, …)
  │           │ ProviderError → retry with fallback provider
  │
  └─▶ SessionManager ─────────── archives trace + validated artifact
        │  trace.jsonl  (every prompt, tool call, response, redaction event)
        └─ artifact.json (schema-validated, content-addressed)
  │
  ▼
ApiRunResponse { result, usage, session_id, error }
```

## Module map

```
src/opspilot/
  api/          FastAPI routes: /run  /config  /models  /sessions  /health  /metrics
  orchestrator/ Playbook runner — chat loop, tool dispatch, schema validate
  providers/    AnthropicProvider · OpenAIProvider · OllamaProvider
  memory/       SqliteStore (FTS5) · LanceStore (vectors) · chunker/tokenizer dispatch
  session/      SessionManager · TraceWriter · ArtifactStore
  redaction/    PII scrubbing rules + placeholder injection
  schemas/      JSON Schema registry + validator
  wiki/         ingest · query_to_page · lint · promote — compounding KB layer
  tui/          Textual TUI shell + 8 screens
  sandbox/      L2 Docker-hardened + L3 gVisor execution engine + approval gate
  mcp/          MCP JSON-RPC 2.0 client — stdio + HTTP transports
web/            Svelte 5 frontend (tabbed UI)
playbooks/      YAML playbook specs + system prompts
examples/       Frozen e2e scenarios + sample KBs (sample_data_en, …)
deploy/         systemd unit + nginx config for Linux production
```

## Full system design

Six layers form a closed AI task loop:

```
   ┌───────────┐  ┌─────────────────┐  ┌───────────────────────────┐
   │ providers │  │    skills       │  │  memory                   │
   │  models   │  │  registry +     │  │  short / mid / long-term  │
   │           │  │  distillation   │  │  SQLite + LanceDB + md    │
   │           │  │  + tool/MCP     │  │  RAG (kb.search /         │
   │           │  │  bindings       │  │       memory.search)      │
   └─────┬─────┘  └────────┬────────┘  └──────────┬────────────────┘
         │ model_ref        │ skill_ref +           │ kb.search results
         ▼                  ▼ tool/mcp bindings     ▼ + memory recall
    playbooks   ──▶  Session(create) ◀─────────────┘
                            │
                            ▼
                      proposed_action ──▶ sandbox ──▶ artifact
                            │                             │
                            ▼                             ▼
                      Session.trace  ◀────────────  recording
                            │   (on archive: distilled → mid-term memory
                            │    + usable as skill distillation source)
                            ▼
                      harness (eval) ──▶ case-studies
```

- **providers** — pluggable LLM backends (Ollama / OpenRouter / OpenAI / Anthropic / Gemini); unified auth, capability declarations, cost and fallback
- **skills** — skill registry + authoring + distillation + iteration + tool/MCP bindings; distil new skills from traces, docs, or other skills
- **memory** — three-tier memory: short-term (in-trace summaries) / mid-term (SQLite + markdown) / long-term (LanceDB + markdown); RAG retrieval and reranking
- **wiki** — LLM-maintained synthesis layer on top of the long-term KB: 5 page kinds + cross-links + lint; query answers can be written back as new pages
- **session** — "context + trace + artifact + audit" bundle for every AI task; the carrier for compliance
- **sandbox** — isolated execution layer for AI-proposed actions; L2: Docker hardened (seccomp + cap-drop + RO rootfs); L3: + gVisor `runsc` user-space kernel; default deny-all
- **harness** — unit tests and regression gates for prompts and playbooks; required before model upgrades

> The spec directories under [`docs/specs/`](specs/) define these contracts and
> templates — the schema registry and redaction rules are loaded from there at
> runtime. The working implementation lives under `src/opspilot/`.

## Provider routing

The active playbook declares a primary model and an optional fallback:

```yaml
model:
  provider_id: anthropic
  kind: anthropic
  name: claude-haiku-4-5-20251001
  fallback:
    provider_id: ollama-local
    kind: ollama
    name: gemma4:e4b
```

The UI model selector overrides the model per-run without editing YAML. When
the fallback (Ollama) is selected, retrieval mode switches automatically to
`prefetch` so weak tool-calling models still cite KB chunks correctly.

## Retrieval modes

| Mode | How it works | Best for |
|------|-------------|----------|
| `tool` | Model decides when to call `kb_search` via tool-use protocol (ReAct loop) | Strong models (Claude, GPT-4) |
| `prefetch` | Orchestrator runs `kb_search` once, injects chunks into system prompt | Weak local models (Gemma, Phi) |

See [ADR-0001](adr/0001-retrieval-mode-prefetch-for-weak-models.md) for the
rationale.
