# Skill Catalogs — Known Sources & Cross-platform Compatibility

> ⚠️ **Information freshness**: as of **2026-05-01**. Skill platforms and fields evolve quickly; verify against the official docs before use.

## 1. Known sources

| Source | Type | Default trust | Notes |
|---|---|---|---|
| Local authors (inside the OpsPilot repo) | local | `self_authored` | trusted by default |
| `anthropic-skills/` (pdf, docx, pptx, xlsx, skill-creator, etc.) | Anthropic official | `imported_trusted` (after human audit) | single-file SKILL.md format |
| Claude Code plugins (with skills + commands + MCP) | Anthropic official + community | depends on author source | includes plugin namespaces |
| Third-party public skill repos (GitHub) | community | `imported_community` | **must** go through the community tier |
| Private team repos | team-internal | `imported_trusted` | identified via allowlist |
| Exports from external platforms (OpenAI GPTs / LangChain agents, etc.) | cross-platform | `imported_unknown` | go through `from_foreign` distillation; the output can then be promoted a tier |

## 2. Cross-platform comparison

| Dimension | OpsPilot Skill | Anthropic Skill | Claude Code Plugin | OpenAI Custom GPT | LangChain Agent |
|---|---|---|---|---|---|
| Unit | SKILL.md + resources | SKILL.md + resources | plugin.json + skills/ + commands/ + mcps/ | JSON config + Actions | Python class |
| Trigger mechanism | `description` (≤300 chars) | `description` | description / explicit invocation | system prompt + descriptions | tool-name match |
| Tool declaration | `requires.tools / .mcps` | implicit (described in the body) | explicit MCP server config | OpenAPI Actions schema | `Tool` subclass |
| Safety classification | explicit `safety.classification` | no native field yet | depends on plugin manifest | platform review | self-implemented |
| Output schema | optional `outputs.schema_ref` | none | none | OpenAPI response schema | custom |
| Distillation support | native (4 source kinds) | none | skill-creator tool supports one at a time | none | LangSmith trace capture |
| Version pinning | semver + checksum | none | git ref | platform-managed | pip version |

Field mapping (used for `from_foreign` distillation):

```
OpenAI GPT.instructions       → SKILL.md.body
OpenAI GPT.name              → SKILL.md.frontmatter.name (slugified)
OpenAI GPT.description       → SKILL.md.frontmatter.description (truncate 300)
OpenAI GPT.actions[].schema  → SKILL.md.requires.tools (mapped) + tool-binding.yaml
OpenAI GPT.knowledge files   → SKILL.md.resources/

Claude Code skill SKILL.md   → readable as-is; just extend the frontmatter fields
Claude Code commands/        → register as builtin tools in tool-binding.yaml
Claude Code mcps/            → import directly into mcp-config.yaml

LangChain Tool.name          → SKILL.md.frontmatter.name
LangChain Tool.description   → SKILL.md.frontmatter.description
LangChain Tool.run signature → tool-binding.yaml (kind=builtin or sandbox)
```

## 3. Recommended MCP servers

> Common MCPs suited to IT operations / ticketing / document-collaboration scenarios, configured in this repo's `mcp-config.template.yaml` format.

| Suggested MCP id | Purpose | Trust | Key constraints |
|---|---|---|---|
| `fs-readonly` | read-only workspace files | trusted | tools_allowlist admits only read_file/list_directory |
| `git-readonly` | read git history, diff, blame | trusted | denylist push/force |
| `notion-main` | Notion pages/databases | trusted | denylist delete_*; enable on demand |
| `slack-readonly` | read Slack messages | trusted (subject to compliance) | compliance.pii_allowed=false |
| `jira-main` | read/write Jira tickets | trusted | denylist delete_issue / clearing sprints |
| `gh-main` | GitHub repos / PRs / issues | trusted | denylist force-push / merge to main |
| `internal-search-http` | internal search service | trusted | data_residency per local compliance |
| `web-fetch-sandboxed` | fetch public web content | community | must run in sandbox + egress allowlist |

For the full list see https://modelcontextprotocol.io/servers (information as of 2026-05-01; verify before use).

## 4. Distillation source selection

| You want to... | Recommended distillation type | Recommended LLM | Notes |
|---|---|---|---|
| Solidify successful workflows the team repeats | `from_traces` | hybrid (pattern_mining + Haiku) | redact first; start with min_support=5 |
| Learn industry best-practice skill style | `from_skills` | llm_distill (Sonnet) | mind copyright and attribution |
| Turn human-written SOPs / Runbooks into executable skills | `from_docs` | llm_distill (Sonnet) | docs are relatively long; higher unit cost |
| OpenAI GPTs / LangChain agent → OpsPilot | `from_foreign` | llm_distill (Sonnet) | not implemented in the spec stage; listed under OQ |

## 5. Known risks & mitigations

| Risk | Mitigation |
|---|---|
| Distillation leaks trace PII into a skill body | hard-fail in the redact stage; second PII scan at the review stage |
| Description tampered with via prompt injection | statically scan injection patterns at load time (see lifecycle-policy `static_checks`) |
| Third-party skill invokes undeclared tools | tool-binding `deny_on_unknown_tool: true` |
| MCP server secret leakage | env placeholders + `block_secrets_in_env_literals` |
| Skill upgrade introduces a regression | `update.require_regression_eval: true`; a 3% drop blocks the update |
| Circular dependencies between skills | DAG validation of `requires.skills` at load time |

## 6. Maintenance

- Review this document every 30 days (same cadence as providers/catalogs.md)
- Keep the recommended MCP list aligned with the official docs; mark deprecated items `status: deprecated` and provide a migration path
- Whenever the cross-platform field-mapping table changes, update the `from_foreign` distillation recipe in sync
