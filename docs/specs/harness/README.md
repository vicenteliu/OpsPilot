# Harness — Eval & Regression Harness

> **Status**: spec only — object model, templates, config schemas. No runner here.

## TL;DR
Harness = "unit tests + a regression gate" for Prompts / Playbooks. Every prompt change, model swap, or temperature tweak produces pass rate / cost / latency / regression delta numbers, preventing "change one place, break everything".

## Conceptual model

```
Scenario
  ├── Fixture (test-case input snapshot)
  ├── Golden  (expected output)
  ├── Rubric  (scoring criteria, for the LLM judge)
  └── Evaluators (list of evaluators)

Run (one evaluation run)
  = Scenario × Playbook × Model × Evaluators
  → Result (per fixture) → Report (aggregate)
```

## Principles

1. **Don't reinvent the wheel**: integrate with promptfoo / OpenAI Evals / Inspect AI through an adapter layer; the harness only defines contracts.
2. **Redact fixtures first**: inputs entering the harness must already be redacted and safe to commit publicly to the repository.
3. **Comparable across models**: the same set of fixtures/goldens must run across a model matrix (GPT-x / Claude / Llama / Qwen).
4. **Regression gate can block**: runs in CI; if a key metric drops by more than the threshold, the merge is blocked.
5. **Explainable**: every Result traces back to a specific fixture / playbook version / model / evaluator.

## Scope

In scope:
- Object model (Scenario / Fixture / Golden / Rubric / Evaluator / Run / Result / Report)
- Evaluator types (rule / schema / semantic / judge / sandbox-exec)
- Metric definitions (pass rate / regression delta / cost / latency / token)
- Config schemas and templates

Out of scope:
- Concrete runner implementation (Python / Go)
- UI report pages (only the JSON report schema is specified)
- Dataset hosting (DVC/HuggingFace selection deferred)

## Directory layout

```
harness/
├── README.md                          # This file
├── SPEC.md                            # Object model + evaluator taxonomy + metric definitions
├── schemas/
│   ├── fixture.schema.json            # Test case
│   └── eval-result.schema.json        # Single evaluation result
└── templates/
    ├── fixture.template.json          # Example fixture
    ├── golden.template.json           # Example golden
    ├── rubric.template.md             # Scoring rubric template
    └── eval-config.template.yaml      # Config for one Run
```

## Recommended layout for users

```
harness-data/
├── fixtures/<scenario_id>/<fixture_id>.json
├── goldens/<scenario_id>/<fixture_id>.json
├── rubrics/<scenario_id>.md
└── runs/<run_id>/
    ├── config.yaml
    ├── results.jsonl       # one eval-result per line
    └── report.{md,html}
```

## Quickstart (for spec readers)

1. Read `SPEC.md` for the object model and metric definitions
2. Start a test case from `templates/fixture.template.json` (**redact first**)
3. Write the expected output with `templates/golden.template.json` and the scoring criteria with `rubric.template.md`
4. Configure a Run with `templates/eval-config.template.yaml`
5. Use `eval-result.schema.json` as the validation target for the CI regression gate

## Contracts

| Upstream | Input to Harness |
|---|---|
| `prompts/` | prompt id + version |
| `playbooks/` | playbook id + version |
| `session/` | trace.jsonl can serve as a fixture source (after redaction) |

| Downstream | Artifacts provided by Harness |
|---|---|
| CI (GitHub Actions / GitLab CI) | exit code + report |
| `case-studies/` | archived reports (human-readable markdown) |

## Open questions

- [ ] Should the LLM-as-judge model itself be version-pinned (to avoid judge drift)?
- [ ] Cross-vendor comparability of cost/latency: token counts, or USD/RMB amounts?
- [ ] Fixture sharing strategy for self-hosted internal models (local Ollama / vLLM)?
