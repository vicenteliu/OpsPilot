<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-on-dark.svg">
    <img src="docs/assets/logo-on-light.svg" alt="" width="37" height="23">
  </picture>&nbsp; OpsPilot
</h1>

**AI-augmented IT ops workbench — spec-driven, multi-provider, multi-user, local-first**

[![CI](https://github.com/vicenteliu/OpsPilot/actions/workflows/ci.yml/badge.svg)](https://github.com/vicenteliu/OpsPilot/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![License: Apache--2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

> 中文版：[README.zh-CN.md](./README.zh-CN.md)

OpsPilot turns raw IT work items — incidents, service requests, tasks — into
structured, KB-cited suggestions through a playbook-driven AI pipeline, and
closes the loop with the tools you already use: it polls new tickets straight
from Jira Service Management and posts the suggestion back as a comment, and
files a Telegram message as a work item with a single command. It runs fully
local with Ollama or against any major cloud provider, and every run leaves
an auditable trail: PII is redacted before anything reaches a model, output
is validated against a strict JSON Schema, and each session archives a
content-addressed artifact plus an append-only trace.

## Why this project

AI is reshaping the IT-support industry. OpsPilot is a working answer to a
concrete question: **given what today's LLMs can actually do, what does a
practical work-assistance layer for IT support look like?**

- Today's models are already good enough to draft incident summaries,
  decompose work into routable tasks, and pull up the right runbook — *if*
  every claim is grounded in a knowledge base and every run is auditable.
  That grounding and auditability are exactly what OpsPilot builds.
- Model capability keeps compounding, and OpsPilot is built to ride that
  curve rather than chase it: playbooks pin model versions, a regression
  harness gates every upgrade, and the spec-driven contracts make adopting a
  stronger model a config change, not a rewrite.
- The human stays in charge: OpsPilot suggests severities, tiers, and
  actions; your system of record — and your engineers — make the decisions.

## Highlights

- **Multi-provider** — Anthropic Claude, OpenAI, OpenRouter, Gemini, xAI
  Grok, or local Ollama; playbooks declare a primary model plus selectable
  alternates (down to a local Gemma), switchable per-run from the UI or set
  as a team default in the admin module, with automatic fallback when a
  provider errors. Admins can curate the selectable list itself — remove or
  upgrade models — from the admin module, editing the playbook in place.
  Embeddings default to local Ollama and fall back to
  OpenAI (with a visible notice) when Ollama is unavailable. Playbooks can
  route by complexity, sending the easy majority to a cheap tier and
  escalating only what needs it
- **Work-item intake** — pull tickets straight from Jira Service Management
  on a JQL scope and post the AI suggestion back as a comment on the ticket:
  polling-only (no public endpoint), comment-only (no field is ever touched),
  restart-safe state, and a `--replay` mode that demos the whole loop
  offline; intake can run on a cheaper model than interactive use, and
  remote deployments can push instead via `POST /api/intake`
- **KB retrieval with citations** — hybrid vector (LanceDB) + full-text
  (SQLite FTS5) search fused with RRF; `tool` mode (ReAct) for strong models,
  `prefetch` injection for weak local ones
- **Asset inventory** — procurement-to-retirement tracking for the devices
  your team manages, and the one domain OpsPilot *owns* rather than mirrors:
  small teams have no CMDB, so CSV import/export is the migration path in and
  out. Eight free-set statuses (no state machine — real inventories are full
  of corrections), an append-only event log whose actor comes from the
  authenticated caller, and a fulfillment playbook that drafts Assets straight
  from a Service Request
- **Runtime Skills** — reusable `SKILL.md` packages the assistant loads on
  demand: it sees a compact catalog of triggers and pulls in the full
  procedure when a problem matches, with retrieval-injection fallback for
  models too weak to call tools. Admins can have one drafted from a problem
  description and edit it before saving
- **Redaction first** — PII stripped before any content reaches a model or
  the KB
- **Auditable sessions** — content-addressed artifacts, append-only traces,
  schema-validated output, browsable history. Who acted is taken from the
  authenticated caller, never from what the caller claims
- **Sandboxed actions** — AI-proposed shell actions run in hardened Docker
  (L2) or gVisor (L3, fail-closed) containers; an approval gate flags risky
  patterns for human sign-off
- **Compounding wiki** — session insights distilled into lint-checked,
  lifecycle-managed wiki pages on top of the long-term KB
- **MCP client** — tools from any Model Context Protocol server (stdio/HTTP)
  injected into the ReAct loop, with per-server allow/denylists
- **Interfaces & channels** — CLI, REPL terminal UI (Textual, slash
  commands), tabbed web UI (Svelte 5) with KB-augmented chat, FastAPI
  backend; a Telegram channel brings the KB chat into your messenger and
  files work items with `/intake`; WeCom connects both ways — a group robot
  pushes intake suggestions (notify), and a self-built app answers KB
  questions in chat (assist)
- **Multi-user & SSO** — login-gated web UI with three roles
  (viewer / operator / admin); authenticate against local accounts,
  LDAP / Active Directory, or OIDC SSO, with group→role mapping and an
  admin module for users, roles, provider status, and audit. Machine
  callers (channels, intake) use a Service token; secrets stay in the
  environment, never the database. Ships as an all-in-one Docker image —
  one `docker run` is a complete, login-gated workbench
- **Observability** — Prometheus `/metrics`, OTel-compatible JSON logs,
  `/health`
- **Rust hot paths** — chunker (~10×) and tokenizer (~45×) compiled via
  PyO3/maturin, with a transparent Python fallback; CI enforces ≥5×

## A quick look

The web UI — dark-first, sidebar-navigated, every answer cited back to the KB:

![OpsPilot web UI](docs/assets/webui.png)

The terminal UI — a REPL with slash commands over the same backend:

![OpsPilot TUI tour](docs/assets/tui.gif)

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

Optional but recommended — Rust extensions (~10–45× faster chunker/tokenizer;
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
# Edit .env — add ANTHROPIC_API_KEY or other cloud keys if using cloud providers.
# No cloud key? Pick the local Gemma model from the UI dropdown — retrieval
# switches to prefetch automatically so weak models still cite the KB.
```

### 4. Ingest a knowledge base

```bash
# Sample English KB (SOPs and runbooks) shipped with the repo:
opspilot ingest examples/sample_data_en/kb/
# Or point it at your own directory of markdown/PDF/DOCX documents.
```

### 5. Run

```bash
opspilot tui                              # terminal UI workbench
opspilot serve --reload --with-ui         # API + web UI → http://localhost:5173
```

Then see the whole intake loop offline — no ticket system needed:

```bash
opspilot source jsm --replay tests/fixtures/jsm_replay/
cat intake_comments/IT-101.md             # the suggestion a real ticket would get
```

From here: submit a work item on the **Run** tab, ask the KB a question on
the **Chat** tab, connect a [Telegram channel](docs/channels.md) to chat
with your KB (or file a work item with `/intake`) from your phone, or point
intake at your [Jira Service Management project](docs/sources.md) — a
free-tier site connects in about ten minutes — so new tickets get summarised
and commented automatically.

### Or: one container (all-in-one)

The image bundles the built web UI, so a single container is a complete,
login-gated workbench ([docs/deployment.md](docs/deployment.md)):

```bash
docker build -t opspilot:latest .
docker run -p 8000:8000 \
  -e OPSPILOT_API_TOKEN="$(openssl rand -hex 32)" \
  -e OPSPILOT_BOOTSTRAP_ADMIN=admin -e OPSPILOT_BOOTSTRAP_PASSWORD='<strong-pw>' \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e OPSPILOT_OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v opspilot-data:/home/opspilot/.opspilot \
  opspilot:latest serve --host 0.0.0.0 --port 8000
# → http://localhost:8000, sign in as the bootstrap admin
```

## Architecture

![OpsPilot system architecture](docs/assets/architecture.png)

![OpsPilot execution flow](docs/assets/workflow.png)

Every run: redact → retrieve → generate → validate against JSON Schema →
archive. See [docs/architecture.md](docs/architecture.md) for the full request
flow, the six-layer system design, provider routing, and retrieval modes.

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Request flow, layer design, provider routing, retrieval modes |
| [docs/cli.md](docs/cli.md) | TUI, harness, sandbox, MCP, and wiki command reference |
| [docs/deployment.md](docs/deployment.md) | Docker Compose, systemd, observability, configuration |
| [docs/channels.md](docs/channels.md) | Messaging channels — Telegram setup: KB chat + `/intake` |
| [docs/sources.md](docs/sources.md) | Work-item intake — JSM setup, replay mode, state and reruns |
| [docs/inventory.md](docs/inventory.md) | Asset model, statuses, event log, CSV migration, REST surface |
| [docs/verification.md](docs/verification.md) | Post-deployment checks for LDAP, OIDC, WeCom and the all-in-one image |
| [docs/specs/](docs/specs/) | Spec contracts: schemas + templates (loaded at runtime) |
| [docs/adr/](docs/adr/) | Architecture decision records |
| [CONTEXT.md](CONTEXT.md) | Domain glossary — the canonical name for every concept above |
| [ROADMAP.md](ROADMAP.md) | What is shipped, what is open, what is deferred |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, quality gates, PR conventions |
| [SECURITY.md](SECURITY.md) | Deployment model, threat model, reporting vulnerabilities |

## Safety

- **Multi-user with three roles** (viewer / operator / admin) via local
  accounts, LDAP/AD, or OIDC SSO. Loopback dev stays friction-free; remote
  binding is fail-closed on a token, with TLS in front; machine callers use
  a Service token
  ([ADR-0020](docs/adr/0020-multi-user-auth-three-roles-three-sources.md),
  [ADR-0011](docs/adr/0011-remote-access-bearer-token-proxy-tls.md),
  [SECURITY.md](SECURITY.md))
- **Secrets stay in the environment** — cloud API keys and LDAP/OIDC
  credentials are read from env vars, never committed and never stored in
  the database; the admin module shows status, not secrets
- The redaction layer strips PII from structured work items, but always
  sanitize manually before pasting content into any model or tool
- Session traces and all state stay local under `~/.opspilot/`

## License

[Apache-2.0](LICENSE)
