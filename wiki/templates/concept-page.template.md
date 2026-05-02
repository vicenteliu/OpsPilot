---
# Concept page — 抽象概念或主题
# 与 schemas/wiki-page.schema.json 等价（kind=concept）

page_id: "wpg_11111111"
slug: "ipsec-vs-ssl-vpn"
kind: "concept"
title: "IPSec vs SSL VPN —— 选型对比 / IPSec vs SSL VPN: When to Choose Which"
summary: "IPSec 工作在网络层（L3），SSL VPN 工作在应用层（L7/TLS）；二者在性能、穿透 NAT、客户端复杂度、运维成本上各有取舍。"
namespace: "opspilot:public-kb"
classification: "internal"
language: "zh-CN"
version: "1.0.0"
created_at: "2026-05-01T10:00:00Z"
updated_at: "2026-05-01T10:00:00Z"

tags: ["vpn", "ipsec", "ssl", "concept"]
aliases: ["VPN 选型", "L3 VPN vs L7 VPN"]

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_88a277cf"
      sha256: "sha256:88a277cf857f9fdee36c4b8272b40bdfa121e3a9526956f9f21cc7198f3e456d"
      line_start: 23
      line_end: 23
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

extensions: {}
---

# IPSec vs SSL VPN

## Definition

VPN（Virtual Private Network）的两条主流技术路线：

- **IPSec**：在 IP 层封装加密，常用 IKEv2 做密钥协商；天然支持任意 L3+ 协议；客户端通常需要 OS 级支持。
- **SSL VPN**：在 TLS 之上跑专有应用协议；走 443 端口，**穿透防火墙能力强**；客户端通常是浏览器或轻量代理。

## Why it matters

- **故障模式不同**：IPSec 常见故障在 IKE 协商 / NAT-T / 时间同步；SSL VPN 常见故障在证书 / 浏览器兼容 / 应用代理路由
- **运维边界不同**：IPSec 网关 vs 应用层代理由不同团队维护；同公司若两种并存，[[vpn-incident-patterns-2026q1]] 显示 80% 工单需要先确认是哪种
- **客户端策略不同**：IPSec 全流量；SSL VPN 通常 split-tunnel 仅保护特定应用

## Examples in our environment

- 主入口：[[vpn-gateway-corp]] —— IPSec / IKEv2
- 备用入口：SSL VPN（适用于 BYOD / 第三方协作）—— 待补 entity page

## Trade-offs

| 维度 | IPSec | SSL VPN |
|---|---|---|
| 穿透 NAT/Firewall | 一般（需 NAT-T；UDP 500/4500 可能被屏蔽）| 强（443 / TCP）|
| 性能 | 高 | 中 |
| 客户端复杂度 | 高（OS 集成 / strongSwan / 配置文件）| 低（浏览器 / 轻量代理）|
| 全流量 vs split-tunnel | 通常全流量 | split-tunnel 友好 |
| 运维责任 | 网络组 | 应用 / 接入团队 |

更详细对比见 [[ipsec-vs-ssl-vpn-decision-matrix]]（synthesis page，待生成）。

## Cross-links

- compares → [[vpn-gateway-corp]] (IPSec 主入口)
- see_also → [[vpn-authentication-flow]]
- see_also → [[ssl-vpn-gateway-corp]] (待生成的 entity page)

## Sources

1. [VPN 故障排查 SOP（中文）](examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md:23) — Scope 段对协议范围的定义

## Changelog

- v1.0.0 (2026-05-01): initial; from doc_88a277cf
