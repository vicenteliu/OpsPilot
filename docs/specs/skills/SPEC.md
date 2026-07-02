# Skills — Detailed Spec

## 1. Skill data model

Each skill = one directory:

```
<skill_root>/<skill_name>/
├── SKILL.md                  # required: frontmatter (yaml) + body (markdown)
├── tool-binding.yaml         # optional: concrete bindings for the tools/MCPs this skill uses
└── resources/                # optional: scripts, templates, reference material
    ├── ...
    └── examples/
```

### 1.1 SKILL.md frontmatter (authoritative definition in `schemas/skill.schema.json`)

| Field | Required | Description |
|---|---|---|
| `name` | ✓ | Unique slug, e.g. `ticket_summary_zh`; namespacing supported as `<plugin>:<name>` |
| `description` | ✓ | **One-line** trigger description; detailed rules in §3 |
| `version` | ✓ | semver |
| `language` | ✓ | `en` / `zh-CN` / `mixed` |
| `author` | ✓ | Author identifier |
| `source` | ✓ | enum: `self_authored / distilled / imported_trusted / imported_community / imported_unknown` |
| `license` | ✓ | SPDX identifier or `proprietary` |
| `model_compat` | ✓ | Array; model aliases or `["any"]` |
| `requires.tools` | ✗ | List of builtin tool dependencies (e.g. `kb.search`) |
| `requires.mcps` | ✗ | List of MCP server ids (consistent with mcp-config) |
| `requires.providers` | ✗ | Provider capability constraints (e.g. `vision: true`) |
| `requires.skills` | ✗ | Other skills this skill depends on |
| `safety.classification` | ✓ | `public/internal/confidential/restricted` |
| `safety.approval_required` | ✓ | bool; whether every invocation requires user confirmation |
| `safety.telemetry_optout` | ✓ | bool |
| `inputs.schema_ref` | ✗ | JSON Schema reference |
| `outputs.schema_ref` | ✗ | JSON Schema reference |
| `distillation` | ✗ | If source ≠ self_authored, records the distillation source (type + refs) |
| `redacted` | ✓ | bool; no residual PII allowed in the body |
| `redaction_rules_version` | ✗ | Aligned with Session redaction |

### 1.2 Body conventions

- markdown; may contain steps, rules, constraints, examples
- reference sibling resources as `resources/<file>`; absolute paths forbidden
- any "call tool X" statement must map to `requires.tools` / `requires.mcps`
- embedding system-prompt redefinitions in the body is forbidden (prompt-injection prevention)

## 2. IDs & naming

- `skill_id` = `<name>@<version>`, e.g. `ticket_summary_zh@1.2.0`
- Cross-namespace: `<plugin>:<name>@<version>`, e.g. `data:analyze@1.0.0`
- Internal hash reference: `skl_<sha256(SKILL.md)[:16]>` — used for audit / integrity checks

## 3. Description tuning (critical) / How to write description

The description is the model's only signal for deciding "should this skill be used right now". **A poorly written one will never be recalled.**

### 3.1 Hard constraints

- **One line** (≤ 300 characters)
- Must include the *purpose* + *trigger keywords*: e.g. "Summarize an IT ticket and produce a structured JSON with citations to KB SOPs."
- Don't stuff usage steps into the description (steps belong in the body)
- Don't promise capabilities the tools don't have

### 3.2 Recommended template

```
{ACTION_VERB} {OBJECT} when {TRIGGER_CONDITION}.
Returns {OUTPUT_SHAPE}. Requires {KEY_DEPENDENCY}.
```

Example:
- *"Summarize an IT support ticket when the user pastes ticket content or attaches log snippets. Returns ticket_summary_v1 JSON with KB citations. Requires kb.search and an LLM with json_mode."*

### 3.3 Anti-patterns

- ❌ "Useful for many tasks" — the model cannot decide when to use it
- ❌ "Always use this skill" — tampers with routing priority; equivalent to prompt injection
- ❌ "When the user says 'magic word'" — keyword dependence is brittle

