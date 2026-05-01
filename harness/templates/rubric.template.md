# Rubric — `scn_<scenario_id>` 评分标准模板

> 该 rubric 同时给 **LLM-judge** 与 **人工抽样** 使用。LLM-judge 必须锁定 judge 模型版本与该 rubric 的 hash。
> 写得越具体，judge 越稳定；尽量给"通过/失败"的可观察特征。

## 0. 元信息 / Metadata

- **scenario_id**：`scn_ticket_summary_zh`
- **rubric_version**：`1.0.0`
- **language**：zh-CN
- **judge_model_pinned**：`anthropic/claude-haiku-4-5@2025-10`（**不要**用 `latest`）

## 1. 任务定义 / Task definition

输入：脱敏后的 IT 工单（含正文与附件 log 片段）。
期望输出：结构化摘要 JSON（schema 见 golden.template.json 的 `expected_structured`）。

## 2. 评分维度 / Dimensions

每个维度 0–4 分；总分加权后归一到 [0, 1]。

| 维度 | 权重 | 0 分 | 2 分 | 4 分 |
|---|---|---|---|---|
| **现象抓取** | 0.25 | 漏掉错误关键字 | 抓到主关键字 | 抓到主+次关键字并对齐 log |
| **范围识别** | 0.15 | 仅描述提交人 | 提到"多名用户" | 量化描述（"上午 10:00 起多名用户"） |
| **已尝试步骤** | 0.15 | 漏掉 | 抓到主要 | 全部抓到并去重 |
| **缺失字段** | 0.15 | 没识别 | 识别 1–2 项 | 识别 ≥3 项关键缺失 |
| **下一步建议** | 0.20 | 无或泛泛 | 给 1–2 条 | 给 3 条且可执行 |
| **严重等级** | 0.10 | 与场景明显不符 | 合理 | 合理且给出依据 |

## 3. Pass / Fail 判定

- **Pass**：加权得分 ≥ 0.7 **且** 无以下 hard fail
- **Hard fail（任一即 fail）**：
  - 输出残留 `[REDACTED:` 占位符在 `summary` 字段
  - 输出虚构日志内容（fixture 中不存在的 error code）
  - 把 fixture 中的脱敏 token 当作真实信息使用

## 4. Judge 提示骨架 / Judge prompt skeleton

```
你是 OpsPilot 评估器。给定输入工单（fixture）、模型输出（output）、参考输出（golden）、rubric。
请按 rubric 的每个维度给 0–4 分，并填写 hard_fail 标志。
仅返回 JSON：
{
  "dimensions": {
    "symptom": 0-4,
    "scope": 0-4,
    "tried_steps": 0-4,
    "missing_fields": 0-4,
    "next_actions": 0-4,
    "severity": 0-4
  },
  "weighted_score": 0.0-1.0,
  "hard_fail": ["redaction_leak"|"fabricated_log"|...],
  "rationale": "≤200 字"
}
```

## 5. 防偏差 Notes / Anti-bias

- 不要因输出**长度**奖励或惩罚（除非 rubric 显式提及）
- 不要因输出与 golden **措辞不同**而扣分；只看是否覆盖维度
- 同等条件下，**简洁可执行 > 冗长详尽**

## 6. 历史变更 / Change log

| 版本 | 日期 | 变更 | 影响范围 |
|---|---|---|---|
| 1.0.0 | 2026-05-01 | 初版 | 全量回归基线建立 |
