# Harness — 评估与回归骨架 / Eval & Regression Harness

> **状态 / Status**：规范阶段（spec-only）。本目录只定义对象模型、模板与配置 schema；不含运行器实现。
> **Stage**：spec only — object model, templates, config schemas. No runner here.

## TL;DR
Harness（评估骨架）= 给 Prompt / Playbook 上"单元测试 + 回归门"。每次改 prompt、换模型、调温度——都能跑出 pass rate / 成本 / 延迟 / 回归 delta，避免"改一处坏一片"。

## 概念模型 / Conceptual model

```
Scenario（场景）
  ├── Fixture（用例输入快照）
  ├── Golden  （期望输出）
  ├── Rubric  （评分标准，给 LLM-judge 用）
  └── Evaluators（评估器列表）

Run（一次评估运行）
  = Scenario × Playbook × Model × Evaluators
  → Result（per fixture）→ Report（聚合）
```

## 设计原则 / Principles

1. **不重复造轮子**：以"适配层"形式对接 promptfoo / OpenAI Evals / Inspect AI；harness 只定义契约。
2. **Fixture 先脱敏**：进入 harness 的输入必须已脱敏，可公开提交到仓库。
3. **多模型可比**：同一组 fixture/golden 必须能跨模型矩阵跑（GPT-x / Claude / Llama / Qwen）。
4. **回归门可阻断**：CI 中跑，关键指标掉点 > 阈值 → 阻断 merge。
5. **可解释**：每条 Result 都能追到哪个 fixture / playbook 版本 / 模型 / evaluator。

## 范围 / Scope

In scope：
- 对象模型（Scenario / Fixture / Golden / Rubric / Evaluator / Run / Result / Report）
- 评估器类型（rule / schema / semantic / judge / sandbox-exec）
- 指标定义（pass rate / regression delta / cost / latency / token）
- 配置 schema 与模板

Out of scope：
- 具体 runner 实现（Python / Go）
- UI 报告页（仅约定 JSON 报告 schema）
- 数据集托管（DVC/HuggingFace 选型留待后续）

## 目录结构 / Directory layout

```
harness/
├── README.md                          # 本文件
├── SPEC.md                            # 对象模型 + 评估器分类 + 指标定义
├── schemas/
│   ├── fixture.schema.json            # 用例
│   └── eval-result.schema.json        # 单条评估结果
└── templates/
    ├── fixture.template.json          # 示例 fixture
    ├── golden.template.json           # 示例 golden
    ├── rubric.template.md             # 评分标准模板
    └── eval-config.template.yaml      # 一次 Run 的配置
```

## 推荐目录结构（用户使用时）/ Recommended layout for users

```
harness-data/
├── fixtures/<scenario_id>/<fixture_id>.json
├── goldens/<scenario_id>/<fixture_id>.json
├── rubrics/<scenario_id>.md
└── runs/<run_id>/
    ├── config.yaml
    ├── results.jsonl       # 每行一个 eval-result
    └── report.{md,html}
```

## Quickstart（给读规范的人）

1. 读 `SPEC.md` 了解对象模型与指标定义
2. 用 `templates/fixture.template.json` 起一个用例（**注意先脱敏**）
3. 用 `templates/golden.template.json` 写期望输出 + `rubric.template.md` 写评分标准
4. 用 `templates/eval-config.template.yaml` 配置一次 Run
5. 把 `eval-result.schema.json` 作为 CI 回归门校验目标

## 与其他目录的契约 / Contracts

| 上游 | 给 Harness 的输入 |
|---|---|
| `prompts/` | prompt id + version |
| `playbooks/` | playbook id + version |
| `session/` | trace.jsonl 可作为 fixture 的来源（脱敏后） |

| 下游 | Harness 提供的产物 |
|---|---|
| CI（GitHub Actions / GitLab CI） | 退出码 + report |
| `case-studies/` | 报告归档（人类可读 markdown） |

## 开放问题 / Open questions

- [ ] LLM-as-judge 的评判模型本身要不要锁版本（避免 judge 漂移）？
- [ ] cost/latency 跨厂商可比性：用 token 数还是用美元/RMB 金额？
- [ ] 自有内网模型（本地 Ollama / vLLM）的 fixture 共享策略？
