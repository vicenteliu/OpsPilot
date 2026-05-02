# 端到端样例：Iteration `itr_01K2B0BRYN8P8R5H2YJ7M9E7N0`

> **作用 / Purpose**：把 `skills/ITERATION.md` 的迭代流程**真的串成数据**——从 feedback signals 累积、触发、提议、双 variant 评估、决策、晋升，到 lineage 落地。
> 所有文件都是真实示例（hashes 实际计算，无占位符）。

## 故事线 / Story

| 阶段 | 动作 | 关键文件 |
|---|---|---|
| 1. 反馈累积 | 5 条信号在 30 天窗口内累积，加权和 +5.5（4× user_action.edit 各 -1.0 + 1× distillation_pattern +1.5；按 \|sum\| 触发） | [`feedback/signals.jsonl`](feedback/signals.jsonl) |
| 2. 触发 | 累积权重 5.5 ≥ 阈值 5.0 → 启动 iteration `itr_...N0` | trigger.type=`feedback_signal` |
| 3. 假设 | "在 body 加 missing-field handling 段，让模型主动追问而非泛泛说'建议人工补充'" | [`iteration/recipe.yaml`](iteration/recipe.yaml) |
| 4. 提议 → 2 variants | `var_9930d615`（仅改 body）/ `var_d373c759`（body + outputs.schema_ref） | [`variants/`](variants/) |
| 5. 评估 | 双 variant 跑同一 fixture (`fix_a1b2c3d4`) | [`eval/`](eval/) |
| 6. 决策 | promote `var_9930d615`；reject `var_d373c759`（cost gate 失败） | [`iteration/record.yaml`](iteration/record.yaml) |
| 7. 应用 | 注册为 `ticket_summary_zh@1.3.0`；lineage 加新条目；rollback 窗口 30 天 | [`lineage/`](lineage/) + [`promoted/`](promoted/) |

## 数据流 / Data flow

```
sessions (4 sessions × user_action.edit)         distillation
  + 'add ask-for-X step'                          run_dist_01K2B0...
       │                                                 │
       ▼ redact + extract                                ▼
   ┌────────────────────────────────────────────────────────┐
   │ feedback/signals.jsonl  (5 signals, agg weight 5.5)    │
   └────────────────────────┬───────────────────────────────┘
                            │ ≥ feedback_min_weight_to_trigger=5.0
                            ▼
   ┌────────────────────────────────────────────────────────┐
   │ iteration/recipe.yaml                                   │
   │   trigger=feedback_signal                               │
   │   hypothesis='add missing-field handling branch'        │
   │   proposed_changes=[body.append]                        │
   └────────────────────────┬───────────────────────────────┘
                            │ propose → vary
                ┌───────────┼─────────────┐
                ▼                         ▼
   variants/var_9930d615/         variants/var_d373c759/
     SKILL.md (body+section)        SKILL.md (body+section + outputs v2)
     meta.yaml                      meta.yaml
                │                         │
                ▼ harness × fixture       ▼
     eval/var_9930d615-...jsonl     eval/var_d373c759-...jsonl
       Δweighted +0.014               Δweighted +0.008
       Δcost     +4.5%                Δcost   +18.3%  ❌
       verdict   winning              verdict losing
                │                         │
                └──────────┬──────────────┘
                           │ decision
                           ▼
   ┌────────────────────────────────────────────────────────┐
   │ iteration/record.yaml                                   │
   │   outcome = promote                                     │
   │   promoted_variant_id = var_9930d615                    │
   │   approval_chain = [vicente@example.com]                │
   └────────────────────────┬───────────────────────────────┘
                            │ apply
                            ▼
   ┌────────────────────────┴───────────────────────────────┐
   │ promoted/SKILL.md  (= var_9930d615/SKILL.md，作为新版本) │
   │ lineage/ticket_summary_zh.yaml  (追加 v1.3.0 条目)       │
   │ rollback_window_until = 2026-05-31T13:20:00Z            │
   └────────────────────────────────────────────────────────┘
```

## 关键 ID（实际计算）/ Key IDs (real-computed)

| 对象 | ID |
|---|---|
| iteration | `itr_01K2B0BRYN8P8R5H2YJ7M9E7N0` |
| variant winning | `var_9930d615` |
| variant losing | `var_d373c759` |
| baseline run | `run_01J0Z9ZQXK7M6P3F0XK5K7C5RR`（复用 zh e2e sample 的） |
| variant run α | `run_01K2B0BRYN8P8R5H2YJ7M9E7VA` |
| variant run β | `run_01K2B0BRYN8P8R5H2YJ7M9E7VB` |
| feedback signals | `fb_..F1A` ~ `fb_..F5E` |
| distillation run | `run_dist_01K2B0BRYN8P8R5H2YJ7M9D` |

## 这个样例**不**演示什么 / What it omits

- **rollback**：本样例只演示首次 promote；rollback 流程留作单独样例（如有需要）
- **iterate_again chain**：本样例 1 轮即收敛；多轮 iteration 链留作单独样例
- **joint iteration**：zh + en 同步演化（policy 中 `joint_iteration.enabled=false`）
- **community-tier 限制**：本 skill 是 `self_authored`；community/unknown 的 sandbox 强制不在本样例覆盖

## 阅读顺序 / Reading order

1. `README.md`（你正在看）
2. `checks.md` —— 跨文件契约自检清单
3. `baseline/SKILL.md` —— 起点 v1.2.0
4. `feedback/signals.jsonl` —— 反馈累积证据
5. `iteration/recipe.yaml` → `iteration/record.yaml` —— 完整 iteration 记录
6. `variants/var_9930d615/` 与 `variants/var_d373c759/` —— 两个候选
7. `eval/*.jsonl` —— 双 variant 评估结果
8. `lineage/ticket_summary_zh.yaml` —— 演化谱系新增条目
9. `promoted/SKILL.md` —— 最终落地版本

## 闭合的本质 / Why this proves the iteration spec is closed

如果以下三组引用任何一组对不上，说明 iteration schema 有缺：

1. **Trigger → Decision recomputability**：给定 `feedback/signals.jsonl` + `iteration-policy`，是否能机械推算出 `trigger.type=feedback_signal` 与 `should_trigger=true`？
2. **Variant identity**：`variants/<id>/meta.yaml#checksum` 与对实际 `SKILL.md` 跑 sha256 是否一致？`variants/<id>/` 文件夹名与 `variant_id` 是否一致？
3. **Promotion gate determinism**：给定 baseline run + variant runs + iteration-policy，是否能机械推算出 winner？`record.yaml#decision.outcome` 是否被 evaluation 数据完全决定（不是人工硬编）？

`checks.md` 列出每条引用与对应 schema 行号。
