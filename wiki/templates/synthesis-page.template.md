---
# Synthesis page — 跨源综合（最有价值；从 ≥2 raw sources 推出 thesis）
# 与 schemas/wiki-page.schema.json 等价（kind=synthesis）

page_id: "wpg_44444444"
slug: "vpn-incident-patterns-2026q1"
kind: "synthesis"
title: "VPN 故障模式综合：2026 Q1 / VPN Incident Patterns Q1 2026"
summary: "基于 12 张 L1 工单 + SOP + 1 篇 RCA 文档的综合：多人认证失败占主导，多源都指向服务端时间同步与 RADIUS 健康监控不足。"
namespace: "opspilot:public-kb"
classification: "internal"
language: "zh-CN"
version: "1.0.0"
created_at: "2026-05-01T10:00:00Z"
updated_at: "2026-05-01T10:00:00Z"

tags: ["synthesis", "vpn", "incident", "Q1-2026"]
aliases: ["VPN Q1 综合"]

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_88a277cf"
      sha256: "sha256:88a277cf857f9fdee36c4b8272b40bdfa121e3a9526956f9f21cc7198f3e456d"
      line_start: null
      line_end: null
    - kind: "session"
      ref: "sess_01J0Z9ZQXK7M6P3F0XK5K7C5K0"
      sha256: null
      line_start: null
      line_end: null
    - kind: "kb_document"
      ref: "doc_aaaaaaaa"     # 假设：另一份 RCA 报告（占位示例）
      sha256: null
      line_start: null
      line_end: null
  parent_pages: []

outbound_links: []
inbound_link_count: 0

redacted: true
redaction_rules_version: "1.0.0"

lifecycle_state: "live"
owner: "vicente@example.com"
collaborators: []

kb_registration:
  kb_doc_id: null
  registered_at: null
  embedding_model: null
  chunk_count: null

lint_state:
  last_linted_at: null
  open_issue_ids: []

extensions:
  synthesis:
    thesis: "2026 Q1 VPN 故障 80% 集中在认证链路；根因聚焦在 NTP 漂移 + RADIUS 单点。补这两块预期能消除多数事件。"
    evidence_count: 5
    counter_evidence_count: 1
---

# VPN 故障模式综合：2026 Q1

## Thesis

> **2026 Q1，公司 VPN 故障 80% 集中在认证链路；根因聚焦在 NTP 漂移 + RADIUS 单点。补这两块预期能消除多数事件。**

## Evidence

1. **多人认证失败 = 服务端问题**（来自 [[sop-vpn-zh-2026-04-28]] / SOP §2.1）—— 不是单端
2. **2026-04-30 工单**（[[summary-ticket-T-XXXX-2026-04-30]]，session sess_01J0Z9...）：典型多人 VPN 认证失败案例，确认服务端鉴权问题
3. **3 月 RCA 报告**（`doc_aaaaaaaa`，占位）：上次大规模事件由 RADIUS HA 切换问题导致（待 ingest 后填实）
4. **客户端日志关键词分布**：12 张工单中 9 张含 `peer authentication failed`（占 75%）
5. **时间同步在 SOP 列为第 4 步排查**——工单数据显示 ≥3 张事件实际根因是时间同步漂移

## Counter-evidence

1. 有 1 张工单（占 8%）实际是 NAT-T 被中间 ISP 设备丢包 —— 与 thesis 不符；说明 thesis 应限定在"周期性 / 多人"范围

## Implications

- **建议建设**：
  - RADIUS HA 健康监控 + 自动 failover 验证（单点是 thesis 第二条）—— 进 [[radius-auth-backend]] 作为 todo
  - VPN 网关、RADIUS、AD LDAP 三方 NTP 同步告警（thesis 第一条）—— 见 [[vpn-gateway-corp]]
- **不建议**：盲目引入 SSL VPN 备用入口 —— 与 thesis 无直接关联（见 [[ipsec-vs-ssl-vpn]] 决策矩阵）

## Gaps

- 缺乏 Q1 整季工单数据库；当前 evidence 来自抽样
- 还未做 NTP 漂移 → 认证失败的精确量化；需要再 ingest 1-2 篇相关源

## Cross-links

- extends → [[sop-vpn-zh-2026-04-28]]
- describes → [[vpn-gateway-corp]]
- describes → [[radius-auth-backend]]
- compares → [[ipsec-vs-ssl-vpn]]
- see_also → [[summary-ticket-T-XXXX-2026-04-30]]

## Sources

1. [VPN 故障排查 SOP（中文）](examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md:37-46) — 认证错误排查步骤
2. [Session sess_01J0Z9ZQXK7M6P3F0XK5K7C5K0](examples/scn_ticket_summary_zh/session/) — 单工单的代表性 session
3. doc_aaaaaaaa（待 ingest 占位）— 3 月 RCA 报告

## Changelog

- v1.0.0 (2026-05-01): initial synthesis from 3 sources
