---
# Summary page — 单一来源的摘要（直接对应 1 个 raw source）
# 与 schemas/wiki-page.schema.json 等价（kind=summary）

page_id: "wpg_22222222"
slug: "sop-vpn-zh-2026-04-28"
kind: "summary"
title: "Source Summary: VPN 故障排查 SOP（中文）— v1.3.0 / 2026-04-28"
summary: "原 SOP 涵盖 IPSec/IKEv2 VPN 的现象分类表、认证错误排查步骤、隧道故障排查、L2 升级条件。"
namespace: "opspilot:public-kb"
classification: "internal"
language: "zh-CN"
version: "1.0.0"
created_at: "2026-05-01T10:00:00Z"
updated_at: "2026-05-01T10:00:00Z"

tags: ["summary", "vpn", "sop", "L1"]
aliases: []

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_88a277cf"
      sha256: "sha256:88a277cf857f9fdee36c4b8272b40bdfa121e3a9526956f9f21cc7198f3e456d"
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
  summary:
    source_doc_id: "doc_88a277cf"
    source_uri: null
---

# Source Summary: VPN 故障排查 SOP（中文） v1.3.0

## TL;DR

公司 IPSec/IKEv2 VPN 的 L1 排查 SOP。把现象分为三类（认证失败 / 隧道建不起 / 极慢），给每类定关键词与排查路径。**多人同时认证失败 → 服务端鉴权链路**是 SOP 的核心论点。

## Key claims

1. 多人同时认证失败几乎总是服务端问题（非单端）—— 引导排查顺序：日志 → 后端健康 → 控制台试登录 → 时间同步
2. NAT-T 不通会导致 ESP 被丢包 → 隧道建不起；用 UDP 500/4500 可达性测试
3. MTU 经验值：1400 → 1200 逐步降；穿越 NAT 时常见
4. 升级 L2 网络组的判断：多人受影响 + 服务端日志无认证记录

## Implications for our wiki

- 已建 [[vpn-gateway-corp]] entity page，记录主要 facts
- 已建 [[ipsec-vs-ssl-vpn]] concept page，记录协议选型
- **缺失**：[[ssl-vpn-gateway-corp]]、[[vpn-authentication-flow]]、[[radius-auth-backend]] 等 entity / concept page —— 进 lint missing_concept_page 队列
- 已与历史 page 对齐：本 SOP 与既有 entity facts 无冲突

## Cross-links

- describes → [[vpn-gateway-corp]]
- describes → [[ipsec-vs-ssl-vpn]]

## Sources

1. [VPN 故障排查 SOP（中文）](examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md:1-63) — 全文

## Changelog

- v1.0.0 (2026-05-01): initial; from doc_88a277cf
