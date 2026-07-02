---
# SKILL.md 模板 / Skill template
# 与 schemas/skill.schema.json 等价

name: "ticket_summary_zh"
description: "Summarize a redacted Chinese IT support ticket and emit a ticket_summary_v1 JSON with citations to KB SOPs. Trigger when input includes a ticket body or vpn-client-style log snippet. Requires kb.search and an LLM with json_mode."
version: "1.2.0"
language: "zh-CN"

author: "vicente@example.com"
source: "self_authored"             # self_authored | distilled | imported_trusted | imported_community | imported_unknown
license: "MIT"

# 兼容模型；用 registry alias 或具体 model_ref；禁用 latest/auto/stable
model_compat:
  - "@chat-strong"
  - "anthropic-claude/claude-sonnet-4-6@2026-04"
  - "openai-main/gpt-4o@2024-11-20"

requires:
  tools:
    - "kb.search"
    - "artifact.write"
  mcps: []                          # MCP server ids；本 skill 不需要外部 MCP
  providers:
    tools: true                     # 模型必须支持 tool calling
    json_mode: true
    long_context_tokens: 32000
  skills: []                        # 依赖的其他 skill

safety:
  classification: "internal"        # public | internal | confidential | restricted
  approval_required: false
  telemetry_optout: true
  pii_allowed: false                # 输入禁含 PII；触发即拒绝

inputs:
  schema_ref: "examples/scn_ticket_summary_zh/harness/fixture.json#input"
  description: "Redacted ticket payload (subject + body + log attachment)"
outputs:
  schema_ref: "examples/scn_ticket_summary_zh/harness/golden.json#schema_check"
  description: "ticket_summary_v1 structured JSON"

# 若 source ≠ self_authored，distillation 段必填
# distillation:
#   type: "from_traces"
#   sources:
#     - "sess_01J0Z9ZQXK7M6P3F0XK5K7C5K0"
#   pipeline_run: "run_dist_01J0Z9ZQXK7M6P3F0XK5K7"
#   distilled_at: "2026-05-01T12:00:00Z"
#   redaction_rules_version: "1.0.0"

redacted: true
redaction_rules_version: "1.0.0"

tags: ["ticket", "L1", "zh-CN", "rag"]
labels:
  team: "service-desk"

extensions: {}
---

# Ticket Summary (zh-CN)

## 触发条件 / When to use

输入包含**已脱敏**的 IT 工单（含正文 + 可选附件 log 片段），用户希望产出结构化摘要。

## 步骤 / Steps

1. **检索 KB**：用工单关键症状（如 "VPN 认证失败"）调 `kb.search`，scopes 默认走 `opspilot:public-kb`，top_k=8，hybrid 模式 + cross_encoder rerank。
2. **生成结构化摘要**：填充 `ticket_summary_v1` schema 的所有 required keys。
3. **citation 必填**：每个 `next_actions[].rationale` 引用 chunk 时，citations 字段必须能定位回 `source_path:line_range`。
4. **写入 artifact**：调 `artifact.write`，filename = `art_<sha256(payload)[:16]>.json`。

## 强约束 / Hard rules

- 输出 `summary` 字段不允许出现 `[REDACTED:` 占位符（保留在技术细节字段也不行）
- `severity_suggested` 必须匹配 `^P[0-4]$`
- `next_actions` 至少 3 条，每条要么 actionable，要么标注 missing-info
- 引用的 chunk_id 必须在 `kb.search` 响应里命中过

## 失败处理 / Failure modes

- KB 无命中：依然产出摘要，但 `citations: []`，并在 `next_actions` 中加 "建议人工补充 SOP"
- 工单含未脱敏 PII：拒绝处理；返回 `safety_violation` 并写入 `tool_result.status=aborted`

## 资源 / Resources

- `resources/rubric.md` —— 评分维度（与 harness rubric 同步）
- `resources/example-output.json` —— 标杆输出，用于 in-context learning