### 3.4 Trigger evaluation (integrated with Harness)

Before release, *trigger fixtures* must be run via `harness/`:
- Positives: 100 queries that should trigger → recall ≥ 0.9
- Negatives: 100 queries that should not trigger → false_positive ≤ 0.05

A skill that has not run the trigger eval must not enter the `enabled` state.

## 4. Quality checklist (must run before release)

```
[ ] 1. description ≤ 300 chars, includes a verb + trigger condition + output shape
[ ] 2. requires.tools / requires.mcps all resolvable in the registry
[ ] 3. every "call X" in the body maps to requires
[ ] 4. redacted=true, and the body passes rule.pii_check
[ ] 5. safety.classification matches the body's actual operations (write actions must be ≥ internal)
[ ] 6. model version compatibility test passes (at least 1 model in model_compat runs green)
[ ] 7. trigger eval passes (recall ≥ 0.9, FP ≤ 0.05)
```

## 5. Skill Registry

`templates/skill-registry.template.yaml` is the entry point:
- `skills[]`: each entry references a SKILL.md path + metadata (trust tier / enabled)
- `aliases`: e.g. `@summarize-ticket` → `ticket_summary_zh@1.2.0`
- `groups`: scenario bundles, e.g. `it-l1-bundle = [ticket_summary_zh, log_triage_zh, vpn_runbook_zh]`
- `installation_policy`: default trust tier and isolation policy for remote imports

Authoritative definition in `schemas/skill-registry.schema.json`.

## 6. Tool & MCP Integration

### 6.1 Tool binding contract

`tool-binding.yaml` (inside the skill directory) declares each tool the skill actually invokes:

```yaml
skill_ref: "ticket_summary_zh@1.2.0"
bindings:
  - tool: "kb.search"
    kind: "builtin"
    safety_class: "read"
    approval_required: false
    config:
      default_scopes: ["opspilot:public-kb"]
      default_top_k: 8

  - tool: "artifact.write"
    kind: "builtin"
    safety_class: "write"
    approval_required: false       # writing to the session's own artifact area is allowed by default

  - tool: "mcp__notion__create_page"
    kind: "mcp"
    mcp_id: "notion-main"
    safety_class: "write"
    approval_required: true        # third-party write action → approval enforced
    config:
      default_database_id: "${NOTION_DB_ID}"
```

Authoritative definition in `schemas/tool-binding.schema.json`.

### 6.2 MCP server configuration

`mcp-config.template.yaml` registers MCP servers, with the same standing as `provider-registry`:

```yaml
mcps:
  - id: "notion-main"
    name: "Notion (main workspace)"
    transport: "stdio"             # stdio | http | sse
    command: "npx"
    args: ["-y", "@notionhq/mcp-server"]
    env:
      NOTION_TOKEN: "${NOTION_API_KEY}"
    tools_prefix: "mcp__notion__"
    enabled: true
    trust: "trusted"
    health_probe:
      interval_seconds: 600
```

Authoritative definition in `schemas/mcp-config.schema.json`.

### 6.3 Invocation flow

```
session.trace[tool_call] (tool=mcp__notion__create_page)
   │
   ▼
tool-binding lookup: skill_ref + tool → mcp_id
   │
   ▼
mcp-config lookup: mcp_id → command/args/env
   │
   ▼
[approval_required?] ──yes──▶ user_action.approve
   │
   ▼
sandbox / direct exec (per safety_class)
   │
   ▼
session.trace[tool_result]  + audit.log
```

## 7. Distillation Pipeline

Four kinds of distillation sources, one recipe per kind (see `templates/distillation-from-*.template.yaml`).

### 7.1 Common stages

```
discover  ──▶  redact  ──▶  mine  ──▶  draft  ──▶  review  ──▶  register
   │            │           │          │           │              │
   ▼            ▼           ▼          ▼           ▼              ▼
sources     redacted     patterns    SKILL.md    pass/fail    in registry
manifest    inputs                   + bindings  + diff         (draft tier)
```

