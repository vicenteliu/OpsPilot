# OpsPilot

**AI-augmented IT ops workbench — spec-driven, multi-provider, local-first**

> 中文版：[README_zh.md](./README_zh.md)

OpsPilot turns raw IT tickets into structured, KB-cited summaries using a playbook-driven AI pipeline. It runs locally with Ollama or against any cloud provider (Anthropic, OpenAI, OpenRouter, Gemini), with a Svelte 5 web UI and a FastAPI backend.

---

## Features

- **Multi-provider** — Anthropic Claude, OpenAI, OpenRouter, Gemini, or local Ollama; switch from the UI dropdown without restarting
- **Fallback routing** — playbook declares a primary model + optional local fallback (e.g. Claude → Gemma)
- **KB retrieval** — hybrid vector (LanceDB) + full-text search (SQLite FTS5) over an ingested knowledge base; citations traced to source chunks
- **Redaction** — PII stripped before any content reaches the model or the KB
- **Session audit** — every run produces a signed trace + artifact; sessions are archived and browsable
- **Schema validation** — model output validated against a strict JSON Schema before it's accepted
- **Token usage display** — input/output token counts shown after each run
- **Session history** — past runs listed inline with expandable output cards for side-by-side comparison

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

### 5. Start the API server

```bash
source .env  # or: set -a && source .env && set +a
uvicorn opspilot.api.app:app --reload
```

### 6. Start the web UI

```bash
cd web && pnpm install && pnpm dev
```

Open [http://localhost:5173](http://localhost:5173).

---

## Architecture

```
web/          Svelte 5 + SvelteKit frontend (SSR disabled, local tool)
src/opspilot/
  api/        FastAPI app — /api/run, /api/config, /api/models, /api/sessions
  orchestrator/  Playbook runner: redact → retrieve → chat loop → validate → archive
  providers/  LLM provider abstraction (Anthropic, OpenAI-compat, Ollama)
  memory/     SQLite (FTS5) + LanceDB vector store
  session/    Session lifecycle, trace writer, artifact storage
  redaction/  PII scrubbing before model / KB ingestion
  schemas/    JSON Schema registry + validator
playbooks/    YAML playbook specs + system prompts
kb/           Source documents for KB ingestion
```

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

## Configuration

All settings live in `~/.opspilot/config.yaml` (optional) or environment variables. See `.env.example` for the full list.

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Anthropic cloud API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OPENROUTER_API_KEY` | — | OpenRouter API key |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `OPSPILOT_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama base URL |
| `OPSPILOT_HOME` | `~/.opspilot` | State directory (KB, sessions, audit) |

---

## Running tests

```bash
pytest                        # all tests
pytest -m "not requires_ollama"  # skip tests that need a live Ollama instance
```

---

## Repository structure

```
.
├── src/opspilot/       # Python package (API, orchestrator, providers, memory, …)
├── web/                # Svelte 5 frontend
├── playbooks/          # Playbook YAML + system prompts
├── kb/                 # Source documents for KB ingestion
├── tests/              # pytest test suite
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

---

## License

MIT
