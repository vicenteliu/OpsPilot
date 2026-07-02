# Skills — 迭代机制详细规范 / Iteration Mechanism Detailed Spec

> 本文档单独成册以避免 SPEC.md 过厚。`skills/SPEC.md §13` 是入口概览；详细看本文。

## TL;DR
让 skill 从 v1.0 → 持续小步演进 → 稳定 v1.x 的结构化机制。三块拼图：

1. **Lineage**：每个 skill 的演化是有向图（`parent_variant_id` / `merged_from`），可追溯每次变更原因
2. **Variants**：同一 skill 的多个候选并行，由 harness 跑矩阵后比对 baseline
3. **Feedback signals**：把 session 中的 user_action、harness 评分、蒸馏候选模式、模型漂移、trace 失败汇集成结构化信号 → 触发新迭代

强约束：所有迭代必须**自动可重算**（recipe + signals + run results = decision），人工 review 只决定"是否 ship"，不重写计算。

## 1. 核心对象 / Core objects

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
FeedbackSignal[] (fb_<ULID> 或 aggregated)
```

| 对象 | 关键字段 | 文件位置 |
|---|---|---|
| Skill | name + version + checksum | `skills/repo/<name>/SKILL.md` |
| Variant | parent_skill_ref, variant_label, status, diff_ref | `skills/repo/<name>/variants/<variant_id>/SKILL.md` |
| Iteration | trigger, hypothesis, proposed_changes, evaluation, decision | `skills/iterations/<itr_id>.yaml` |
| FeedbackSignal | signal_type, weight, source_ref | `skills/feedback/<skill_ref>/<fb_id>.yaml` 或聚合 jsonl |

## 2. Trigger taxonomy / 触发分类

每次 iteration 必须有明确的 trigger 类型：

| trigger.type | 触发条件 | 自动/手动 |
|---|---|---|
| `regression_detected` | harness 回归门掉点 > policy.regression_threshold | 自动 |
| `feedback_signal` | 累积反馈权重 ≥ policy.feedback_min_weight_to_trigger | 自动 |
| `distillation_candidate` | 从 traces 蒸馏出与现 skill 显著不同的候选 pattern（min_support 满足） | 自动 |
| `model_upgrade` | model_compat 中某个 model_ref 版本升级 | 自动 |
| `scheduled` | cron（如周一全量回归） | 自动 |
| `manual` | 人工指定（含 hypothesis 文本） | 手动 |

未声明 trigger 的 iteration 在加载时拒绝。

## 3. Variant 生命周期 / Variant lifecycle

```
              ┌──────────┐
              │  draft   │  作者/迭代刚创建；未跑 eval
              └────┬─────┘
                   │ run trigger eval + harness fixtures
                   ▼
              ┌──────────┐
              │  active  │  正在与 baseline 比较中
              └────┬─────┘
       ┌───────────┼───────────────┐
       │           │               │
       ▼           ▼               ▼
   ┌────────┐ ┌────────┐      ┌────────┐
   │winning │ │ losing │      │ merged │  与其他 variant 合并
   └───┬────┘ └───┬────┘      └────┬───┘
       │ promote   │ archive       │ promote merged variant
       ▼           ▼               ▼
  ┌─────────┐ ┌────────────────────────┐
  │promoted │ │  archived (kept N days)│
  └─────────┘ └────────────────────────┘
       │ becomes new stable; old stable 进入 rollback window
       ▼
   updates registry to new version
```

### 3.1 状态转移规则

- 同一 skill 同时 active 的 variant 数量 ≤ `policy.max_concurrent_active`（默认 3）
- variant_max_lifetime_days 到期未 promote 自动 archive
- promoted variant 必须把上一版本 stable 标记为 deprecated（grace 30d）

## 4. Iteration 流程 / Pipeline

```
sense  ──▶  propose  ──▶  vary  ──▶  evaluate  ──▶  decide  ──▶  apply
  │           │           │           │             │            │
  ▼           ▼           ▼           ▼             ▼            ▼
signals    hypothesis   variant(s)  run results   outcome     registry
                                                              update
```

| 阶段 | 输入 | 输出 | 失败处理 |
|---|---|---|---|
| sense | feedback signals + triggers | 是否启动 iteration | 不达阈值 → 返回 |
| propose | trigger + signals | hypothesis + proposed_changes | LLM 生成失败 → 重试 N 次 |
| vary | proposed_changes | 1..M variant SKILL.md drafts | schema 校验失败 → reject |
| evaluate | baseline + variants × fixtures | 矩阵 results | 任一 hard_fail → variant losing |
| decide | results + policy | promote / reject / merge / iterate_again | 不达晋升标准 → reject |
| apply | decision | registry update + version bump | 失败回滚 |

## 5. Decision rules / 决策规则

variant 进入 `winning` 必须**全部满足**（来自 `iteration-policy`）：

1. 在 anchor fixtures 上**无回归**（pass_rate 不低于 baseline）
2. 在新增 fixtures（针对本次迭代假设设计）上**通过率 ≥ baseline + min_delta_weighted**
3. cost 增长 ≤ `max_cost_increase_pct`（默认 10%）
4. trigger eval 仍满足（recall ≥ 0.9, FP ≤ 0.05）
5. 静态检查全过（PII / prompt-injection / tool resolvable）

不满足任一条 → losing → 进入 archive。

## 6. Promotion vs merge / 晋升 vs 合并

- **Promotion**：单 variant 直接成为新 stable
- **Merge**：多 variant 各自包含部分改进，合并它们的差异成新 variant 再走 evaluate

合并算法（spec 阶段不强制实现路径，约定接口）：
```
merge(variants[]) → new_variant
  inputs:
    base = baseline.SKILL.md
    diffs[] = each variant's diff vs baseline
  output:
    SKILL.md with diffs union, conflicts surfaced for human resolve
