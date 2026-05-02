---
name: "ticket_summary_zh"
description: "Summarize a redacted Chinese IT support ticket and emit a ticket_summary_v1 JSON with citations to KB SOPs. Trigger when input includes a ticket body or vpn-client-style log snippet. Requires kb.search and an LLM with json_mode."
version: "1.3.0"
language: "zh-CN"

author: "vicente@example.com"
source: "self_authored"
license: "MIT"

model_compat:
  - "@chat-strong"
  - "anthropic-claude/claude-sonnet-4-6@2026-04"
  - "openai-main/gpt-4o@2024-11-20"

requires:
  tools:
    - "kb.search"
    - "artifact.write"
  mcps: []
  providers:
    tools: true
    json_mode: true
    long_context_tokens: 32000
  skills: []

safety:
  classification: "internal"
  approval_required: false
  telemetry_optout: true
  pii_allowed: false

inputs:
  schema_ref: "examples/scn_ticket_summary_zh/harness/fixture.json#input"
  description: "Redacted ticket payload (subject + body + log attachment)"
outputs:
  schema_ref: "examples/scn_ticket_summary_zh/harness/golden.json#schema_check"
  description: "ticket_summary_v1 structured JSON"

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

- 输出 `summary` 字段不允许出现 `[REDACTED:` 占位符
- `severity_suggested` 必须匹配 `^P[0-4]$`
- `next_actions` 至少 3 条
- 引用的 chunk_id 必须在 `kb.search` 响应里命中过

## 失败处理 / Failure modes

- KB 无命中：依然产出摘要，但 `citations: []`
- 工单含未脱敏 PII：拒绝处理；返回 `safety_violation` 并写入 `tool_result.status=aborted`

## 缺失字段处理 / Missing field handling（v1.3.0 新增）

当工单缺少**关键诊断字段**时（VPN 客户端版本、受影响账号清单、变更窗口时间等），不要在 `next_actions` 里只写 "建议人工补充"。改为生成**针对性追问**：

1. **识别缺失项**：对照 `outputs.schema.missing_fields_min` 清单与本工单已有信息，列出真正缺的项
2. **生成追问步骤**：在 `next_actions` 中加入 `action: "向用户索取 <字段名>"` 类型的步骤，每条配 `rationale: "<为什么需要这一项才能继续>"`
3. **不阻塞主流程**：即使关键字段缺失，仍输出基于已有信息的临时摘要 + severity 估计；标记 `severity_suggested` 后加注 `(待信息确认)`
4. **优先级**：影响 P0/P1 严重等级判定的字段（如受影响范围）排在追问列表最前面
