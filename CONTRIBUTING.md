# Contributing

Thanks for your interest in OpsPilot. This document covers the dev setup,
the quality gates every change must pass, and the conventions we follow.

## Dev setup

```bash
git clone https://github.com/vicenteliu/OpsPilot.git
cd OpsPilot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make rust-dev            # optional: Rust extensions (requires rustup)
cd web && pnpm install   # optional: web UI
```

Local models and embeddings need [Ollama](https://ollama.com):

```bash
ollama pull nomic-embed-text-v2-moe
```

## Quality gates

CI runs these on every PR — run them locally first:

```bash
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
pytest tests/ -m "not slow and not requires_ollama"
```

Additional suites:

```bash
pytest                          # full suite (needs a live Ollama instance)
make bench                      # Rust vs Python benchmarks (must stay ≥ 5×)
cd web && pnpm check && pnpm build   # web UI type-check + build
```

Golden tests (`opspilot harness golden*`) gate provider/model changes — run
them when touching playbooks, prompts, or provider code. See
[docs/cli.md](docs/cli.md#harness).

## Conventions

- **Language** — all code, comments, and docs are English. Chinese
  translations live under `docs/zh/`.
- **Terminology** — use the domain language defined in
  [CONTEXT.md](CONTEXT.md) (e.g. *Work item*, not "ticket"; *Session*, not
  "job"). Legacy identifiers like `ticket_ref` migrate incrementally.
- **Branches / PRs** — feature branches (`fix/…`, `feat/…`, `chore/…`,
  `docs/…`) with one focused PR each; PRs must be green before merge.
- **Architecture decisions** — significant, hard-to-reverse choices get an
  ADR in [docs/adr/](docs/adr/); follow the existing numbered format.
- **Schemas and specs** — the contracts under [docs/specs/](docs/specs/) are
  the source of truth; the schema registry and redaction rules load from
  there at runtime. Change the spec and the code together.
- **Safety invariants** — never weaken the redaction layer, the sandbox
  hardening flags, or the approval gate without an ADR. PII must be redacted
  before any content reaches a model or the KB.

## Reporting issues

Bug reports and feature requests go through
[GitHub Issues](https://github.com/vicenteliu/OpsPilot/issues). For security
vulnerabilities, see [SECURITY.md](SECURITY.md) — do not open a public issue.