```

## 7. Feedback ingestion / 反馈摄入

### 7.1 信号类型

| signal_type | 来源 | weight 默认 |
|---|---|---|
| `user_action.accept` | session.trace `user_action.accept` | +1.0 |
| `user_action.reject` | session.trace `user_action.reject` | -2.0 |
| `user_action.edit` | session.trace `user_action.edit`（含 payload_diff）| -1.0（带 diff 提示具体问题）|
| `harness_score` | harness.results 的 weighted score 与 baseline diff | × 5（强信号）|
| `distillation_pattern` | 蒸馏出新 pattern + min_support 满足 | +1.0 per pattern |
| `model_drift` | trigger eval 在 model 升级后掉点 | +3.0 |
| `trace_failure` | tool_result.status=failed 频率提高 | +2.0 |

### 7.2 聚合规则

每个 skill 维护一个 `signals.jsonl`（append-only）。聚合：
- **滑动窗口**：默认 30 天
- **加权和** `Σ(weight × decay)`，decay = `0.9^days_since`
- **达阈值** `feedback_min_weight_to_trigger`（默认 5.0）→ 触发 iteration `feedback_signal`

### 7.3 强约束

- 所有 signals 必须脱敏（不允许携带原 prompt 内容）
- session_id 引用受 retention 约束；过期 → signal 仍保留但 source 字段降级为 hash 引用

## 8. Lineage / 演化谱系

每个 stable skill 的演化历史存于 `skills/lineage/<skill_name>.yaml`：

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

## 9. Rollback / 回滚

- 默认保留最近 `preserve_previous_n_versions`（默认 3）个稳定版本
- `can_rollback_within_days`（默认 30）：30 天内可一键回滚
- 回滚操作走 audit + 记录在 lineage 上为新条目（不修改历史）

## 10. 与其他目录的接口 / Interfaces

### 10.1 Harness（评估侧）

新增 evaluator 类型：
- `iteration.delta`：variant 对比 baseline 的多维度 delta（pass_rate / cost / latency / per-evaluator score）
- `iteration.no_regression_on_anchors`：在 anchor fixtures 上无回归
- `iteration.trigger_eval_recall`：trigger eval 是否仍达标

### 10.2 Session（信号源）

session.trace 中新增可选事件：
```yaml
type: "system"
event: "feedback_capture"
details:
  skill_ref: "ticket_summary_zh@1.2.0"
  signal_type: "user_action.edit"
  weight: -1.0
  payload_ref: "art_<sha8>"   # diff 内容走 artifact
```

### 10.3 Memory（蒸馏候选）

蒸馏 pipeline 在 `mine` 阶段产出的"与现 skill 显著不同的 pattern"自动作为 `distillation_pattern` 信号注入 feedback collector。

## 11. 强约束 / Hard requirements

- 每个 iteration 必须有 trigger.type
- variant 必须有 parent_skill_ref + diff vs parent
- 决策结果必须可重算（recipe + signals + run results 给定，结论应一致）
- promoted variant 必须更新 lineage + 旧 stable 进 rollback window
- losing variant 不允许直接删除；archive 至少保留 `variant_max_lifetime_days`
- iteration 与 variant 的所有 ID 必须满足 ULID/sha8 模式（见 schemas）

## 12. 反模式 / Anti-patterns

- ❌ 跳过 evaluate 直接 promote（手动 trigger 也必须跑 fixtures）
- ❌ 同一 iteration 同时改 description + body + requires.tools（一次改一个变量；多变量混改无法归因）
- ❌ 用过期的 fixtures（fixtures 必须随 model_ref 一起锁版本）
- ❌ feedback signals 不脱敏直接入库
- ❌ 把 user_action.edit 的 diff 视为权威（用户也可能错；diff 是信号，不是答案）

## 13. 开放问题 / Open questions

- [ ] variant 之间的 conflict 自动 merge 策略（schema 字段冲突 vs body 章节冲突）
- [ ] 多 skill 联合迭代（如 `ticket_summary_zh` 与 `ticket_summary_en` 的描述风格同步演化）
- [ ] 回滚是否要求把 lineage 上的"虚假 promotion"标记 voided？还是单纯加新条目？
- [ ] 跨工作空间的 lineage 合并（fork-and-merge model）
