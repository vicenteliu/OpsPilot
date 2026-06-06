# Rubric — `scn_ticket_summary_zh` 评分标准

## 元信息 / Metadata

- **scenario_id**：`scn_ticket_summary_zh`
- **rubric_version**：`1.0.0`
- **language**：zh-CN
- **judge_model_pinned**：`anthropic-claude/claude-haiku-4-5@2025-10`
- **rubric_hash**：`sha256:4e7d2f8c9b1a3d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e`（运行时校验）

## 任务定义

输入：脱敏后 IT 工单（含正文 + 附件 log 片段）+ 检索到的 KB chunks（含 citation）。
期望输出：符合 `incident_summary_v1` 的结构化 JSON；引用必须可定位到 `source_path:line_range`。

## 评分维度（与 expected_structured 对齐）

每维 0-4 分；加权后归一到 [0, 1]。

| 维度 | 权重 | 0 | 2 | 4 |
|---|---|---|---|---|
| **现象抓取** | 0.20 | 漏掉关键错误 | 抓主关键字 | 主+次关键字与 log 完全对齐 |
| **范围识别** | 0.15 | 仅说提交人 | 提到"多人" | 量化（"上午 10:00 起多名用户"）|
| **已尝试步骤** | 0.10 | 漏 | 主要 | 全部抓到并去重 |
| **缺失字段** | 0.10 | 没识别 | 1-2 项 | ≥3 项关键缺失 |
| **下一步建议** | 0.15 | 0-1 条或泛泛 | 2 条可执行 | ≥3 条可执行 |
| **严重等级** | 0.05 | 明显不符 | 合理 | 合理 + 给依据 |
| **citation 有效性** | 0.25 | 无引用 | 有引用但定位错 | 引用准确指向 chk_0cf89826 / SOP §2.1 |

## Pass / Fail

- **Pass**：加权得分 ≥ 0.7 **且** 无 hard_fail
- **Hard fail（任一即 fail）**：
  - 输出残留 `[REDACTED:` 占位符在 `summary` 字段
  - 输出虚构日志（fixture 中不存在的 error code）
  - 引用指向不存在的 chunk_id 或 line_range
  - 把脱敏 token 当作真实信息使用

## Judge prompt 骨架

```
你是 OpsPilot 评估器。给定 fixture（输入工单）、output（模型输出）、golden（参考）、rubric。
按 7 个维度给 0-4 分；附 hard_fail 标志；输出 JSON：
{
  "dimensions": {
    "symptom": 0-4, "scope": 0-4, "tried_steps": 0-4,
    "missing_fields": 0-4, "tasks": 0-4,
    "severity": 0-4, "citation_validity": 0-4
  },
  "weighted_score": 0.0-1.0,
  "hard_fail": ["redaction_leak"|"fabricated_log"|"invalid_citation"|...],
  "rationale": "≤200 字"
}
```

## 防偏差

- 不因长度奖罚（除非 rubric 显式提及）
- 不因措辞与 golden 不同扣分；只看维度覆盖
- 简洁可执行 > 冗长详尽

## 历史变更

| 版本 | 日期 | 变更 |
|---|---|---|
| 1.0.0 | 2026-05-01 | 初版，含 RAG citation_validity 维度 |
