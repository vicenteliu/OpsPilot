# Skills — Registry, Authoring & Distillation

> **Status**: spec-only. This directory defines the skill data model, lifecycle, tool/MCP binding contracts, the distillation pipeline, and templates; it contains no runtime implementation.
> **Stage**: spec only — schemas, templates, contracts. No runtime here.

## TL;DR
A Skill is a **reusable instruction package for "doing one kind of job"**: it has a trigger condition (description), operating steps (markdown body), and declarative tool/MCP dependencies, and it **can be packaged, versioned, shared, and distilled**. OpsPilot's skills subsystem adds three things on top of the Anthropic skills format:

1. **Authoring**: gives people writing new skills a template + checklist + description-tuning guide
2. **Distillation**: **automatically produces skill drafts** from session traces / docs / other people's skills / cross-platform skills — this is what sets OpsPilot apart from a plain skill repository
3. **Tool & MCP integration**: a skill can declare the builtin tools (kb.search etc.) and MCP servers it requires; the registry validates dependencies at load time

## Relation to Anthropic skills

Compatible: the single-file `SKILL.md` + frontmatter + sibling resources/ format is preserved — skills can be imported/exported directly.

Extensions:
- frontmatter adds `requires.tools`, `requires.mcps`, `requires.providers` (dependency declarations)
- adds a `safety` section (classification, telemetry, approval_required)
- adds a `distillation` section (declares the distillation source for traceability)
- adds `compat` (cross-tool/platform mapping)

None of this breaks the minimal Anthropic skills format — the extra fields are unknown frontmatter to a native runner and can be ignored.

## Skill Lifecycle

```
                ┌─────────┐
                │  draft  │  authored or freshly distilled
                └────┬────┘
                     │ author/distill
                     ▼
                ┌─────────┐
                │reviewed │  passed human/auto review
                └────┬────┘
                     │ review.pass
                     ▼
                ┌─────────┐
                │ trusted │  added to trusted sources; no sandbox isolation on install
                └────┬────┘
                     │
            ┌────────┴────────┐
            │                 │
            ▼                 ▼
       ┌─────────┐       ┌──────────┐
       │installed│       │community │  trusted but not installed; or from the community
       └────┬────┘       └─────┬────┘
            │ enable            │
            ▼                   ▼
       ┌─────────┐       (sandbox-only invocation)
       │ enabled │  can be triggered and invoked by a Session
       └────┬────┘
            │ invoke / update / deprecate
            ▼
       ┌──────────┐
       │ archived │
       └──────────┘
```

## Trust tiers

| Tier | Source | Invocation constraints |
|---|---|---|
| `self_authored` | Local author | full (per the permissions the skill itself declares) |
| `distilled` | Distilled from internal traces/docs; passed local review | full |
| `imported_trusted` | Imported from trusted sources (allowlisted orgs/authors) | full |
| `imported_community` | Community / unaudited sources | **sandbox-only invocation enforced**; read-only permissions; network egress denied by default |
| `imported_unknown` | Unknown origin | denied by default; explicit opt-in required to enter the community tier |

See `templates/lifecycle-policy.template.yaml` for details.

## Four core capabilities

### 1. Skill Authoring

Help people write new skills that **trigger reliably, have clear dependencies, and are safe and compliant**.

- `templates/SKILL.template.md`: single-skill template (frontmatter + body)
- `SPEC.md` §3 *Description tuning*: how to write a description so the model recalls it at the right moment
- `SPEC.md` §4 *Quality checklist*: the 7 self-checks that must run before release
- `SPEC.md` §5 *Trigger eval*: use `harness/` to evaluate description trigger accuracy

### 2. Skill Distillation (core of the project)

**Automatically generate skill drafts** from 4 kinds of sources instead of writing them from scratch by hand:

| Source | Template | Best for |
|---|---|---|
| Our own Session traces | `distillation-from-traces.template.yaml` | Solidifying successful workflows the team repeats into a skill |
| Other people's skill collections | `distillation-from-skills.template.yaml` | Learning shared structure and style; building a meta-template |
| Docs / SOPs / playbooks | `distillation-from-docs.template.yaml` | Automatically converting human-written markdown SOPs into skills |
| Cross-platform skills | `distillation-from-foreign.template.yaml` (placeholder) | Anthropic skill ↔ OpenAI GPTs ↔ LangChain agent translation |

Every distillation pipeline must:
1. **redact** — aligned with Session redaction
2. **mine** patterns — pattern mining / LLM-distill
3. **draft** — produce SKILL.md + tool-binding.yaml
4. **review** — human or auto-review
5. **register** — write into the skill-registry

Distillation sources must be traceable: every draft records references to the original data in the `distillation.source` frontmatter field.