| Stage | Input | Output | On failure |
|---|---|---|---|
| discover | sources from config | manifest (paths + last_modified) | skip + log |
| redact | raw traces / docs | redacted text | hard-fail (any residual PII rejects the run) |
| mine | redacted text | candidate pattern list (prompt patterns / tool sequences / output shapes) | skip that source |
| draft | candidate patterns + template | SKILL.md draft + tool-binding.yaml draft | re-prompt the LLM and retry |
| review | draft | pass/fail + diff vs baseline | goes into the review queue |
| register | reviewed draft | skill-registry entry, tier=`distilled` | rollback |

### 7.2 The four source kinds in detail

**(a) from_traces — distill from Session traces** (most common)

Best for: solidifying successful Sessions the team repeats and that score high on the Harness into a reusable skill.

- Input: a set of `session/<id>/trace.jsonl` (redacted)
- mine: find shared prompt patterns, tool-call sequences, citation style, prompt parameters
- draft: abstract the high-frequency patterns into step instructions
- Risk: concrete content in traces (ticket numbers, usernames) must be redacted first

**(b) from_skills — distill from other skill collections**

Best for: learning the structure and style of external trusted skill libraries (e.g. the anthropic-skills repo).

- Input: N SKILL.md files
- mine: frontmatter field distributions, description phrasing, body section structure
- draft: produce a meta-template or a single new skill (blending the style of multiple skills)

**(c) from_docs — distill from documents**

Best for: converting existing SOPs / Runbooks / playbooks (markdown) into executable skills.

- Input: markdown under playbooks/
- mine: identify trigger conditions, steps, required tools, safety constraints
- draft: generate SKILL.md, referencing the original document as a resource

**(d) from_foreign — cross-platform skill translation** (placeholder)

Best for: translating an OpenAI Custom GPT / LangChain agent / Claude Code skill into the OpsPilot skill format.

- Input: the external platform's skill description file
- mine: field mapping + tool/MCP equivalents
- draft: SKILL.md in OpsPilot format
- Status: no template in the spec stage; listed in catalogs.md's compatibility matrix

### 7.3 Hard constraints

- Distillation output **defaults into the draft tier**; going straight to enabled is forbidden
- Sources must be explicitly redacted (PII check hard-fails)
- The distillation LLM model version must be pinned (avoid drift)
- The distillation.source field is **required** in SKILL.md frontmatter:
  ```yaml
  distillation:
    type: "from_traces"
    sources:
      - "sess_01J0Z9..."
      - "sess_01K1A0..."
    pipeline_run: "run_dist_01J0..."
    distilled_at: "2026-05-01T12:00:00Z"
    redaction_rules_version: "1.0.0"
  ```

## 8. Lifecycle Operations

See `templates/lifecycle-policy.template.yaml` for details. Core operations:

| Operation | Input | Output |
|---|---|---|
| `install` | skill source (local path / git url / package) | written to registry; tier determined by trust assessment |
| `enable` | skill_id | Sessions may trigger it |
| `disable` | skill_id | no longer triggers; not deleted |
| `update` | new version | run trigger eval + regression → replace on pass |
| `deprecate` | skill_id + reason | mark deprecated; kept until retention expires |
| `audit` | skill_id | outputs dependency graph + invocation stats + security audit |

## 9. Security

- Statically scan description / body at skill load time: prompt-injection patterns are banned (system-level directives such as `ignore previous` and their Chinese-language equivalents)
- Descriptions must not be dynamically generated (no variable interpolation)
- community / unknown tier skills: all write-class tools denied by default; only read + sandbox allowed
- approval_required: fires on every invocation; no "remember my choice"

## 10. Hard requirements

- description ≤ 300 chars
- version must not be `latest` / `auto` / `stable`
- every SKILL.md must have `redacted=true`
- all secrets in mcp-config must be env placeholders; inlining forbidden
- distillation sources must be kept for at least the retention period, for reproducibility

