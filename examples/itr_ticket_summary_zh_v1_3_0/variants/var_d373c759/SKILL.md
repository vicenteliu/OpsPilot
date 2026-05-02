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
  schema_ref: "examples/itr_ticket_summary_zh_v1_3_0/variants/var_beta_pending/missing_fields_v2.schema.json"
  description: "ticket_summary_v1 with structured missing_fields[] (each item has field_name + reason + priority)"

redacted: true
redaction_rules_version: "1.0.0"

tags: ["ticket", "L1", "zh-CN", "rag", "experimental"]
labels:
  team: "service-desk"

extensions: {}
---

# Ticket Summary (zh-CN)

## 触发条件 / When to use

输入包含**已脱敏**的 IT 工单（含正文 + 可选附件 log 片段），用户希望产出结构化摘要。

## 步骤 / Steps

1. **检索 KB**：用工单关键症状（如 "VPN 认证失败"）调 `kb.search`，scopes 默认走 `opspilot:public-kb`，top_k=8，hybrid 模式 + cross_encoder rerank。
2. **生成结构化摘要**：填充扩展的 `ticket_summary_v2` schema 的所有 required keys（注意 missing_fields 已升级为结构化数组）。
3. **citation 必填**：每个 `next_actions[].rationale` 引用 chunk 时，citations 字段必须能定位回 `source_path:line_range`。
4. **写入 artifact**：调 `artifact.write`，filename = `art_<sha256(payload)[:16]>.json`。

## 强约束 / Hard rules

- 输出 `summary` 字段不允许出现 `[REDACTED:` 占位符
- `severity_suggested` 必须匹配 `^P[0-4]$`
- `next_actions` 至少 3 条
- 引用的 chunk_id 必须在 `kb.search` 响应里命中过
- `missing_fields[]` 每项必须含 `field_name` / `reason` / `priority` 三个属性（v2 schema 要求）

## 失败处理 / Failure modes

- KB 无命中：依然产出摘要，但 `citations: []`
- 工单含未脱敏 PII：拒绝处理；返回 `safety_violation` 并写入 `tool_result.status=aborted`

## 缺失字段结构化处理 / Structured missing-field handling（v1.3.0 新增）

当工单缺少诊断字段时，对每个缺失项产出完整结构化对象：

```json
{
  "field_name": "VPN 客户端版本",
  "reason": "影响 IPSec 协议栈兼容性判断；不同版本 NAT-T 行为有差异",
  "priority": "high",
  "suggested_phrasing": "请提供 VPN 客户端的版本号（在客户端 关于 / About 菜单中可见）",
  "depends_on": null,
  "blocks_severity_decision": false
}
```

每个字段都需要：
1. **field_name**：标准化字段名
2. **reason**：为什么需要（≥30 字解释）
3. **priority**：high / medium / low
4. **suggested_phrasing**：直接可发给用户的话术
5. **depends_on**：是否依赖其他缺失字段先回答（用于序列化追问）
6. **blocks_severity_decision**：是否决定性影响 severity 判定

输出冗长但便于后续自动化（如自动生成回工单的追问 email 模板、按 priority 排队）。
