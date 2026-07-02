# Wiki — Detailed Spec

## 1. Principles

1. **The wiki is the persistent compounding artifact**: every ingest makes the wiki richer, instead of retrieving from scratch
2. **LLM owns writes, human owns curation**: the LLM writes every page; humans decide what to ingest, what to ask, what to keep
3. **Cross-link is the value**: a page's value lies in its interlinks; an orphan page is treated as a lint issue
4. **One concept = one page**: multiple pages for the same concept is an anti-pattern (lint will suggest merging)
5. **Provenance always**: every page must be traceable back to raw sources (`derived_from`)
6. **Wiki feeds back to KB**: pages are registered back into memory, so new queries hit synthesis (not just raw chunks)

## 2. IDs & naming

- `page_id` = `wpg_<sha8>` (sha8 of canonical frontmatter+body) — content-addressed
- `slug` = the file name (without extension), globally unique; used in cross-page links `[[<slug>]]`
- Path convention: `wiki/pages/<kind>/<slug>.md`, e.g. `wiki/pages/entity/vpn-gateway.md`
- Namespacing: via the frontmatter `namespace` field (consistent with memory), not via path separation

## 3. Page model

### 3.1 The five page kinds

| kind | Required frontmatter fields | Required body sections |
|---|---|---|
| `entity` | aliases, related_entities, related_concepts | "What is it" / "Key facts" / "Related" |
| `concept` | parent_concepts, related_entities | "Definition" / "Why it matters" / "Examples" |
| `summary` | source_doc_id, source_uri, ingested_at | "TL;DR" / "Key claims" / "Implications for our wiki" |
| `comparison` | subjects[] (≥2), criteria[] | "Subjects" / "Comparison table" / "Verdict / when to use which" |
| `synthesis` | sources[] (≥2 source_doc_ids), thesis | "Thesis" / "Evidence" / "Counter-evidence" / "Gaps" |

### 3.2 Common frontmatter (shared by all kinds)

Authoritative definition: `schemas/wiki-page.schema.json`.

