# Stage 1 Dev Quickstart

> Stage 1 = Python core + CLI + schema validation tooling. This guide gets a
> fresh checkout to "passing PR-1 quality gate" in ~5 minutes.

## Prerequisites (macOS)

```bash
brew install python@3.12
# Optional but recommended:
brew install pyenv direnv shellcheck
```

If you use `pyenv`:

```bash
pyenv install 3.12.7   # any 3.12.x
pyenv local 3.12.7     # respects .python-version in repo root
```

## Install

```bash
make install
source .venv/bin/activate
```

This runs:

1. `python3.12 -m venv .venv`
2. `pip install -e ".[dev]"`

## Verify PR-1 quality gate

```bash
make ci
# == lint + typecheck + test + validate
```

Each step should print green. The four gates:

* `make lint` — ruff (style + bugbear + import sort)
* `make typecheck` — mypy strict on `src/`
* `make test` — unit tests, including the auto-parametrized "every example
  validates against its schema" suite
* `make validate` — runs `opspilot validate examples/` end-to-end

## Try the CLI

```bash
opspilot --version
opspilot init                                  # creates ~/.opspilot/{kb,sessions,audit,logs}
opspilot schemas                               # list all 19+ registered schemas
opspilot validate examples/scn_ticket_summary_zh/
opspilot validate examples/itr_ticket_summary_zh_v1_3_0/iteration/record.yaml
```

## Ollama setup (local vs docker)

PR-3+ talks to a real Ollama daemon. The Makefile supports two modes via
`OLLAMA_MODE`:

| Mode | When to use | GPU on macOS | Setup |
|------|-------------|--------------|-------|
| `local` (default) | macOS dev box; host already has `ollama` | Metal (full speed) | `brew install ollama && brew services start ollama` |
| `docker` | CI runners; Linux servers; team-onboarding repro | NVIDIA via `--gpus all`; **no Metal** in Docker Desktop | `make OLLAMA_MODE=docker ollama-up` |

**macOS rule of thumb**: stay in `local` mode. Docker Desktop containers run
inside a Linux VM and cannot reach Metal Performance Shaders, so an Ollama
container will fall back to CPU and run 5–10× slower than the host binary.

### Local mode (macOS dev default)

```bash
# 1. Confirm daemon is up (default port 11434)
make ollama-up                              # OLLAMA_MODE=local
# Expected: "Local Ollama running on :11434"

# 2. Pull defaults — override names if you have different tags installed
make ollama-pull                            # uses OLLAMA_CHAT_MODEL / _EMBED_MODEL
# Or pin per-invocation:
make OLLAMA_CHAT_MODEL=qwen2.5:14b-instruct ollama-pull

# 3. Run the integration smoke tests
make test-ollama
```

`make ollama-down` and `make ollama-logs` in local mode are informational only —
host daemons are managed by `brew services` / `launchctl`, not Make.

### Docker mode (CI / Linux servers)

```bash
make OLLAMA_MODE=docker ollama-up           # docker compose up -d ollama
make OLLAMA_MODE=docker ollama-pull         # pulls inside the container
make OLLAMA_MODE=docker test-ollama
make OLLAMA_MODE=docker ollama-down         # tear down
```

Persist the choice in your shell:

```bash
export OLLAMA_MODE=docker                   # for the rest of this session
```

Or in CI workflow YAML:

```yaml
env:
  OLLAMA_MODE: docker
```

### Default models

| Var | Default | Override example |
|-----|---------|------------------|
| `OLLAMA_CHAT_MODEL`  | `gemma4:e4b`              | `make OLLAMA_CHAT_MODEL=qwen2.5:14b-instruct ollama-pull` |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text-v2-moe` | `make OLLAMA_EMBED_MODEL=nomic-embed-text ollama-pull` |

Whatever you choose, pin the same `model_ref` (e.g. `ollama-local/<name>@<date>`)
in `examples/` and `harness/templates/eval-config.yaml` so test fixtures stay
reproducible.

## File map (PR-1)

```
src/opspilot/
├── __init__.py        # version
├── __main__.py        # python -m opspilot
├── cli.py             # Typer app (init / validate / schemas)
├── config.py          # Stage 1 config (env vars only)
├── errors.py          # OpsPilotError hierarchy
├── ids.py             # ULID + sha8/sha16 + validators
├── timeutil.py        # RFC3339 UTC helpers
└── schemas.py         # registry + validate() + path → schema inference

tests/
├── conftest.py        # auto-discovers every example file as a test case
├── test_ids.py
├── test_timeutil.py
└── test_schemas.py    # registry checks + parametrized example validation
```

## What PR-1 deliberately does NOT include

PR-1 is the **schema validation foundation only**. The following arrive in
later PRs (see `IMPLEMENTATION_STAGE_1.md` §8):

* PR-2: redaction + chunker
* PR-3: Ollama provider + docker-compose
* PR-4: SQLite + LanceDB stores + retrieval
* PR-5: ingestion pipeline + markitdown adapter + `opspilot ingest`
* PR-6: session manager + trace + artifact
* PR-7: orchestrator + `opspilot run`
* PR-8: harness + 6 evaluators + golden test

## Troubleshooting

**`ulid` import fails**: confirm `python-ulid` is installed (`pip show python-ulid`).
There are two competing packages on PyPI; we use `python-ulid` (the active one).

**`make validate` reports "skipped (no schema inferred)"**: that's expected for
files like `README.md`, `checks.md`, sandbox leftover `*_pending.json`. The
validator only attempts files it can map to a schema (see
`infer_schema_name` in `schemas.py`).

**Tests fail on a fresh checkout**: pull latest `examples/` and re-run.
`pytest_generate_tests` auto-discovers `examples/` at collection time, so a
stale checkout misses recently-added validation cases.
