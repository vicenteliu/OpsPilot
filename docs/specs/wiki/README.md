# Wiki — Compounding Synthesis Layer

> **Status**: spec stage (spec-only). This directory defines the wiki's data model, operations, conventions, and templates; it contains no runtime implementation.
> **Stage**: spec only — page schema, ops contracts, conventions, templates. No runtime here.

## TL;DR
Traditional RAG **re-synthesizes** every answer from raw chunks — the LLM never accumulates. The wiki flips this: on each ingest of a new source, the LLM **writes into** a set of interlinked markdown pages, so **every future answer stands on the shoulders of prior synthesis**. OpsPilot's wiki layers on top of `memory/long-term` (the KB) and works with `skills/`, upgrading "knowledge" from a "passive retrieval source" into "continuously compounding synthesis".

## Mapping to the original idea

| LLM Wiki concept | OpsPilot equivalent |
|---|---|
| Raw sources (immutable) | `kb-document` in the `memory/long-term` KB (markdown source + LanceDB index) |
| **Wiki** (LLM-maintained synthesis layer) | **This directory** `wiki/`: page kinds, cross-links, index, log |
| Schema doc | `wiki/CONVENTIONS.md` (works together with the repo-root `CLAUDE.md`) |
| `index.md` | `wiki/index.md` (indexed by topic/category) |
| `log.md` | `wiki/log.md` (chronological; same semantics as session/audit.log) |
| Ingest | `wiki/templates/ingest-recipe.template.yaml` (layers a wiki update on top of memory.ingestion) |
| Query | Reuses `memory/templates/retrieval.template.yaml`, **plus writing good answers back as new pages** (`query-to-page-recipe`) |
| Lint | **New OpsPilot capability**: detects contradictions / stale content / orphan pages / missing concepts / missing cross-references / data gaps |
| qmd search | Reuses memory's SQLite/FTS5 + LanceDB hybrid |

## How it fits

```
                 raw docs (markdown / pdf / html / wiki export)
                        │
                        ▼
              ┌──────────────────────┐
              │  memory/long-term    │  KB ingest pipeline:
              │   (raw + chunks +    │  redact → chunk → embed → upsert
              │    LanceDB + SQLite) │  (passive retrieval source)
              └─────────┬────────────┘
                        │ retrieval (kb.search)
                        ▼
   ┌─────────────────────────────────────────────────────────┐
   │  wiki/  (LLM-maintained compounding synthesis)           │
   │   ├── pages/         entity/concept/summary/comparison/  │
   │   │                  synthesis pages — interlinked       │
   │   ├── index.md       content catalog                     │
   │   └── log.md         chronological ledger                │
   └─────────────────────┬───────────────────────────────────┘
                         │  wiki page itself becomes a KB doc:
                         │  registered into memory/long-term
                         │  → searchable from kb.search
                         ▼
                   harness / sessions / skills
                         │
                         ▼  lint findings → feedback_signal (wiki_lint_issue)
                   skills/iteration trigger
```

**Core invariant**: a wiki page is a special kind of KB document (`kind: "wiki_synthesis"`) and **is fed back into the memory KB** for retrieval — but write access to it belongs to the wiki maintenance flow, not ordinary ingest.

## Page taxonomy (5 kinds)

Every page must declare a `kind`, one of five:

| kind | Purpose | Example |
|---|---|---|
| `entity` | A single object (system, tool, team, person, product) | `pages/entity/vpn-gateway.md` |
| `concept` | An abstract concept or topic | `pages/concept/ipsec-vs-ssl-vpn.md` |
| `summary` | Summary of a single source (maps directly to 1 raw source) | `pages/summary/sop-vpn-2026-04-28.md` |
| `comparison` | Comparison of multiple objects/options | `pages/comparison/radius-vs-ldap-auth.md` |
| `synthesis` | Cross-source synthesis (the most valuable) | `pages/synthesis/vpn-incident-patterns-2026q1.md` |

See `SPEC.md` §3 and `CONVENTIONS.md` for detailed frontmatter / body conventions.

## Operations

### 1. Ingest

```
new raw source ──▶ memory.ingestion (chunks + vectors)  ──▶ wiki.ingest
                                                              │
                                                              ▼
              [LLM] read → propose updates to ≤15 pages
                                  │
                                  ▼
              human review (default for self_authored / restricted)
                                  │
                                  ▼
              apply: write/update pages + index + log
```

See `templates/ingest-recipe.template.yaml` for details.

### 2. Query → Page (compounding)

The key point stressed by LLM Wiki: "good answers should be written back as new pages." OpsPilot's implementation:

