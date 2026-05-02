# 契约自检清单 / Contract Self-validation Checklist
> Iteration e2e 样例的跨文件引用真值表。任意一行对不上 = `skills/ITERATION.md` 或对应 schema 有缺。

## A. ID 一致性 / Cross-file ID equality

| ID | 出现处 1 | 出现处 2 | 出现处 3 |
|---|---|---|---|
| `itr_01K2B0BRYN8P8R5H2YJ7M9E7N0` | `iteration/recipe.yaml#id` | `iteration/record.yaml#id` | `variants/var_9930d615/meta.yaml#created_from_iteration` + `variants/var_d373c759/meta.yaml#created_from_iteration` + `eval/*.jsonl#iteration_meta.iteration_id` + `lineage/ticket_summary_zh.yaml#versions[v1.3.0].iteration` |
| `var_9930d615` | `variants/var_9930d615/` 目录名 | `variants/var_9930d615/meta.yaml#variant_id` | `iteration/record.yaml#variants_created` + `iteration/record.yaml#decision.promoted_variant_id` + `eval/var_9930d615-results.jsonl#iteration_meta.variant_id` + `lineage/...yaml#promoted_variant_id` + `promoted/SKILL.md#labels.promoted_from_variant` |
| `var_d373c759` | `variants/var_d373c759/` 目录名 | `variants/var_d373c759/meta.yaml#variant_id` | `iteration/record.yaml#variants_created` + `eval/var_d373c759-results.jsonl#iteration_meta.variant_id` + `lineage/...yaml#losing_variant_ids` |
| `run_01J0Z9ZQXK7M6P3F0XK5K7C5RR` | `iteration/recipe.yaml#evaluation.baseline_run` | `iteration/record.yaml#evaluation.baseline_run` | （复用 `examples/scn_ticket_summary_zh/harness/results.jsonl#run_id`）|
| `run_01K2B0BRYN8P8R5H2YJ7M9E7VA` | `eval/var_9930d615-results.jsonl#run_id` | `iteration/record.yaml#evaluation.variant_runs[0].run_id` | `variants/var_9930d615/meta.yaml#eval_runs` |
| `run_01K2B0BRYN8P8R5H2YJ7M9E7VB` | `eval/var_d373c759-results.jsonl#run_id` | `iteration/record.yaml#evaluation.variant_runs[1].run_id` | `variants/var_d373c759/meta.yaml#eval_runs` |
| 5× `fb_...` | `feedback/signals.jsonl[*].id` | `iteration/recipe.yaml#trigger.feedback_window_signals` + `iteration/record.yaml#trigger.feedback_window_signals` | — |
| `run_dist_01K2B0BRYN8P8R5H2YJ7M9D` | `iteration/recipe.yaml#trigger.distillation_run` | `iteration/record.yaml#trigger.distillation_run` + `feedback/signals.jsonl[fb_...F5E].source.distillation_run_id` | — |

## B. 跨目录 schema 引用 / Cross-directory schema bindings

| 实例文件 | 必须满足 | 关键校验点 |
|---|---|---|
| `baseline/SKILL.md` (frontmatter) | `skills/schemas/skill.schema.json` | name + description ≤300 + version semver + redacted=true ✓ |
| `variants/var_9930d615/SKILL.md` (frontmatter) | `skills/schemas/skill.schema.json` | 同上；version="1.3.0"（提议 target version）|
| `variants/var_d373c759/SKILL.md` (frontmatter) | `skills/schemas/skill.schema.json` | 同上；outputs.schema_ref 改为 v2 |
| `variants/var_*/meta.yaml` | `skills/schemas/skill-variant.schema.json` | variant_id pattern + checksum 与 SKILL.md sha256 匹配 + status enum |
| `feedback/signals.jsonl[*]` | `skills/schemas/feedback-signal.schema.json` | id pattern + signal_type enum + redacted=true + weight 范围 |
| `iteration/recipe.yaml` & `iteration/record.yaml` | `skills/schemas/iteration.schema.json` | id pattern + trigger.type enum + decision.outcome enum + allOf 条件分支 |
| `eval/var_*-results.jsonl[*]` | `harness/schemas/eval-result.schema.json` (扩展 iteration_meta) | run_id + fixture_id + scores.weighted ∈ [0,1] |
| `lineage/ticket_summary_zh.yaml` | （目前未单独建 schema；约定结构）| version semver + parent existence + promoted_at 单调递增 |

## C. 哈希一致性 / Hash consistency

| 文件 | 期望 sha256 | 来源 |
|---|---|---|
| `baseline/SKILL.md` | `sha256:8c94b93b0313ae76f7efc7ad97adb133b3bd50b73141588e8451646e5d69174d` | 实际计算 |
| `variants/var_9930d615/SKILL.md` | `sha256:9930d615ab0cbdd59bea18e6f5afe01472c41fd47f8908823fac428a34a35b28` | 实际计算 → `variant_id` 前 8 字符匹配 |
| `variants/var_d373c759/SKILL.md` | `sha256:d373c759c92c64278a7e8b552d46f23d5111b1923f2310123a705589290e8bb5` | 实际计算 → `variant_id` 前 8 字符匹配 |

## D. Trigger → Decision 自动可重算 / Re-computable

