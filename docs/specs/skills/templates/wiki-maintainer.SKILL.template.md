---
# Wiki Maintainer skill — packages the wiki ingest / query→page / lint operations into one OpsPilot skill
# Equivalent to schemas/skill.schema.json
# This is the example skill that connects the operations under wiki/ into the skills framework

name: "wiki-maintainer"
description: "Maintain the OpsPilot wiki: ingest new sources into structured pages, convert high-quality session answers into wiki pages, and run periodic lint to surface contradictions, stale claims, orphan pages, and missing concept pages. Trigger when user asks 'add this to wiki', 'lint the wiki', 'update wiki from this session', or on scheduled cron."
version: "1.0.0"
language: "mixed"

author: "vicente@example.com"
source: "self_authored"
license: "MIT"

model_compat:
  - "@chat-strong"
  - "anthropic-claude/claude-sonnet-4-6@2026-04"

requires:
  tools:
    - "kb.search"                   # search existing wiki pages + KB raw sources
    - "kb.write"                    # register pages back into the KB
    - "memory.add"                  # record maintenance decisions in mid-term memory
    - "artifact.write"              # write page files + lint patches
  mcps:
    - "fs-readonly"                 # read the wiki directory tree (list_directory + read_file)
  providers:
    tools: true
    json_mode: true
    long_context_tokens: 100000     # full wiki scans need long context
  skills: []

safety:
  classification: "internal"
  approval_required: true           # by default every apply needs user approval (conservative)
  telemetry_optout: true
  pii_allowed: false

inputs:
  schema_ref: "wiki/schemas/wiki-page.schema.json"
  description: "Operation kind (ingest|query_to_page|lint) + specific input refs (doc_id / session_id / scan window)"
outputs:
  schema_ref: "wiki/schemas/lint-issue.schema.json"
  description: "For lint: issues list. For ingest/query_to_page: page diff manifest + register-back-to-KB plan."

redacted: true
redaction_rules_version: "1.0.0"

tags: ["wiki", "maintenance", "lint", "ingest"]
labels:
  team: "service-desk"
  routing_target_for: "wiki_lint_issue"

extensions:
  wiki_ops_supported:
    - "ingest"
    - "query_to_page"
    - "lint"
  recipes:
    ingest: "wiki/templates/ingest-recipe.template.yaml"
    query_to_page: "wiki/templates/query-to-page-recipe.template.yaml"
    lint: "wiki/templates/lint-recipe.template.yaml"
---

# Wiki Maintainer

## When to use

Invoke when any of the following holds:

- The user explicitly says "add this to wiki", "lint the wiki", or "update wiki from this session"
- A Session ends + judge.llm score ≥ 0.85 + user_action.accept → candidate for query→page
- Scheduled cron (default every Monday) → run lint
- A `wiki_lint_issue` feedback signal arrives (from the previous lint) → start an iteration to improve the wiki

## Operations

Route by the `inputs.operation` field:

### `ingest`
1. Read `wiki/templates/ingest-recipe.template.yaml`
2. Use `kb.search` to find affected existing pages (top_k=12, hybrid + rerank)
3. The LLM proposes page changes + new pages (≤15 pages per run)
4. Run static checks (schema / pii / no_prompt_injection / links_resolvable / no_orphan)
5. Decide the review mode via the classification + source_trust matrix
6. apply: write files + compute page_id + rebuild outbound_links + update index + append log
7. Register the live page back into the memory KB (`kind: "wiki_synthesis"`)

### `query_to_page`
1. Extract the final response + KB Chunks + user edits from the Session
2. Determine the page kind (synthesis / comparison / summary)
3. Generate a draft; prevent duplicates (embedding similarity ≥0.90 → update the existing page instead)
4. Enforce human review (safety floor)
5. Default into draft; only after approval does it go live + into the KB

### `lint`
1. Read `wiki/templates/lint-recipe.template.yaml`
2. Run the 10 check categories (contradiction / stale / orphan / missing_concept / missing_cross_ref / duplicate / broken_link / data_gap / redaction_warning / schema_invalid)
3. Write each issue to `wiki/_lint/issues.jsonl`
4. Convert to feedback_signal type=`wiki_lint_issue` and inject into skills iteration
5. **Never auto-apply**

## Hard rules

- **Lint never applies**: it only produces issues + candidate patches; apply must go through the ingest / query_to_page flow
- **PII static scan**: every page write must pass redaction first; a hard-fail rejects the write
- **No prompt injection in body**: statically scan injection patterns at load/write time
- **Single-concept-per-page**: on duplicate_concept → file an issue suggesting a merge; creating a second page for the same concept is forbidden
- **Cross-link or orphan**: a new page must have ≥1 inbound candidate link, otherwise it goes into the lint orphan queue
- **Approval default ON**: safety.approval_required=true; the user may relax it per operation kind in the tool-binding

## Failure modes

- Schema validation fails during ingest → roll back the whole batch, write an audit record + emit wiki_lint_issue
- query_to_page hits a duplicate → automatically turn into "suggest updating the existing page"; do not create a new one
- lint exceeds budget → abort + report the partial result + becomes an iteration candidate

## Resources

- `resources/page-style-guide.md` — writing style guide (kept in sync with wiki/CONVENTIONS.md)
- `resources/lint-rules-watchlist.yaml` — key-term watchlist (used for missing_concept_page detection)
