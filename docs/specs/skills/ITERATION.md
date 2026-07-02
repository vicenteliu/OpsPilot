# Skills — Iteration Mechanism Detailed Spec

> This document stands alone to keep SPEC.md from growing too thick. `skills/SPEC.md §13` is the entry-point overview; the details are here.

## TL;DR
A structured mechanism that takes a skill from v1.0 → continuous small-step evolution → a stable v1.x. Three pieces of the puzzle:

1. **Lineage**: each skill's evolution is a directed graph (`parent_variant_id` / `merged_from`); the reason for every change is traceable
2. **Variants**: multiple candidates of the same skill run in parallel; the Harness runs the matrix and compares against the baseline
3. **Feedback signals**: user_action events from Sessions, Harness scores, distillation candidate patterns, model drift, and trace failures are aggregated into structured signals → trigger a new iteration

Hard constraint: every iteration must be **automatically recomputable** (recipe + signals + run results = decision); human review only decides "ship or not" — it never rewrites the computation.

## 1. Core objects

```
Skill (stable, e.g. ticket_summary_zh@1.2.0)
  │ has_many
  ▼
Variant (candidate, e.g. var_<sha8> labeled v1.3.0-alpha)
  │ produced_by
  ▼
Iteration (process record, itr_<ULID>)
  │ triggered_by
  ▼
FeedbackSignal[] (fb_<ULID> or aggregated)
```

| Object | Key fields | File location |
|---|---|---|
| Skill | name + version + checksum | `skills/repo/<name>/SKILL.md` |
| Variant | parent_skill_ref, variant_label, status, diff_ref | `skills/repo/<name>/variants/<variant_id>/SKILL.md` |
| Iteration | trigger, hypothesis, proposed_changes, evaluation, decision | `skills/iterations/<itr_id>.yaml` |
| FeedbackSignal | signal_type, weight, source_ref | `skills/feedback/<skill_ref>/<fb_id>.yaml` or aggregated jsonl |

## 2. Trigger taxonomy

Every iteration must have an explicit trigger type:

| trigger.type | Trigger condition | Automatic/manual |
|---|---|---|
| `regression_detected` | harness regression gate drops more than policy.regression_threshold | automatic |
| `feedback_signal` | accumulated feedback weight ≥ policy.feedback_min_weight_to_trigger | automatic |
| `distillation_candidate` | distillation from traces yields a candidate pattern significantly different from the current skill (min_support satisfied) | automatic |
| `model_upgrade` | a model_ref in model_compat gets a version upgrade | automatic |
| `scheduled` | cron (e.g. full regression every Monday) | automatic |
| `manual` | human-initiated (with hypothesis text) | manual |

Iterations without a declared trigger are rejected at load time.

## 3. Variant lifecycle

```
              ┌──────────┐
              │  draft   │  just created by author/iteration; eval not yet run
              └────┬─────┘
                   │ run trigger eval + harness fixtures
                   ▼
              ┌──────────┐
              │  active  │  being compared against baseline
              └────┬─────┘
       ┌───────────┼───────────────┐
       │           │               │
       ▼           ▼               ▼
   ┌────────┐ ┌────────┐      ┌────────┐
   │winning │ │ losing │      │ merged │  merged with other variants
   └───┬────┘ └───┬────┘      └────┬───┘
       │ promote   │ archive       │ promote merged variant
       ▼           ▼               ▼
  ┌─────────┐ ┌────────────────────────┐
  │promoted │ │  archived (kept N days)│
  └─────────┘ └────────────────────────┘
       │ becomes new stable; old stable enters the rollback window
       ▼
   updates registry to new version
```

### 3.1 State transition rules

- Number of simultaneously active variants per skill ≤ `policy.max_concurrent_active` (default 3)
- A variant not promoted by variant_max_lifetime_days is auto-archived
- A promoted variant must mark the previous stable version as deprecated (grace 30d)

## 4. Iteration pipeline

```
sense  ──▶  propose  ──▶  vary  ──▶  evaluate  ──▶  decide  ──▶  apply
  │           │           │           │             │            │
  ▼           ▼           ▼           ▼             ▼            ▼
signals    hypothesis   variant(s)  run results   outcome     registry
                                                              update
```

| Stage | Input | Output | On failure |
|---|---|---|---|
| sense | feedback signals + triggers | whether to start an iteration | below threshold → return |
| propose | trigger + signals | hypothesis + proposed_changes | LLM generation fails → retry N times |
| vary | proposed_changes | 1..M variant SKILL.md drafts | schema validation fails → reject |
| evaluate | baseline + variants × fixtures | matrix results | any hard_fail → variant losing |
| decide | results + policy | promote / reject / merge / iterate_again | promotion criteria not met → reject |
| apply | decision | registry update + version bump | rollback on failure |

## 5. Decision rules

A variant enters `winning` only when **all** of the following hold (from `iteration-policy`):