### 3. Iteration ⭐

Let a skill go from its first version → continuous improvement → convergence to stable, rather than manually bumping semver. Detailed spec in `ITERATION.md`; highlights:

- **Lineage**: each skill's evolution is a directed graph (parent_variant_id / merged_from); the reason for every change is traceable
- **Variants**: multiple candidates of the same skill run in parallel; the Harness runs the matrix and compares against the baseline
- **Feedback signals**: user_action events from Sessions, Harness scores, distillation candidate patterns, model drift, and trace failures are aggregated into structured signals
- **6 trigger types**: `regression_detected` / `feedback_signal` / `distillation_candidate` / `model_upgrade` / `scheduled` / `manual`
- **Promotion criteria**: no regression on anchor Fixtures + weighted score +0.01 + cost growth ≤10% + trigger eval still passing + all static checks pass
- **Rollback window**: keep the last 3 stable versions by default; one-click rollback within 30 days

Files:
- `ITERATION.md` detailed spec
- `schemas/iteration.schema.json` / `skill-variant.schema.json` / `feedback-signal.schema.json`
- `templates/iteration-recipe.template.yaml` / `iteration-policy.template.yaml` / `feedback-collector.template.yaml`

### 4. Tool & MCP Integration

A skill can invoke three kinds of operations:

| Kind | Examples | Registration |
|---|---|---|
| **Builtin tools** | `kb.search`, `memory.add`, `artifact.write` | Provided by OpsPilot core; no registration needed |
| **MCP tools** | `mcp__notion__*`, `mcp__slack__*` | Register the server in `mcp-config.template.yaml` |
| **Sandbox actions** | shell / script / sql_readonly | Go through `sandbox/templates/action-request.template.yaml` |

`tool-binding.template.yaml` binds a skill's `requires.tools[]` to concrete builtin / MCP / sandbox implementations, annotated with safety_class (read / write / execute / sensitive) and approval_required.

## Scope

In scope:
- skill data model (frontmatter + body + resources)
- registry / lifecycle / trust tiers
- distillation pipeline contracts (4 source kinds)
- tool and MCP binding declarations
- interfaces with session/sandbox/harness/memory

Out of scope (not in this directory for now):
- distillation runner implementation (Python pipeline)
- skill marketplace (community distribution)
- CLI for automatic skill installation

## Directory layout

```
skills/
├── README.md                                  # this file
├── SPEC.md                                    # detailed spec
├── catalogs.md                                # known skill sources + cross-platform mapping
├── schemas/
│   ├── skill.schema.json                      # SKILL.md frontmatter
│   ├── skill-registry.schema.json             # registry entries
│   ├── tool-binding.schema.json               # tool/MCP invocation contract
│   ├── mcp-config.schema.json                 # MCP server config
│   └── distillation-recipe.schema.json        # distillation recipes
└── templates/
    ├── SKILL.template.md
    ├── skill-registry.template.yaml
    ├── tool-binding.template.yaml
    ├── mcp-config.template.yaml
    ├── distillation-from-traces.template.yaml
    ├── distillation-from-skills.template.yaml
    ├── distillation-from-docs.template.yaml
    └── lifecycle-policy.template.yaml
```

## Contracts with other directories

| Upstream | Input to skills |
|---|---|
| `session/` | Historical trace.jsonl as distillation sources (must be redacted first) |
| `memory/` | KB documents as from_docs distillation sources |
| `harness/` | Description trigger evaluation + skill regression tests |
| `providers/` | `requires.providers[]` declares required capabilities (e.g. vision/tools) |

| Downstream | Artifacts skills provide |
|---|---|
| `session/` | Injected into the prompt once activated (system message or tool description) |
| `sandbox/` | Sandbox actions declared in a skill execute via the sandbox |
| `case-studies/` | Distillation reports archived |

## Hard nos

- ❌ Never feed unredacted traces directly into the distillation pipeline
- ❌ Community/unknown-tier skills must never invoke write-class tools (kb.write, memory.add, sandbox.apply)
- ❌ Skills must never modify mcp-config at runtime (prevents prompt-injection routing tampering)
- ❌ Skill descriptions must never contain prompt-injection statements ("ignore previous instructions" etc.) — statically scanned at load time
- ❌ MCP API keys always come from env; never committed to the repo

## Open questions

- [ ] When a skill version is upgraded, should a Harness trigger-regression pass be required (old Fixtures still hit the new skill)?
- [ ] Should distilled skills default into the `distilled` tier, or land in `draft` first pending human review?
- [ ] MCP server health-check frequency (reuse `health_probe` from providers, or define it separately)?
- [ ] Priority of target platforms for cross-platform skill translation (Anthropic skills / Claude Code skills / OpenAI GPTs / LangChain)?
