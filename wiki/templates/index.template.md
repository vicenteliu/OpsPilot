---
# Wiki index — content catalog
# 由 wiki-maintainer skill 在每次 ingest 后自动重排
# 人工只读；不要手编辑

slug: "index"
kind: "concept"           # 复用 concept kind 但 lifecycle 永远 live
title: "Wiki Index"
summary: "Catalog of all wiki pages, grouped by kind."
namespace: "opspilot:public-kb"
classification: "internal"
language: "mixed"
version: "1.0.0"
created_at: "2026-05-01T10:00:00Z"
updated_at: "2026-05-01T10:00:00Z"
tags: ["index", "meta"]
aliases: ["目录", "TOC"]
derived_from:
  sources: []
  parent_pages: []
outbound_links: []
inbound_link_count: 999       # 强制 large 数避免被 lint 误标 orphan
redacted: true
redaction_rules_version: "1.0.0"
lifecycle_state: "live"
owner: "wiki-maintainer-skill"
extensions:
  meta:
    is_meta_page: true
    auto_maintained: true
---

# Wiki Index

> 自动维护。以 `## ` 二级标题分类，列每个 page 一行。
> 解析规则：`^- \[\[(\S+?)\]\] — (.+?) · `（slug · summary · classification · tag）

## Entities

- [[vpn-gateway-corp]] — 公司 IPSec/IKEv2 VPN 网关；RADIUS + AD LDAP 双因子 · `internal` · #vpn #infrastructure
- [[radius-auth-backend]] — RADIUS 认证后端；UDP 1812/1813 · `internal` · #auth
- [[ad-ldap-corp]] — AD LDAP 目录服务；TCP 389/636 · `internal` · #auth

## Concepts

- [[ipsec-vs-ssl-vpn]] — IPSec vs SSL VPN 选型对比 · `internal` · #vpn #concept
- [[vpn-authentication-flow]] — VPN 认证流程：客户端 → 网关 → RADIUS → AD LDAP · `internal` · #auth #flow

## Summaries (one per raw source)

- [[sop-vpn-zh-2026-04-28]] — VPN 故障排查 SOP（中文）v1.3.0 · `internal` · #vpn #sop
- [[summary-ticket-T-XXXX-2026-04-30]] — Session sess_01J0Z9... 工单摘要 · `internal` · #ticket

## Comparisons

- [[radius-vs-ldap-auth]] — RADIUS vs AD LDAP 认证后端选型 · `internal` · #auth #comparison

## Syntheses

- [[vpn-incident-patterns-2026q1]] — 2026 Q1 VPN 故障模式综合（thesis: 80% 在认证链路）· `internal` · #vpn #q1-2026

## Meta

- [[index]] — this page
- [[log]] — chronological ledger

---

**Stats（由 lint 维护）**：
- Total pages: 9
- By kind: entity=3, concept=2, summary=2, comparison=1, synthesis=1
- Orphans: 0
- Open lint issues: 0
- Last updated: 2026-05-01T10:00:00Z