1. **No regression** on anchor fixtures (pass_rate not below baseline)
2. On the new fixtures (designed for this iteration's hypothesis), **pass rate ≥ baseline + min_delta_weighted**
3. Cost growth ≤ `max_cost_increase_pct` (default 10%)
4. Trigger eval still passing (recall ≥ 0.9, FP ≤ 0.05)
5. All static checks pass (PII / prompt-injection / tool resolvable)

Failing any one → losing → goes into archive.

## 6. Promotion vs merge

- **Promotion**: a single variant directly becomes the new stable
- **Merge**: multiple variants each carry part of the improvement; merge their diffs into a new variant, which then goes through evaluate again

Merge algorithm (the spec stage does not mandate an implementation path; the interface is agreed):
```
merge(variants[]) → new_variant
  inputs:
    base = baseline.SKILL.md
    diffs[] = each variant's diff vs baseline
  output:
    SKILL.md with diffs union, conflicts surfaced for human resolve
```

## 7. Feedback ingestion

### 7.1 Signal types

| signal_type | Source | Default weight |
|---|---|---|
| `user_action.accept` | session.trace `user_action.accept` | +1.0 |
| `user_action.reject` | session.trace `user_action.reject` | -2.0 |
| `user_action.edit` | session.trace `user_action.edit` (with payload_diff) | -1.0 (the diff points at the concrete problem) |
| `harness_score` | weighted score diff vs baseline from harness.results | × 5 (strong signal) |
| `distillation_pattern` | distillation yields a new pattern with min_support satisfied | +1.0 per pattern |
| `model_drift` | trigger eval degrades after a model upgrade | +3.0 |
| `trace_failure` | rising frequency of tool_result.status=failed | +2.0 |

### 7.2 Aggregation rules

Each skill maintains a `signals.jsonl` (append-only). Aggregation:
- **Sliding window**: default 30 days
- **Weighted sum** `Σ(weight × decay)`, decay = `0.9^days_since`
- **Threshold reached** `feedback_min_weight_to_trigger` (default 5.0) → triggers a `feedback_signal` iteration

### 7.3 Hard constraints

- All signals must be redacted (carrying original prompt content is forbidden)
- session_id references are subject to retention; after expiry → the signal is kept, but the source field is downgraded to a hash reference

## 8. Lineage

Each stable skill's evolution history is stored in `skills/lineage/<skill_name>.yaml`:

```yaml
skill_name: "ticket_summary_zh"
versions:
  - version: "1.0.0"
    parent: null
    iteration: null
    promoted_at: "2026-01-15T10:00:00Z"
  - version: "1.1.0"
    parent: "1.0.0"
    iteration: "itr_01J..."
    promoted_at: "2026-02-20T10:00:00Z"
    summary: "Added missing-field detection"
  - version: "1.2.0"
    parent: "1.1.0"
    iteration: "itr_01K..."
    promoted_at: "2026-04-12T10:00:00Z"
    summary: "Tightened citation validity"
```

## 9. Rollback

- Keep the most recent `preserve_previous_n_versions` (default 3) stable versions by default
- `can_rollback_within_days` (default 30): one-click rollback within 30 days
- A rollback goes through audit + is recorded as a new lineage entry (history is never modified)

## 10. Interfaces with other directories

### 10.1 Harness (evaluation side)

New evaluator types:
- `iteration.delta`: multi-dimensional delta of a variant vs baseline (pass_rate / cost / latency / per-evaluator score)
- `iteration.no_regression_on_anchors`: no regression on anchor fixtures
- `iteration.trigger_eval_recall`: whether the trigger eval still passes

### 10.2 Session (signal source)

New optional event in session.trace:
```yaml
type: "system"
event: "feedback_capture"
details:
  skill_ref: "ticket_summary_zh@1.2.0"
  signal_type: "user_action.edit"
  weight: -1.0
  payload_ref: "art_<sha8>"   # diff content goes through an artifact
```

### 10.3 Memory (distillation candidates)

Patterns that the distillation pipeline's `mine` stage identifies as "significantly different from the current skill" are automatically injected into the feedback collector as `distillation_pattern` signals.

## 11. Hard requirements

- Every iteration must have a trigger.type
- A variant must have parent_skill_ref + a diff vs its parent
- Decision results must be recomputable (given recipe + signals + run results, the conclusion must be identical)
- A promoted variant must update lineage + the old stable enters the rollback window
- Losing variants must not be deleted directly; keep them archived for at least `variant_max_lifetime_days`
- All iteration and variant IDs must match the ULID/sha8 patterns (see schemas)

## 12. Anti-patterns

- ❌ Skipping evaluate and promoting directly (even a manual trigger must run the fixtures)
- ❌ Changing description + body + requires.tools in the same iteration (change one variable at a time; multi-variable changes cannot be attributed)
- ❌ Using stale fixtures (fixtures must be version-pinned together with the model_ref)
- ❌ Ingesting feedback signals without redaction
- ❌ Treating a user_action.edit diff as authoritative (users can be wrong too; the diff is a signal, not the answer)

## 13. Open questions

- [ ] Automatic merge strategy for conflicts between variants (schema field conflicts vs body section conflicts)
- [ ] Joint iteration across multiple skills (e.g. keeping the description style of `ticket_summary_zh` and `ticket_summary_en` evolving in sync)
- [ ] On rollback, should the "voided promotion" in lineage be marked voided, or simply add a new entry?
- [ ] Cross-workspace lineage merging (fork-and-merge model)
