# Harness — Detailed Spec

## 1. Object model

```
Scenario (e.g. ticket-summary, log-triage, runbook-gen)
  ├── Fixture[]   ── input snapshot (JSON), redacted
  ├── Golden[]    ── expected output (JSON); may be empty (for rubric-only)
  ├── Rubric      ── scoring criteria (markdown); for the LLM judge / human review
  └── EvaluatorCfg[] — evaluator configurations

Run = (Scenario, Playbook[ver], Model[matrix], EvaluatorCfg[])
  → Result[] (one per fixture × playbook × model)
  → Report (aggregate: pass rate / cost / latency / regression delta)
```

## 2. IDs & naming

- `scenario_id`: `scn_<slug>`, e.g. `scn_ticket_summary_zh`
- `fixture_id`: `fix_<sha8>` (content-addressed), e.g. `fix_a1b2c3d4`
- `golden_id`: `gold_<fix_sha8>` (paired with the fixture)
- `playbook_ref`: `<playbook_id>@<version>`
- `model_ref`: `<provider_id>/<name>@<version>`, e.g. `anthropic-claude/claude-sonnet-4-6@2026-04`; see `providers/SPEC.md` §1.2. An alias (e.g. `@chat-strong`) may also be used; the registry resolves it before persisting.
- `run_id`: `run_<ULID>`

## 3. Evaluator types

| Type | Input | Judgment | Use case |
|---|---|---|---|
| `rule.regex` | output text | regex match / no-match | required key fields, forbidden words |
| `rule.json_schema` | output JSON | schema validation | structured output |
| `rule.pii_check` | output text | detect residual PII | compliance baseline |
| `semantic.embedding` | output vs golden | cosine similarity threshold | semantic similarity |
| `judge.llm` | output + rubric | LLM scoring (judge model version pinned) | quality evaluation that is hard to encode as rules |
| `sandbox.exec` | output (script) | run in sandbox → exit_code / expected files | runbook/script-style outputs |
| `rag.recall_at_k` | retrieval results vs ground truth document_ids | hits / k | RAG recall evaluation (see `memory/`) |
| `rag.precision_at_k` | retrieval results vs ground truth | relevant / k | RAG precision evaluation |
| `rag.citation_validity` | output containing citations | whether each citation resolves to source_path:line_range | eliminate "fake citations" |
| `human.review` | output | manual annotation (entered externally) | sampled quality checks |

The config schema for each evaluator type is in the `evaluators:` section of `eval-config.template.yaml`.

### 3.1 Pinning the LLM-judge version

To avoid judge drift:
- the judge model must be pinned to a specific version (`latest` is not allowed)
- the judge prompt must be hash-pinned and written into the Result
- prefer a judge from a different vendor than the model under evaluation, to reduce same-direction bias

## 4. Metrics

| Metric | Definition | Purpose |
|---|---|---|
| `pass_rate` | passing fixtures / total fixtures | overall quality |
| `regression_delta` | current − baseline pass rate | regression gate |
| `cost_per_run` | sum(token cost) / fixtures | cost comparison |
| `latency_p50/p95` | end-to-end latency percentiles | performance |
| `evaluator_breakdown` | hit rate per evaluator | locating failure types |
| `flakiness` | variance across repeated runs of the same fixture/model | stability |

## 5. Dataset versioning

- Fixture / Golden / Rubric assets must carry a `version` (semver) and a `content_hash` (sha256)
- Changes go through a PR; the baseline diff is shown during code review
- Large files (>1 MiB) go through LFS or DVC; small files go directly into Git

## 6. CI integration

```
on PR:
  → discover changed prompts/playbooks/fixtures
  → run harness on affected scenarios
  → enforce thresholds (pass_rate, regression_delta)
  → upload report.{md,html} as artifact
on schedule (nightly):
  → full matrix run
  → diff vs last green
  → notify on regression
```

Exit code convention:
- `0`: all thresholds pass
- `1`: some fixtures failed but the regression gate was not triggered
- `2`: regression gate triggered (merge blocker)
- `64`: harness internal error

## 7. Output contracts

- Single result: `schemas/eval-result.schema.json`
- A Run's `results.jsonl`: one result per line
- Reports:
  - `report.md`: human-readable summary + samples of failed cases
  - `report.html`: optional, with trend charts
  - `report.json`: machine-readable, schema-conformant (schema TBD)

## 8. Adapter pattern

This repository defines a neutral contract. Execution can be delegated to:
- **promptfoo** (lightweight CLI, YAML config; good for individuals/small teams)
- **OpenAI Evals** (a more systematic framework)
- **Inspect AI** (from the UK AI Safety Institute; better suited to agent/tool-call evaluation)

Adapter-layer responsibilities (to be implemented, not in this directory):
1. Read an `eval-config.template.yaml`-style config
2. Translate it into the target framework's native format
3. Convert the target framework's output back into `eval-result.schema.json`

## 9. Fixture sourcing

Legitimate sources (by priority):
1. **Redacted session trace.jsonl** — closest to real traffic
2. **Hand-crafted boundary cases** — cover corner cases
3. **Public datasets** (with license attribution) — for cross-team comparison
4. **Synthetic data** (LLM-generated) — stress testing only, never the regression baseline

Red lines:
- ❌ Unredacted tickets/logs/customer conversations committed directly
- ❌ Content containing real PII / credentials / internal domain names / IPs

## 10. Hard requirements

- Fixtures must be redacted and pass a `rule.pii_check` self-check
- At least one of Golden or Rubric must exist (a fixture with no evaluation basis at all is not allowed)
- Every evaluator must be re-runnable (deterministic) or explicitly flagged `nondeterministic: true`
- Run results must include the model version, judge model version, prompt hash, playbook version, and fixture version — none may be missing
