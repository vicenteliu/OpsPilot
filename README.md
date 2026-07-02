# OpsPilot

**AI-augmented IT ops workbench — spec-driven, multi-provider, local-first**

> 中文版：[README.zh-CN.md](./README.zh-CN.md)

OpsPilot turns raw IT work items — incidents, service requests, tasks — into
structured, KB-cited summaries through a playbook-driven AI pipeline. It runs
fully local with Ollama or against any major cloud provider, and every run
leaves an auditable trail: PII is redacted before anything reaches a model,
output is validated against a strict JSON Schema, and each session archives a
content-addressed artifact plus an append-only trace.

## Highlights

- **Multi-provider** — Anthropic Claude, OpenAI, OpenRouter, Gemini, or local
  Ollama; switch per-run from the UI; playbooks declare a primary model plus a
  local fallback (e.g. Claude → Gemma)
- **KB retrieval with citations** — hybrid vector (LanceDB) + full-text
  (SQLite FTS5) search fused with RRF; `tool` mode (ReAct) for strong models,
  `prefetch` injection for weak local ones
- **Redaction first** — PII stripped before any content reaches a model or
  the KB
- **Auditable sessions** — content-addressed artifacts, append-only traces,
  schema-validated output, browsable history
- **Sandboxed actions** — AI-proposed shell actions run in hardened Docker
  (L2) or gVisor (L3, fail-closed) containers; an approval gate flags risky
  patterns for human sign-off
- **Compounding wiki** — session insights distilled into lint-checked,
  lifecycle-managed wiki pages on top of the long-term KB
- **MCP client** — tools from any Model Context Protocol server (stdio/HTTP)
  injected into the ReAct loop, with per-server allow/denylists
- **Four interfaces** — CLI, 8-module terminal UI (Textual), tabbed web UI
  (Svelte 5) with KB-augmented chat, FastAPI backend
- **Observability** — Prometheus `/metrics`, OTel-compatible JSON logs,
  `/health`
- **Rust hot paths** — chunker (9.6×) and tokenizer (45×) compiled via
  PyO3/maturin, with transparent Python fallback

## Quick start

### Prerequisites

- Python 3.12+
- [Ollama](https://ollama.com) (for local models and embeddings)
- Node.js 18+ and [pnpm](https://pnpm.io) (for the web UI)

### 1. Clone and install

```bash
git clone https://github.com/vicenteliu/OpsPilot.git
cd OpsPilot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Optional but recommended — Rust extensions (10–48× faster chunker/tokenizer;
requires [rustup](https://rustup.rs)):

```bash
make rust-dev
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

### 5. Run

```bash
opspilot tui                              # terminal UI workbench
opspilot serve --reload --with-ui         # API + web UI → http://localhost:5173
```

## Architecture

```
Browser (Svelte 5)          opspilot tui / CLI
        └──────────────┬──────────────┘
                       ▼
              FastAPI (opspilot.api)
                       ▼
                 Orchestrator
   ┌───────────┬───────┴───────┬─────────────┐
   ▼           ▼               ▼             ▼
Redactor   KB Search       Provider     SessionManager
(PII)      (FTS5+vector    (Claude ·    (trace + artifact
            hybrid, RRF)    OpenAI ·     archive)
                            Gemini ·
                            Ollama)
```

Every run: redact → retrieve → generate → validate against JSON Schema →
archive. See [docs/architecture.md](docs/architecture.md) for the full request
flow, the six-layer system design, provider routing, and retrieval modes.

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Request flow, layer design, provider routing, retrieval modes |
| [docs/cli.md](docs/cli.md) | TUI, harness, sandbox, MCP, and wiki command reference |
| [docs/deployment.md](docs/deployment.md) | Docker Compose, systemd, observability, configuration |
| [docs/specs/](docs/specs/) | Spec contracts: schemas + templates (loaded at runtime) |
| [docs/adr/](docs/adr/) | Architecture decision records |
| [ROADMAP.md](ROADMAP.md) | Direction: remote access foundation, Channels, mobile companion |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, quality gates, PR conventions |
| [SECURITY.md](SECURITY.md) | Deployment model, threat model, reporting vulnerabilities |

## Safety

- OpsPilot is **single-user, local-only** today — do not expose the API to
  the internet ([ADR-0002](docs/adr/0002-stage2-single-user-no-auth.md),
  [SECURITY.md](SECURITY.md))
- The redaction layer strips PII from structured work items, but always
  sanitize manually before pasting content into any model or tool
- Cloud API keys are resolved from environment variables — never committed
- Session traces stay local in `~/.opspilot/sessions/`

## License

MIT