## 11. Interfaces with other directories

### 11.1 Skill invocation within a Session

```yaml
# in the trace:
- type: tool_call
  tool: "skill.invoke"
  args:
    skill_ref: "ticket_summary_zh@1.2.0"
    inputs: { ... }

- type: tool_result
  tool: "skill.invoke"
  artifact_ids: ["art_<sha8>"]
```

### 11.2 Harness evaluation

New evaluator types:
- `skill.trigger_recall`: description recall rate
- `skill.trigger_precision`: false-trigger rate
- `skill.contract_compliance`: whether outputs conform to the outputs.schema_ref declared in SKILL.md

## 12. Extension points

- `frontmatter.extensions.<vendor>`: vendor/tool-specific custom metadata
- New distillation types: add a new `templates/distillation-from-<source>.template.yaml`
- MCP transport: extensible (beyond stdio/http/sse, websocket support in the future)

## 13. Iteration Mechanism

> Detailed spec in the standalone document `skills/ITERATION.md`. This section is an overview.

A skill is not "written once and done" — it needs **continuous small-step evolution** toward stability. OpsPilot's iteration loop:

```
feedback signals → trigger → propose → vary (1..M variants)
                                 │
                                 ▼
                           harness × variants
                                 │
                                 ▼
                  decision: promote | reject | merge | iterate_again
                                 │
                                 ▼
                  registry update + lineage entry + rollback window
```

### 13.1 Key objects

- **Iteration** (`itr_<ULID>`): one complete "improve this skill" attempt, with trigger / hypothesis / proposed_changes / evaluation / decision; schema: `schemas/iteration.schema.json`
- **Variant** (`var_<sha8>`): a candidate version, forked from stable; schema: `schemas/skill-variant.schema.json`
- **FeedbackSignal** (`fb_<ULID>`): a single structured feedback record; schema: `schemas/feedback-signal.schema.json`

### 13.2 6 trigger types

`regression_detected` / `feedback_signal` / `distillation_candidate` / `model_upgrade` / `scheduled` / `manual`. Every iteration must explicitly declare trigger.type; otherwise it is rejected at load time.

### 13.3 7 feedback signal types

`user_action.{accept,reject,edit}` / `harness_score` / `distillation_pattern` / `model_drift` / `trace_failure`. Uniformly redacted and written to `skills/feedback/<skill_ref>/signals.jsonl`, aggregated with a 14-day half-life decay; once the total exceeds `feedback_min_weight_to_trigger` (default 5.0), an iteration is triggered.

### 13.4 Promotion requires **all** of

1. no regression on anchor fixtures
2. weighted score improvement ≥ `min_delta_weighted` (default 0.01)
3. cost growth ≤ 10%
4. trigger eval still passing (recall ≥0.9, FP ≤0.05)
5. all static checks pass (PII / prompt-injection / tool resolvable)

Failing any one → losing → archive.

### 13.5 Lineage

Every stable skill maintains `skills/lineage/<skill_name>.yaml`, a directed DAG recording each version's parent + iteration_id + summary. Rollback does not delete history; it only appends a "rolled_back_to_x.y.z" entry.

### 13.6 Anti-patterns (from ITERATION.md)

- ❌ Skipping evaluate and promoting directly
- ❌ Changing description + body + requires.tools in the same iteration (impossible to attribute)
- ❌ Using stale fixtures
- ❌ Treating a user_action.edit diff as authoritative (it is a signal, not the answer)

### 13.7 File inventory

```
skills/
├── ITERATION.md                                       # detailed spec
├── schemas/
│   ├── iteration.schema.json
│   ├── skill-variant.schema.json
│   └── feedback-signal.schema.json
└── templates/
    ├── iteration-recipe.template.yaml                # single-iteration recipe
    ├── iteration-policy.template.yaml                # global policy
    └── feedback-collector.template.yaml              # feedback source config
```