| Field | Required | Description |
|---|---|---|
| `page_id` | ✓ | wpg_<sha8> |
| `slug` | ✓ | Globally unique |
| `kind` | ✓ | enum, see §3.1 |
| `title` | ✓ | Human-readable title |
| `summary` | ✓ | One sentence; used in index.md and hover previews |
| `namespace` | ✓ | Consistent with memory, e.g. `opspilot:public-kb` |
| `classification` | ✓ | public/internal/confidential/restricted |
| `language` | ✓ | en/zh-CN/mixed |
| `version` | ✓ | semver (the page's own revision version) |
| `created_at` | ✓ | RFC3339 |
| `updated_at` | ✓ | RFC3339 |
| `tags` | ✗ | Free-form tags |
| `aliases` | ✗ | Alternative names (used for cross-page link matching) |
| `derived_from` | ✓ | { sources: [{kind,ref,sha256}], parent_pages: [page_id] } |
| `outbound_links` | ✓ | [page_id] — machine-maintained at index time |
| `inbound_link_count` | ✓ | int — computed and back-filled by lint |
| `redacted` | ✓ | Must be true |
| `redaction_rules_version` | ✓ | Synced with session |
| `lifecycle_state` | ✓ | draft / reviewed / live / stale / archived |
| `owner` | ✓ | Responsible maintainer |
| `extensions` | ✗ | Vendor/tool-specific customization |

### 3.3 Body conventions

- See `CONVENTIONS.md` for writing style
- Must contain a `## Sources` section, listing human-readable citations for derived_from + locations (`source_path:line_start-line_end`, same schema as memory citations)
- Must contain a `## Cross-links` section or use `[[<slug>]]` in the body
- Strict redaction; no `[REDACTED:` placeholder may leak into the body

## 4. Cross-links

Authoritative definition: `schemas/wiki-link.schema.json`.

```yaml
link_id: "wlk_<sha8>"
from_page: "wpg_..."
to_page: "wpg_..."
relation: "describes" | "contradicts" | "extends" | "supersedes" | "depends_on" | "compares" | "instance_of" | "see_also"
context_quote: "..."         # short excerpt (≤120 chars, redacted)
created_at: "..."
created_by: "wiki-maintainer-skill@<version>"
```

Conventions:
- `[[<slug>]]` is the canonical form in the body; the index stage parses it into a wiki-link record
- `relation` is an explicit enum; `see_also` is the default (weakest relation)
- `contradicts` / `supersedes` relations automatically produce lint issues (stale_claim candidates)

## 5. Operations

### 5.1 Ingest

```
input: new raw source (already in memory KB as kb_document with doc_id)
        │
        ▼
[1] discover affected pages: kb.search + wiki.search → top-N existing pages
[2] propose page updates (LLM): patches per page, each with a reason
[3] propose new pages: if new concepts/entities/synthesis opportunities are identified
[4] redact + static check: PII / prompt-injection / orphan-creation check
[5] human review (mode by classification + trust):
       public/internal/self_authored → auto + audit
       confidential/restricted/community → human approve required
[6] apply patches: write pages + update index + append log
[7] register wiki updates back to memory KB:
       each updated page → kb_document(kind=wiki_synthesis, content_hash refresh)
       trigger memory.ingestion incremental sync
```

Detailed configuration: `templates/ingest-recipe.template.yaml`.

### 5.2 Query → Page

Not every query should be written back — write-back has costs (it consumes KB capacity, needs maintenance, and may introduce redundancy). Trigger conditions (any one suffices):

- user_action.accept at session end and harness judge.llm score ≥ 0.85
- the session contains ≥ 2 kb.search calls (indicating a synthesis-style question whose answer has synthesis value)
- the user explicitly pins (user_action contains `pin_to_wiki`)

Write-back flow:
1. Take the final response from session.trace as the draft
2. Extract the cited KB chunks → convert them into the page's `derived_from.sources`
3. Choose the page kind (default `synthesis`; special cases such as comparison questions use `comparison`)
4. Follow the ingest recipe's review→apply chain (no separate distillation pass)

Detailed configuration: `templates/query-to-page-recipe.template.yaml`.

### 5.3 Lint

Input: the full current wiki; optionally + the last N days of ingest log + the last M sessions.

Output: a list of lint issues (schema: `schemas/lint-issue.schema.json`).

| issue_type | Detection method (suggested) | Default severity |
|---|---|---|
| `contradiction` | Extract each page's "Key claims" → LLM checks cross-page consistency | high |
| `stale_claim` | A new raw source conflicts with key facts claimed by an existing page | high |
| `orphan` | inbound_link_count = 0 (and not index/log) | medium |
| `missing_concept_page` | An entity/concept mentioned across pages without its own page, count ≥ N | medium |
| `missing_cross_ref` | Two pages clearly related in content but not linked | low |
| `data_gap` | Users ask repeatedly but neither wiki nor KB can answer | medium |
| `duplicate_concept` | Multiple pages describe the same concept | high |

Every issue must be convertible into a `feedback_signal` (type=`wiki_lint_issue`) → injected into skills/iteration (see the entry already added to `feedback-signal.schema.json`).

**Lint never edits pages automatically** — it only produces issues + candidate patches. Apply must go through a human or the wiki-maintainer skill's iteration flow.

Detailed configuration: `templates/lint-recipe.template.yaml`.

## 6. index.md / log.md

### index.md

Organized by kind + topic. Each entry:
```
- [[<slug>]] — <one-line summary> · `<tag>` · classified <classification>
```

Machine-parseable (regex `^- \[\[(\S+)\]\] — (.+?) · `). The LLM appends / reorders after every ingest.

### log.md

Append-only. Each entry:
```
## [<RFC3339-date>] <op> | <subject>
- by: wiki-maintainer-skill@<version>
- session_id: sess_...
- pages_touched: 12 (3 created / 9 updated / 0 archived)
- lint_issues_emitted: 0
- notes: <optional>
```

Machine-parsed (`grep "^## \[" log.md | tail -N`) — directly aligned with the original LLM Wiki idea.

## 7. Bi-directional with KB

When a wiki page's lifecycle_state transitions to `live`, it is **automatically registered into memory as a new KB doc**:

```yaml
kind: "wiki_synthesis"             # new kind field on kb-document (backward compatible; defaults to raw_source)
source_path: "wiki/pages/<kind>/<slug>.md"
namespace: <inherits page.namespace>
classification: <inherited>
content_hash: <wiki page sha256>
embedding_model: <KB default>
chunk_strategy: "headings_then_size"
extensions:
  wiki:
    page_id: "wpg_..."
    page_kind: "<kind>"
    page_version: "<semver>"
```

`kb.search` searches both raw and wiki_synthesis by default; a filter can restrict this (e.g. raw only while debugging).

## 8. Security

- redaction: same pipeline as session; no `[REDACTED:` residue allowed
- prompt-injection: static scan when the page body is loaded (same patterns as skills)
- Forbidden: embedding `system_prompt:` / `<|im_start|>system` etc. in a page body
- approval: ingest from `confidential` / `restricted` / `community trust` sources requires mandatory approval
- audit: page create/update/archive/lint apply are all logged; dual-written with session/audit.log

## 9. Lifecycle / state machine

```
draft → reviewed → live → stale → archived
                     ↑       │
                     └───────┘ (lint marks stale → back to live after revision)
```

- `draft`: freshly generated; not in the index; not registered to the KB
- `reviewed`: passed automated checks; can be approved into live by the owner
- `live`: visible in the index + KB; retrieved normally
- `stale`: marked outdated by lint; still visible but shown with a banner; an iteration trigger candidate
- `archived`: archived; not in the index; visible only to audit

## 10. Hard requirements

- page_id = sha8 of frontmatter+body; any change must bump the version + recompute page_id (the old id goes into lineage)
- redacted=true is a precondition for storage
- restricted classification must never be auto-written-back by query_to_page
- lint never auto-applies
- all cross-page links go through `[[<slug>]]`; raw paths are not allowed
- page bodies must not embed system prompts / role overrides

## 11. Interfaces

| Upstream | Input to the wiki |
|---|---|
| `memory/long-term` | raw KB docs (ingest sources) + retrieval (cited by the wiki) |
| `session/` | trace.user_action.accept + judge.llm score (query→page trigger source) |
| `playbooks/` | usable as ingest sources (treated as raw markdown) |
| `governance/` | redaction / classification / approval policies |

| Downstream | What the wiki provides |
|---|---|
| `memory/long-term` | wiki pages registered back into the KB (kind=wiki_synthesis) |
| `skills/` | wiki_lint_issue feedback_signals into the iteration trigger |
| `harness/` | optional evaluators: `wiki.coverage` (coverage) / `wiki.consistency` (consistency) |
| `case-studies/` | live pages can be archived as case studies (not as a replacement) |

## 12. Extension points

- New page kind: extend the enum in `schemas/wiki-page.schema.json` + add a matching template
- New link relation: extend the enum in `schemas/wiki-link.schema.json`
- New lint issue type: extend the enum in `schemas/lint-issue.schema.json` + lint-recipe.template
- External tool integration: Obsidian Web Clipper (ingest entry point) / Marp (page→slide output) / Dataview (dynamic queries over frontmatter)
