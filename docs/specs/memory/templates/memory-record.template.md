---
# 中期 memory 记录模板 / Mid-term memory record template
# 字段必须符合 schemas/memory-record.schema.json
# 与 SQLite mid-term 表保持等价（同 id 唯一）

id: "mem_a1b2c3d4"                       # mem_<sha8>；运行时计算
type: "feedback"                         # user | feedback | project | reference
scope: "opspilot:project"                # 命名空间
title: "RCA 不堆时间戳，列因果链"
tags: ["rca", "style"]

source:
  origin: "session"
  session_id: "sess_01J0Z9ZQXK7M6P3F0XK5K7C5K0"
  trace_seq: 42
  document_id: null
  url: null

created_at: "2026-05-01T11:00:00Z"
updated_at: "2026-05-01T11:00:00Z"
valid_until: null
confidence: "high"

redacted: true
redaction_rules_version: "1.0.0"

labels:
  team: "service-desk"
extensions: {}
---

写 RCA 时不要罗列时间戳，列因果链（cause → effect）。

**Why:** 用户在 sess_01J0... 中明确反馈过：堆时间戳让管理层抓不到重点；
他们想看的是"什么导致什么"，时间戳在附录里就够。

**How to apply:**
- 在 `playbooks/rca_*` 中默认输出"3 段因果链 + 附录时间线"
- 评估器（harness）按"是否含 'cause→effect' 或'因为...所以...'结构"打分
- 例外：合规调查类工单仍保留逐条时间戳（governance 要求）