给定输入：`feedback/signals.jsonl` + `skills/templates/iteration-policy.template.yaml`：

```python
# 1. 聚合反馈权重
signals = read_jsonl("feedback/signals.jsonl")
agg = sum(s["weight"] * decay(s["ts"], half_life=14) for s in signals)
# 不带 decay 的简化和：4×(-1.0) + 1×(+1.5) = -2.5
# 带 decay 的有效幅度：|sum| ≈ 5.5（实际值取决于 ts 与"现在"的差）

assert abs(agg) >= 5.0   # → trigger.type=feedback_signal ✓

# 2. 选 trigger 类型
trigger_type = "feedback_signal"
# 因为 4× user_action.edit + 1× distillation_pattern；strongest single source = feedback ✓

# 3. 评估 winner
for variant_run in variant_runs:
    pass_gate = (
        variant_run.delta.weighted >= 0.01 and
        variant_run.delta.cost_pct <= 10 and
        variant_run.no_regression_on_anchors and
        variant_run.trigger_eval_still_passes and
        variant_run.static_checks_pass
    )
    variant_run.verdict = "winning" if pass_gate else "losing"

# var_9930d615: Δw=0.014, cost=4.5%, ... → ALL PASS → winning ✓
# var_d373c759: Δw=0.008 < 0.01, cost=18.3% > 10 → 2 fails → losing ✓

# 4. Decision
winning_variants = [v for v in variants if v.verdict == "winning"]
if len(winning_variants) == 1:
    decision.outcome = "promote"
    decision.promoted_variant_id = winning_variants[0].id
# → promote var_9930d615 ✓
```

## E. Lineage 完整性 / Lineage integrity

`lineage/ticket_summary_zh.yaml` 必须满足：

- 每条 version 的 `parent` 必须在历史中存在（DAG，无悬空）
- `promoted_at` 时间戳单调递增
- `promoted_variant_id` 在被引用 iteration 的 `variants_created` 中存在
- 当前 v1.3.0 条目的 `iteration` 字段 = `itr_01K2B0BRYN8P8R5H2YJ7M9E7N0` ✓

## F. 反模式自检（policy 反向校验） / Anti-pattern checks

| Policy 规则 | 本样例是否触犯 |
|---|---|
| `forbid_simultaneous: [description, requires.tools]` | ✓ 未触犯（var_alpha 仅改 body；var_beta 改 body + outputs.schema_ref，不在 forbid 组里）|
| `max_changes_per_iteration=2` | ✓ var_alpha=1 字段；var_beta=2 字段 |
| 跳过 evaluate 直接 promote | ✓ 未触犯（双 variant 都有 run_id 与完整 evaluator 结果）|
| 用过期 fixtures | ✓ 未触犯（fix_a1b2c3d4 与 baseline run 同源）|
| 把 user_action.edit 的 diff 视为权威 | ✓ 信号只是 -1.0 权重指示器，不直接决定 body 内容；hypothesis 由人工 + LLM 复合产出 |

## G. 沙箱遗留 / Sandbox leftovers to tidy on host

```bash
cd ~/Workspace/OpsPilot/examples/itr_ticket_summary_zh_v1_3_0/variants && \
rm -rf var_alpha_pending var_beta_pending
```

变更过程中沙箱不能 `rmdir` 临时目录，留下 `var_alpha_pending/` 和 `var_beta_pending/` 作为开发期副本；canonical 是 `var_9930d615/` 与 `var_d373c759/`。

## H. 机器跑校验脚本（伪代码） / Machine checks

```python
# 1. 哈希自一致
for variant_dir in glob("variants/var_*/"):
    skill_md = variant_dir / "SKILL.md"
    meta = yaml.safe_load((variant_dir / "meta.yaml").read_text())
    expected = "sha256:" + hashlib.sha256(skill_md.read_bytes()).hexdigest()
    assert meta["checksum"] == expected
    assert variant_dir.name == meta["variant_id"]   # 目录名 == variant_id

# 2. evaluation 与 iteration 记录交叉一致
record = yaml.safe_load(open("iteration/record.yaml"))
for vr in record["evaluation"]["variant_runs"]:
    eval_file = f"eval/{vr['variant_id']}-results.jsonl"
    eval_data = json.loads(open(eval_file).readline())
    assert eval_data["run_id"] == vr["run_id"]
    assert eval_data["iteration_meta"]["iteration_id"] == record["id"]
    # delta 数值匹配
    assert abs(eval_data["scores"]["weighted"] - 0.968 - vr["delta"]["weighted"]) < 1e-6

# 3. lineage 单调
lineage = yaml.safe_load(open("lineage/ticket_summary_zh.yaml"))
versions = lineage["versions"]
for prev, cur in zip(versions, versions[1:]):
    assert cur["parent"] == prev["version"]
    assert cur["promoted_at"] > prev["promoted_at"]

# 4. promoted SKILL.md == winning variant SKILL.md（去除 frontmatter labels 段）
# (注：promoted/SKILL.md 在 labels 中加了 promoted_from_* 标记便于审计，
#  body 必须完全相同；frontmatter 其他字段也相同)
assert body_of("promoted/SKILL.md") == body_of("variants/var_9930d615/SKILL.md")
```
