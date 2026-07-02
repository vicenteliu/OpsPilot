# Wiki Conventions — Editing Conventions

> This is the wiki's "schema document" — it tells the LLM **how to write, how to link, and how to archive**. Changing this file = changing the LLM's behavior.
> Equivalent to CLAUDE.md / AGENTS.md in the original LLM Wiki idea.

## 1. Writing principles

- **Compounding over completeness**: prefer short, densely interlinked pages over a single page that tries to be exhaustive
- **Cite or stay silent**: every claim must have a `derived_from`, or be left out
- **Disagreements stay**: when a contradiction is found, **keep both sides**, add a `relation: contradicts` link + flag a `lint_issue`; never silently pick a side
- **Stale beats wrong**: outdated information is better than information rewritten into something wrong; mark it stale and revise at the next ingest
- **One concept = one page**: when duplication is found, propose a merge + provide a migration path
- **No hidden state**: the basis for every conclusion lives in the `Sources` section; never hide it in the LLM's "impressions"

## 2. Titles & slugs

- Title: human-readable, with the necessary qualifiers (e.g. "VPN Troubleshooting SOP (Chinese)" rather than "VPN SOP")
- Slug: lowercase, hyphen-separated, ASCII; for mixed Chinese/English content use pinyin or English
- Globally unique; on conflict use `<topic>-<qualifier>` (e.g. `auth-radius` vs `auth-ldap`)

## 3. Frontmatter

- All required fields must be filled in; none may be missing
- `summary`: one sentence, ≤120 characters; used as the index.md entry and hover preview
- `derived_from`: always list everything; an empty array is allowed only on "purely LLM-generated" pages (very rare; must be marked `extensions.synthetic: true`)
- `outbound_links` and `inbound_link_count` are **machine-maintained**; authors never fill them in by hand

## 4. Body structure

Required sections per page kind (see SPEC.md §3.1). Trailing sections shared by all pages:

```markdown
## Cross-links

- describes → [[<slug-a>]]: <why it is related, 1 sentence>
- contradicts → [[<slug-b>]]: <the point of conflict, 1 sentence>
- see_also → [[<slug-c>]]

## Sources

1. [<doc title>](<source_path>:<line_start>-<line_end>) — <relevance, 1 sentence>
2. ...

## Changelog

- v1.0.0 (2026-04-01): initial; from doc_xxxx
- v1.1.0 (2026-04-15): added contradicting evidence from doc_yyyy
```

## 5. Link writing

- In the body: `[[<slug>]]` or `[[<slug>|<display text>]]` (the latter when the context needs different display text)
- Not allowed: relative paths (`../entity/foo.md`) — machines cannot resolve them across directory reorganizations
- The `Cross-links` section must be explicitly grouped by `relation`

## 6. Tone

- State facts objectively + mark confidence
- Phrase inferences as "Based on XX, possibly ..." (citation required)
- Model first person ("I think") is not allowed — the wiki is a factual record, not the LLM's opinion journal

## 7. Redaction (hard constraint)

- No `[REDACTED:` placeholder may leak anywhere in a page body (even inside quote blocks)
- Alternative: use a generic description ("the affected client host") instead of writing the placeholder
- Every field must pass `session/templates/redaction-rules.template.yaml`

## 8. Pre-publish lint checklist

Self-check before every page is finalized (or after an ingest edit):

```
[ ] 1. frontmatter passes wiki-page.schema.json
[ ] 2. Sources section is non-empty (synthetic pages exempt)
[ ] 3. at least 1 Cross-link (unless being an orphan is expected, e.g. index / log)
[ ] 4. every [[<slug>]] in the body resolves to a page in the wiki (or add a lint stub)
[ ] 5. redacted=true and passes the static PII scan
[ ] 6. classification matches the content (write actions require ≥ internal)
[ ] 7. version bumped (if this is an update) + Changelog entry added
```

## 9. Ingest writing flow (for the LLM)

The LLM proceeds in this order within the ingest recipe:

1. **Read the raw source** (post-redaction version); list 5-10 key claims
2. **kb.search + wiki.search** to find existing related pages (top-10)
3. For each claim:
   - Overlaps with an existing page → add reinforcing evidence to that page (update Sources + Cross-links)
   - Conflicts with an existing page → add `contradicts` links on both sides + trigger a lint signal
   - Brand-new concept → draft an entity / concept page
4. Is a synthesis page worthwhile? (≥ 2 sources jointly supporting one thesis)
5. Update index.md
6. Append to log.md
7. Package all changes and submit for review

**Cap on pages touched per ingest**: default 15 (aligned with the original LLM Wiki idea); exceeding it means the ingest scope is too large and should be split.

## 10. Query → Page writing flow

1. Take session.final_response and the KB chunks cited in session.trace
2. Choose the page kind:
   - Multi-source comparison → `comparison`
   - Multi-source synthesized thesis → `synthesis`
   - Single-source summary → `summary` (rare; usually already generated at ingest time)
3. Fill in the template
4. Required: `derived_from.sources` lists every cited doc_id + chunk_id
5. If `synthesis`, the `thesis` section is required (one-sentence core claim)
6. Follow the second half of the ingest flow: review → apply → register back into the KB

## 11. Lint output writing flow

During lint, the LLM:

1. Scans the wiki: runs each check type (contradiction / stale / orphan / missing_concept, etc.)
2. Writes one structured record per issue (see schema)
3. **Never edits pages directly** — only outputs issues + candidate patches
4. Issues go into `feedback_signal` (type=`wiki_lint_issue`) → trigger iteration

## 12. Anti-patterns (strictly forbidden)

- ❌ "See [[<slug>]]" where the slug does not exist — recorded as broken_link at lint time
- ❌ Citing unredacted raw text (containing PII) in the Sources section
- ❌ Circular dependencies between pages (A explained only via B, B explained only via A)
- ❌ Three pages for the same concept — lint must report duplicate_concept
- ❌ Writing "We should..." / "Decisions:..." in the body — the wiki is facts, not ops
- ❌ Pasting session.trace directly into a page — abstract it into facts / claims first, then cite
- ❌ Absolute links to raw source paths that bypass the KB doc_id — breaks retention

## 13. Obsidian (optional)

- `wiki/pages/` works directly as an Obsidian vault subdirectory
- Frontmatter is fully compatible with Obsidian + Dataview
- `[[<slug>]]` is native Obsidian wiki-link syntax
- Recommended plugins: Dataview (run queries over frontmatter), Graph view (see the wiki's shape)
- Recommended workflow: the LLM edits on one side while Obsidian browses live on the other (aligned with the original LLM Wiki idea)

## 14. Cadence

- **After every ingest**: automatically update index + log
- **Every Monday** (or cron): run lint, emit issues
- **Monthly**: review accumulated lint + run iteration (in concert with skills/iteration-policy.scheduled_review_cron)
- **Quarterly**: review the overall wiki structure, archive stale pages that are no longer relevant
