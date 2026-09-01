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

**Contents** · [A quick look](#a-quick-look) · [Why this project](#why-this-project) · [Highlights](#highlights) · [Quick start](#quick-start) · [Design notes](#design-notes) · [Architecture](#architecture) · [Documentation](#documentation) · [Safety](#safety) · [License](#license)

## A quick look

The web UI — dark-first, sidebar-navigated, every answer cited back to the KB:

![OpsPilot web UI](docs/assets/webui.png)

The terminal UI — a REPL with slash commands over the same backend:

![OpsPilot TUI tour](docs/assets/tui.gif)

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
  alternates (down to a local Gemma), switchable per-run or set as a team
  default, with automatic fallback when a provider errors and complexity
  routing that reserves the expensive tier for what needs it. Admins curate
  the alternate list — remove or upgrade models — from the admin module,
  editing the playbook in place; embeddings default to OpenAI, one variable
  away from local Ollama
- **Work-item intake** — polls Jira Service Management on a JQL scope and
  posts the suggestion back as a ticket comment: polling-only (no public
  endpoint), comment-only (no field is ever touched), restart-safe, with an
  offline `--replay` demo; intake can run on a cheaper model, and remote
  deployments push via `POST /api/intake` instead
- **KB retrieval with citations** — hybrid vector (LanceDB) + full-text
  (SQLite FTS5) search fused with RRF; `tool` mode (ReAct) for strong models,
  `prefetch` injection for weak local ones
- **Memory** — the standing facts about your environment that have no table
  of their own: *"never restart the ESXi cluster on a Tuesday evening"*.
  Written by a person with a reason, carrying up to two anchors (an Asset,
  a site), superseded by appending — and cross-checked against the KB,
  opening a **Conflict** when the two disagree ([details](#memory))
- **Consultation** — the surface where an operator actually works a problem,
  grounded in the KB, Memory and Skills; any sentence the assistant says can
  be pinned into Memory in the moment, and a **Working set** carries the
  chase across conversations ([details](#consultation))
- **Asset inventory** — procurement-to-retirement tracking for the devices
  your team manages, with CSV as the migration path in and out, free-set
  statuses, and an append-only event log ([details](#asset-inventory))
- **Runtime Skills** — reusable `SKILL.md` packages the assistant loads on
  demand from a compact trigger catalog; drafted from a problem description
  or distilled from a closed Working set, and admitted only by a commit
  ([details](#runtime-skills))
- **Redaction first** — PII stripped before any content reaches a model or
  the KB
- **Auditable sessions** — content-addressed artifacts, append-only traces,
  schema-validated output, browsable history. Who acted is taken from the
  authenticated caller, never from what the caller claims
- **Proposed actions** — a session may put forward a read-only diagnostic
  with its dry-run preview; it runs only when a person presses execute,
  inside hardened Docker (L2) or gVisor (L3) sandboxes
  ([details](#proposed-actions))
- **Compounding wiki** — session insights distilled into lint-checked,
  lifecycle-managed wiki pages on top of the long-term KB
- **Knowledge bundles** — export the KB, Skills, wiki pages and Memory as
  one archive and restore them elsewhere; per-domain native formats, and no
  vectors travel ([details](#knowledge-bundles))
- **MCP client** — tools from any Model Context Protocol server (stdio/HTTP)
  injected into the ReAct loop, with per-server allow/denylists
- **Interfaces & channels** — CLI, REPL terminal UI (Textual, slash
  commands), tabbed web UI (Svelte 5) with KB-augmented chat, FastAPI
  backend; a Telegram channel brings KB chat and `/intake` to your
  messenger, and WeCom connects both ways — a group robot pushes intake
  suggestions (notify), and a self-built app answers KB questions in chat
  (assist)
- **Multi-user & SSO** — three roles (viewer / operator / admin) against
  local accounts, LDAP/AD, or OIDC SSO with group→role mapping, plus an
  admin module for users, roles, provider status, and audit; machine callers
  use a Service token, secrets stay in the environment — never the
  database — and an all-in-one Docker image makes one `docker run` a
  complete login-gated workbench
- **Observability** — Prometheus `/metrics`, OTel-compatible JSON logs,
  `/health`
- **Rust hot paths** — chunker (~10×) and tokenizer (~45×) compiled via
  PyO3/maturin, with a transparent Python fallback; CI enforces ≥5×

## Quick start

### Prerequisites

- Python 3.12+
- An `OPENAI_API_KEY` for embeddings, or [Ollama](https://ollama.com) to keep
  them local (see [Embeddings](docs/deployment.md#embeddings))
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

### 2. Pull models (only for local inference)

Skip this if you are using cloud models with OpenAI embeddings.

```bash
ollama pull nomic-embed-text-v2-moe   # embeddings; needs OPSPILOT_EMBED_PROVIDER=ollama
ollama pull gemma4:e4b                 # local chat model (optional fallback)
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — two independent choices:
#   Chat      ANTHROPIC_API_KEY (or another cloud key). No cloud key? Pick the
#             local Gemma model from the UI dropdown — retrieval switches to
#             prefetch automatically so weak models still cite the KB.
#   Embedding OPENAI_API_KEY, used by default. To keep embeddings local
#             instead, set OPSPILOT_EMBED_PROVIDER=ollama (step 2).
```

Step 4 needs a working embedder: with neither an OpenAI key nor a reachable
Ollama, ingest fails and says so.

### 4. Ingest a knowledge base

```bash
# Sample English KB (SOPs and runbooks) shipped with the repo:
opspilot ingest examples/sample_data_en/kb/
# Or point it at your own directory of markdown and PDF documents.
```

Markdown and PDF work out of the box. DOCX, PPTX, and XLSX are routed to
markitdown but need its matching extras, which this repo does not pin
(`markitdown[pdf]`) — without them the ingest fails with a converter error.

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
  -e OPENAI_API_KEY=sk-... \
  -v opspilot-data:/home/opspilot/.opspilot \
  opspilot:latest serve --host 0.0.0.0 --port 8000
# → http://localhost:8000, sign in as the bootstrap admin
```

The container needs no Ollama: `ANTHROPIC_API_KEY` answers chat and
`OPENAI_API_KEY` embeds. To use a host Ollama instead, add
`-e OPSPILOT_EMBED_PROVIDER=ollama -e OPSPILOT_OLLAMA_BASE_URL=http://host.docker.internal:11434`.

For a multi-service deployment (nginx TLS termination, JSM intake, optional
Ollama), see [Docker Compose](docs/deployment.md#docker-compose).

## Design notes

The one-line highlights above compress a lot of deliberate design. This
section keeps the full reasoning for the domains OpsPilot owns and the
decisions that are easy to get wrong.

### Memory

The standing facts about your environment that have no table of their own:
*"never restart the ESXi cluster on a Tuesday evening, finance runs its
month-end batch"*. OpsPilot's second owned domain. An entry is **admitted,
never harvested** — a person writes the sentence and the reason, because an
extractor cannot tell a mid-investigation hunch from a conclusion, and a wrong
entry never raises an error, it just quietly steers the assistant. Entries
carry up to two anchors (an Asset, a site) so a constraint about one site
cannot answer a question about another; they are superseded by appending, so
*"we recorded it wrong"* stays distinguishable from *"the world changed"*; and
a stale review date changes the label an entry carries, never whether it
applies. Memory reaches an answer on its own path rather than through hybrid
search — which is what lets the assistant notice when a recorded constraint
and an ingested document contradict each other, and open a **Conflict** for a
human to settle.

### Consultation

The surface where an operator actually works a problem, grounded in the KB,
Memory and Skills. Visible to its author and to admins only, and swept after
90 days, because that is what makes it cheap enough to think out loud in. Any
sentence the assistant says can be **pinned into Memory** with a reason, in
the moment it is said. A **Working set** carries what you are currently
chasing across a chain of conversations — and the address it lives at, which
is what lets anchored Memory reach an answer at all. It closes by hand, with
an unconditional inactivity fallback that announces itself, because nobody
returns to press "close" at the moment a problem is solved. To *act* on what
a conversation found, it escalates into a Session, carrying a work-item
description and nothing else.

### Asset inventory

Procurement-to-retirement tracking for the devices your team manages, and the
first domain OpsPilot came to *own* rather than mirror: small teams have no CMDB, so
CSV import/export is the migration path in and out. Eight free-set statuses
(no state machine — real inventories are full of corrections), an append-only
event log whose actor comes from the authenticated caller, and a fulfillment
playbook that drafts Assets straight from a Service Request.

### Runtime Skills

Reusable `SKILL.md` packages the assistant loads on demand: it sees a compact
catalog of triggers and pulls in the full procedure when a problem matches,
with retrieval-injection fallback for models too weak to call tools. Admins
can have one drafted from a problem description, or distilled from a **closed
Working set** — a problem opened, worked across several conversations, and
finished. The draft keeps the dead ends, because knowing what to rule out and
in what order is the useful half of a procedure, and it leaves the stopping
condition and the tools list **blank on purpose**: a run that went well never
exercised either, and a plausible guess gets skimmed and merged where a blank
cannot. Nothing is admitted by arriving — moving a draft into `agent_skills/`
is a commit, and that commit is the admission.

### Proposed actions

A session may put forward a read-only diagnostic with its dry-run preview and
the approval gate's verdict, and **it runs only when a person presses
execute**; request, preview, verdict, actor and outcome all append to the
session's trace. The first batch is diagnostics and contains no mutation at
all — that constraint lives in the artifact schema, where the intent is a
constant, so a mutating action cannot be expressed. Widening it later is a
visible, reviewable diff. Execution happens in hardened Docker (L2) or gVisor
(L3, fail-closed) containers; the approval gate flags risky patterns but is a
defence-in-depth signal, not the boundary — the sandbox is.

### Knowledge bundles

Export the KB, Skills, wiki pages and Memory as one archive and restore them
elsewhere. Per-domain native formats, not a uniform envelope: Skills and wiki
pages stay files, because a Skill is admitted through a pull request and a
pull request has to read as a diff. No vectors travel — they are bound to an
embedding model, so the receiver re-ingests. Sessions and Consultations
deliberately have **no** export: an append-only ledger stops being one the
moment it becomes a file anyone can edit.

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
