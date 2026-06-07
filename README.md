# OpsPilot

**AI-augmented IT ops workbench — spec-driven, multi-provider, local-first**

> 中文版：[README_zh.md](./README_zh.md)

OpsPilot turns raw IT tickets into structured, KB-cited summaries using a playbook-driven AI pipeline. It runs locally with Ollama or against any cloud provider (Anthropic, OpenAI, OpenRouter, Gemini), with a terminal UI, a tabbed Svelte 5 web UI, a KB-augmented chat interface, and a FastAPI backend wired to MCP servers (filesystem, Notion, and more).

---

## Features

- **Multi-provider** — Anthropic Claude, OpenAI, OpenRouter, Gemini, or local Ollama; switch from the UI dropdown without restarting
- **Fallback routing** — playbook declares a primary model + optional local fallback (e.g. Claude → Gemma)
- **KB retrieval** — hybrid vector (LanceDB) + full-text search (SQLite FTS5) over an ingested knowledge base; citations traced to source chunks
- **Retrieval modes** — `tool` (model calls `kb_search` via ReAct loop) or `prefetch` (orchestrator injects chunks before the LLM call); prefetch makes weak local models (Gemma, Phi) reliably cite KB chunks
- **Redaction** — PII stripped before any content reaches the model or the KB
- **Session audit** — every run produces a content-addressed artifact (`art_<sha256>`) + an append-only, seq-stamped trace; sessions are archived and browsable
- **Schema validation** — model output validated against a strict JSON Schema before it's accepted
- **Token usage display** — input/output token counts shown after each run
- **Session history** — past runs listed inline with expandable output cards for side-by-side comparison
- **Terminal UI (TUI)** — 8-module Textual workbench: dashboard, sessions, KB browser, wiki tree, harness, lint issues, providers, config; run playbooks inline with `R`; generate wiki pages from sessions with `W`; promote draft wiki pages with `P`
- **Wiki layer** — compounding knowledge base built on top of the long-term KB: ingest KB docs into wiki summary pages, auto-generate synthesis pages from qualifying session responses, lint for orphans/broken links/redaction warnings, promote pages through a `draft → reviewed → live → stale → archived` lifecycle
- **Sandbox (L2 / L3)** — Docker-hardened action execution with seccomp, cap-drop, read-only rootfs, no host mounts, and `--network=none` by default; the real blast-radius boundary is the ephemeral container + network policy. **L3** adds gVisor (`--runtime=runsc`) for user-space-kernel isolation of suspicious-input workloads — selected per-run with `--level l3`, and **fail-closed** (refuses to run rather than downgrade to L2 if `runsc` is unregistered); see [ADR-0009](docs/adr/0009-sandbox-l3-gvisor-over-firecracker.md). An approval gate *flags* risky patterns (`rm -rf`, `DROP TABLE`, fork bombs, prod-env or network-opening actions) for human sign-off — a defense-in-depth signal, not a boundary (see [ADR-0005](docs/adr/0005-approval-gate-is-defense-signal-not-boundary.md)); dry-run preview before committing any action
- **KB-augmented chat** — conversational tab in the web UI; hybrid KB search injected into every turn; streams responses via SSE
- **MCP client** — JSON-RPC 2.0 client for Model Context Protocol servers (stdio and HTTP transports); MCP tools injected into the orchestrator's ReAct loop alongside `kb_search`; per-server allowlist/denylist; `${VAR:-default}` env expansion; best-effort inline-secret detection across env/args/url/headers (a footgun guard, not a guarantee — keep secrets in the environment)
- **Observability** — Prometheus-format `/metrics` endpoint, structured JSON logging (OTel-compatible), `/health` with uptime and version
- **Rust extensions** — `opspilot_chunker` (9.6× faster than pure Python) and `opspilot_tokenizer` (45× faster BPE-ish token counter) compiled via PyO3/maturin

---

## Quick start

### Prerequisites