```
session.user_action == "accept"  +  judge.llm score ≥ 0.85
                  │
                  ▼
   propose query_to_page conversion (recipe in template)
                  │
                  ▼
   draft synthesis page → review → register in wiki
                  │
                  ▼
   re-ingest into memory KB (kind=wiki_synthesis)
```

See `templates/query-to-page-recipe.template.yaml` for details.

### 3. Lint (new value added by OpsPilot)

Periodically scans the wiki and emits structured lint issues:

| issue_type | Description |
|---|---|
| `contradiction` | Two pages make contradictory claims about the same fact |
| `stale_claim` | A claim on an older page is superseded by a new source |
| `orphan` | A page with no inbound links |
| `missing_concept_page` | A concept mentioned repeatedly but with no page of its own |
| `missing_cross_ref` | Pages that should be cross-linked but are not |
| `data_gap` | A gap that could be filled via web retrieval |

Each lint issue is converted into the `wiki_lint_issue` type of `feedback_signal` → triggers the wiki-maintainer skill's iteration (wired into skills/ITERATION.md).

See `templates/lint-recipe.template.yaml` for details.

## Index and Log

- `index.md`: content catalog; entry format `- [[<page-slug>]] — <one-line summary> [tags]`
- `log.md`: append-only; entry format `## [YYYY-MM-DD] <op> | <subject>`, convenient for `grep "^## \[" | tail -10`
- Both are maintained automatically by the LLM; humans are read-only

See `templates/index.template.md` and `templates/log.template.md` for details.

## Safety & compliance

- **Redaction**: every page must pass `session/templates/redaction-rules.template.yaml` before being written; PII checks hard-fail
- **Classification**: every page must declare a `classification` (same taxonomy as the KB); `restricted` pages must never be auto-written-back by Query→Page
- **Audit**: every page create/update is written to `wiki/log.md` + synced with session/audit.log
- **RBAC**: a page's owner/collaborators match the session; `restricted` pages may only be modified by a trusted skill
- **Provenance**: pages must record `derived_from` (raw source ids + previous page versions)

## Bi-directional with memory KB

- After a wiki page is created / updated, it is **automatically registered into memory as a KB doc with kind=wiki_synthesis** — retrievable via `kb.search`
- This means new queries also hit wiki pages (not just raw sources) — the more synthesis, the more each answer stands on the shoulders of prior synthesis ✓
- The reverse does not exist for KB ingest: raw sources never auto-generate wiki pages (they must go through the ingest recipe + review)

## Anti-patterns

- ❌ Treating wiki pages as a general document directory (playbooks / SOPs belong in `playbooks/`; the wiki is LLM-accumulated synthesis)
- ❌ Embedding `<system_prompt>` in a page body / attempting to change the LLM's role (forbidden, same as in skills)
- ❌ Having the wiki point directly at raw source paths instead of citing KB doc_ids (breaks retention and redaction constraints)
- ❌ Creating multiple pages for the same concept (lint will detect this and propose a merge)
- ❌ Lint auto-applying (lint emits suggestions / signals; it never edits pages directly)

## Scope

In scope (this directory):
- Page data model (kind / frontmatter / cross-link / lineage)
- Contracts for the three operations (ingest / query→page / lint)
- Interfaces with memory / skills / session / harness
- Index + Log conventions

Out of scope:
- Concrete page editor implementation
- LLM agent runner implementation
- Obsidian integration (recommended but not required)

## Directory layout

```
wiki/
├── README.md                                  # this file
├── SPEC.md                                    # detailed spec
├── CONVENTIONS.md                             # editing conventions (schema equivalent)
├── schemas/
│   ├── wiki-page.schema.json
│   ├── wiki-link.schema.json
│   └── lint-issue.schema.json
└── templates/
    ├── entity-page.template.md
    ├── concept-page.template.md
    ├── summary-page.template.md
    ├── comparison-page.template.md
    ├── synthesis-page.template.md
    ├── index.template.md
    ├── log.template.md
    ├── ingest-recipe.template.yaml
    ├── query-to-page-recipe.template.yaml
    └── lint-recipe.template.yaml
```

## Open questions

- [ ] Lineage when a wiki page is revised (user rewrite / lint apply): use git history, or a separate page-lineage YAML?
- [ ] Automation threshold for `query-to-page`: at what judge score should write-back be auto-suggested (vs always asking the user to review)? Suggested default 0.85
- [ ] Should integration with Obsidian Web Clipper / Marp / Dataview be part of the officially recommended stack?
- [ ] How do multiple wiki instances (team / project / personal) share / isolate namespaces?