- Python 3.12+
- [Ollama](https://ollama.com) (for local models and embeddings)
- Node.js 18+ and [pnpm](https://pnpm.io)

### 1. Clone and install

```bash
git clone https://github.com/vicenteliu/OpsPilot.git
cd OpsPilot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

**Rust extensions (optional but recommended — 10–48× faster chunker and tokenizer):**

```bash
# Requires Rust toolchain: https://rustup.rs
make rust-dev        # builds debug .so into the venv
# or for a release wheel:
make rust-build
```

`make install` auto-detects `cargo` and runs `make rust-dev`; if Rust is absent the Python fallback is used transparently.

### 2. Pull models

```bash
ollama pull nomic-embed-text-v2-moe   # embedding model (required)
ollama pull gemma4:e4b                 # local chat model (optional fallback)
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY or other cloud keys if using cloud providers
```

### 4. Ingest the knowledge base

```bash
opspilot kb ingest kb/
```

### 5. Launch the terminal UI

```bash
opspilot tui                                      # interactive workbench
opspilot tui run --input ticket.json              # open run modal directly
```

### 6. Start the API server + web UI

```bash
source .env
opspilot serve --reload --with-ui                 # API + frontend together (Ctrl+C stops both)
opspilot serve --reload                           # API only
opspilot serve --host 0.0.0.0 --workers 2 --json-logs   # production (no frontend)
```

Open [http://localhost:5173](http://localhost:5173).

---

## Architecture

### Request flow

```
Browser (Svelte 5 / SvelteKit)
  │  POST /api/run { ticket_json, model_id }
  │  GET  /api/models  ·  GET /api/sessions
  ▼
FastAPI  (opspilot.api)
  │  GET /health · GET /metrics (Prometheus)
  │  resolves playbook + provider from model_id
  ▼
Orchestrator  (opspilot.orchestrator.ticket_summary)
  ├─▶ Redactor ──────────────── strips PII from ticket text
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
        └─ artifact.json (schema-validated ticket_summary_v1)
  │
  ▼
ApiRunResponse { result, usage, session_id, error }
  │
  ▼
Browser  — renders output cards + token count badge
           history table loads past sessions on demand
```

### Module map

```
src/opspilot/
  api/          FastAPI routes: /run  /config  /models  /sessions  /health  /metrics
  orchestrator/ Playbook runner — chat loop, tool dispatch, schema validate
  providers/    AnthropicProvider · OpenAIProvider · OllamaProvider
  memory/       SqliteStore (FTS5) · LanceStore (vectors)
  session/      SessionManager · TraceWriter · ArtifactStore
  redaction/    PII scrubbing rules + placeholder injection
  schemas/      JSON Schema registry + validator
  wiki/         ingest · query_to_page · lint · promote — compounding KB layer
  tui/          Textual TUI shell + 8 screens + RunModal + WikiQueryModal
  sandbox/      L2 Docker-hardened + L3 gVisor execution engine + approval gate
  mcp/          MCP JSON-RPC 2.0 client — stdio + HTTP transports
web/            Svelte 5 frontend (7-tab UI: Run / Chat / KB / Wiki / VendorDoc / MCP / Iteration)
playbooks/      YAML playbook specs + system prompts
kb/             Source documents for KB ingestion
deploy/         systemd unit + nginx config for Linux production
```

### Full system design (Providers × Skills × Memory × Session × Sandbox × Harness)

The six layers form a closed AI task loop:

```
   ┌───────────┐  ┌─────────────────┐  ┌───────────────────────────┐
   │ providers/│  │    skills/      │  │  memory/                  │
   │  models   │  │  registry +     │  │  short / mid / long-term  │
   │           │  │  distillation   │  │  SQLite + LanceDB + md    │
   │           │  │  + tool/MCP     │  │  RAG (kb.search /         │
   │           │  │  bindings       │  │       memory.search)      │
   └─────┬─────┘  └────────┬────────┘  └──────────┬────────────────┘
         │ model_ref        │ skill_ref +           │ kb.search results
         ▼                  ▼ tool/mcp bindings     ▼ + memory recall
    playbooks/  ──▶  Session(create) ◀─────────────┘
                            │
                            ▼
                      proposed_action ──▶ sandbox/ ──▶ artifact
                            │                              │
                            ▼                              ▼
                      Session.trace  ◀────────────  recording
                            │   (on archive: distilled → mid-term memory
                            │    + usable as skill distillation source)
                            ▼
                      harness/ (eval) ──▶ case-studies/
```

- **providers/** — pluggable LLM backends (Ollama / OpenRouter / OpenAI / Anthropic / Gemini); unified auth, capability declarations, cost and fallback
- **skills/** — skill registry + authoring + distillation + iteration + tool/MCP bindings; distil new skills from traces, docs, or other skills; evolve via lineage, variants, and feedback signals
- **memory/** — three-tier memory: short-term (in-trace summaries) / mid-term (SQLite + markdown) / long-term (LanceDB + markdown); RAG retrieval and reranking
- **wiki/** — LLM-maintained synthesis layer on top of the long-term KB: 5 page kinds + cross-links + lint; query answers can be written back as new pages, forming a compounding insight loop
- **session/** — "context + trace + artifact + audit" bundle for every AI task; the carrier for compliance
- **sandbox/** — isolated execution layer for AI-proposed actions ("show me before committing"); L2: Docker hardened (seccomp + cap-drop + RO rootfs); L3: + gVisor `runsc` user-space kernel; default deny-all
- **harness/** — unit tests and regression gates for prompts and playbooks; required before model upgrades

> The spec-only directories (`providers/`, `skills/`, `wiki/`, `session/`, `sandbox/`, `harness/` at repo root) define these contracts and templates. The working implementation lives under `src/opspilot/`.

### Provider routing

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

The UI model selector lets you override the model per-run without editing YAML. When the fallback (Ollama) is selected, retrieval mode switches automatically to `prefetch` so weak tool-calling models still cite KB chunks correctly.

### Retrieval modes

| Mode | How it works | Best for |
|------|-------------|----------|
| `tool` | Model decides when to call `kb_search` via tool-use protocol (ReAct loop) | Strong models (Claude, GPT-4) |
| `prefetch` | Orchestrator runs `kb_search` once, injects chunks into system prompt | Weak local models (Gemma, Phi) |

---

## Terminal UI

Launch with `opspilot tui`. Press keys `1`–`8` to jump between modules.

| Key | Module | Description |
|-----|--------|-------------|
| `1` | Dashboard | Session/KB/wiki counts |
| `2` | Sessions | All runs; `W` → generate wiki page from selected session |
| `3` | KB Browser | Ingested documents and chunk counts |
| `4` | Wiki Tree | All wiki pages; `P` → promote selected draft/reviewed page to live |
| `5` | Harness | Eval run history |
| `6` | Lint Issues | Wiki lint results (orphans, broken links, redaction warnings) |
| `7` | Providers | Ollama / Anthropic / OpenAI connectivity status |
| `8` | Config | Active configuration values |
| `R` | — | Open Run modal (any screen) |
| `Q` | — | Quit |

```bash
opspilot tui run --input ticket.json --playbook playbooks/pb_ticket_summary_zh
```

---

## Harness CLI

```bash
# Run a single fixture against a playbook
opspilot harness run \
  --fixture examples/scn_ticket_summary_zh/harness/fixture.json \
  --golden  examples/scn_ticket_summary_zh/harness/golden.json \
  --playbook playbooks/pb_ticket_summary_zh \
  --output results.jsonl

# Stage 1 golden test (Anthropic baseline, weighted_score ≈ 0.968)
opspilot harness golden

# Stage 4 OpenRouter golden test (delta < 0.1 exit criterion)
opspilot harness golden-openrouter  # requires OPENROUTER_API_KEY

# Stage 5 Gemini golden test
opspilot harness golden-gemini      # requires GEMINI_API_KEY
```

Golden test scores vs baseline (threshold: delta < 0.1):

| Provider | Model | weighted_score | delta |
|---|---|---|---|
| Anthropic | claude-sonnet-4-6 | 0.968 | — baseline |
| OpenRouter | claude-haiku-4-5 (via OR) | 0.983 | 0.015 ✅ |
| Gemini | gemini-2.5-flash | 0.983 | 0.015 ✅ |

---

## Sandbox CLI

The sandbox runs AI-proposed shell actions in a Docker L2 container (seccomp + `--cap-drop=ALL` + read-only rootfs). An approval gate blocks patterns like `rm -rf`, `DROP TABLE`, `chmod 777`, and fork bombs.

```bash
# Preview an action (no execution) — prints the exact docker argv
opspilot sandbox dry-run examples/sandbox_shell_l2/action.yaml

# Execute (requires Docker; dangerous patterns require --approve)
opspilot sandbox run examples/sandbox_shell_l2/action.yaml
opspilot sandbox run examples/sandbox_shell_l2/action.yaml --approve
```

### L3 (gVisor)

Add `--level l3` to either command to route execution through gVisor's
`runsc` runtime instead of the host kernel — the L2 hardening flags are all
retained, with a stronger isolation boundary on top ([ADR-0009](docs/adr/0009-sandbox-l3-gvisor-over-firecracker.md)).

```bash
# Dry-run shows the injected --runtime=runsc in the docker argv
opspilot sandbox dry-run --level l3 examples/sandbox_shell_l2/action.yaml

# Execute under gVisor (requires runsc registered with the Docker daemon)
opspilot sandbox run --level l3 examples/sandbox_shell_l2/action.yaml
```

L3 is **fail-closed**: if `runsc` is not registered in `/etc/docker/daemon.json`,
the run is refused with an explicit error rather than silently downgrading to L2.
Host setup (install `runsc`, register the runtime) is documented in
[`sandbox/backends/README.md` §3](sandbox/backends/README.md).

---

## MCP CLI

```bash
# List all enabled MCP servers and their available tools
opspilot mcp list --config mcp-config.yaml

# Connect to a single server and report health
opspilot mcp probe --config mcp-config.yaml --server fs-readonly
```

MCP tools are injected into the orchestrator's ReAct loop automatically when `mcp-config.yaml` is present at startup — no playbook changes needed. Config example:

```yaml
version: "1.0.0"
mcps:
  - id: fs-readonly
    name: "Filesystem (read-only)"
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "${WORKSPACE_ROOT:-/workspace}"]
    tools_prefix: "mcp__fs__"
    tools_allowlist: ["read_file", "list_directory"]
    enabled: true
    trust: trusted

  - id: notion-main
    name: "Notion (main workspace)"
    transport: stdio
    command: npx
    args: ["-y", "@notionhq/notion-mcp-server"]
    env:
      NOTION_TOKEN: "${NOTION_API_KEY}"
    tools_prefix: "mcp__notion__"
    tools_denylist: ["delete_page", "delete_database"]
    enabled: true
    trust: trusted
```

---

## Wiki CLI

The wiki layer converts KB documents and session responses into a browsable,
lint-checked, lifecycle-managed knowledge base.

```bash
# Ingest a KB document into a wiki summary page
opspilot wiki ingest <doc_id>

# Convert qualifying archived sessions into synthesis pages (auto-scan)
opspilot wiki query-to-page
opspilot wiki query-to-page --session sess_<id>   # single session

# Promote a draft page through the lifecycle
opspilot wiki promote <slug>                       # draft → live (default)
opspilot wiki promote <slug> --to reviewed         # draft → reviewed

# Lint the wiki for structural issues
opspilot wiki lint
```

**Wiki page lifecycle:** `draft` → `reviewed` → `live` → `stale` → `archived`

Pages are always written as `draft` by automated tools. Human review (CLI or TUI `P`) promotes them to `live`.

---

## Production deployment

### Docker Compose

```bash
cp .env.example .env   # add API keys
docker compose -f docker-compose.prod.yml up -d
curl http://localhost:8000/health
```

### systemd (Linux)

```bash
sudo cp deploy/systemd/opspilot.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now opspilot
```

See [`deploy/systemd/README.md`](deploy/systemd/README.md) for full setup instructions.

### Observability

| Endpoint | Description |
|---|---|
| `GET /health` | Status, version, uptime |
| `GET /metrics` | Prometheus-format counters and histograms |

Structured JSON logging (OTel-compatible) is enabled with `--json-logs`:

```bash
opspilot serve --json-logs 2>&1 | jq .
# {"ts":"2026-05-05T10:00:00Z","severity":"INFO","logger":"opspilot.api","msg":"GET /health 200 1ms"}
```

---

## Configuration

All settings live in `~/.opspilot/config.yaml` (optional) or environment variables. See `.env.example` for the full list.

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Anthropic cloud API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OPENROUTER_API_KEY` | — | OpenRouter API key |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `OPSPILOT_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama base URL |
| `OPSPILOT_OLLAMA_TIMEOUT_S` | `300` | Ollama request timeout (s). Raise for large local models (e.g. `gemma4:12b`) that are slow to cold-load. |
| `OPSPILOT_HOME` | `~/.opspilot` | State directory (KB, sessions, audit) |

---

## Running tests

```bash
pytest                              # all tests (733 tests)
pytest -m "not requires_ollama"     # skip tests that need a live Ollama instance
make bench                          # Rust vs Python speedup benchmarks (must be ≥ 5×)
```

---

## Repository structure

```
.
├── src/opspilot/       # Python package (API, orchestrator, providers, memory, …)
│   ├── api/            #   FastAPI app + routes + middleware (health, metrics)
│   ├── orchestrator/   #   Ticket summary playbook runner
│   ├── providers/      #   Anthropic · OpenAI-compat (OpenAI/OpenRouter/Gemini) · Ollama
│   ├── memory/         #   SqliteStore (FTS5) + LanceStore (vectors) + chunker/tokenizer dispatch
│   ├── session/        #   SessionManager · TraceWriter · ArtifactStore
│   ├── sandbox/        #   L2 Docker-hardened + L3 gVisor execution engine + approval gate
│   ├── mcp/            #   MCP JSON-RPC 2.0 client (stdio + HTTP)
│   ├── wiki/           #   Wiki ingest · query-to-page · lint · promote
│   └── tui/            #   Textual terminal UI
├── crates/             # Rust extensions (PyO3 / maturin)
│   ├── opspilot-core/      #   Shared Rust types: chunker + tokenizer algorithms
│   ├── opspilot-chunker/   #   Python binding — chunk_markdown() (9.5× Python)
│   └── opspilot-tokenizer/ #   Python binding — count_tokens() (48× Python)
├── web/                # Svelte 5 frontend
├── benchmarks/         # Rust vs Python timing benchmarks (exit 1 if < 5×)
├── playbooks/          # Playbook YAML + system prompts
├── kb/                 # Source documents for KB ingestion
├── tests/              # pytest test suite (733 tests)
├── deploy/             # systemd unit + nginx config
├── docker-compose.prod.yml
├── .env.example        # Environment variable reference
│
│  # ── Spec-only directories (contracts and templates, no running implementation) ──
├── providers/          # LLM provider spec + catalog
├── skills/             # Skill registry, authoring, distillation, iteration spec
├── wiki/               # LLM-maintained compounding wiki spec
├── memory/             # Memory + RAG pipeline spec (separate from src/opspilot/memory/)
├── session/            # Session & trace spec
├── sandbox/            # Sandboxed action execution spec
└── harness/            # Eval & regression harness spec
```

> The top-level `providers/`, `skills/`, `wiki/`, `session/`, `sandbox/`, and `harness/` directories are **specification and template** artifacts. The working implementation lives under `src/opspilot/`.

---

## Safety notes

- **Never paste PII, credentials, or internal secrets** into any model or tool. The redaction layer handles structured tickets, but always sanitize manually first.
- Cloud API keys are resolved from environment variables — never committed to the repository.
- All session traces are stored locally in `~/.opspilot/sessions/`.
- The sandbox approval gate blocks irreversible or destructive shell patterns by default; use `--force-approve` only when you have reviewed the dry-run output.

---

## License

MIT
