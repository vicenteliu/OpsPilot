---
# Entity page — 单一对象（系统、工具、团队、人物、产品）
# 与 schemas/wiki-page.schema.json 等价（kind=entity）

page_id: "wpg_00000000"           # wpg_<sha8>；运行时计算
slug: "vpn-gateway-corp"
kind: "entity"
title: "公司 VPN 网关 / Corporate VPN Gateway"
summary: "公司 IPSec/IKEv2 VPN 网关；负责员工远程接入；后端走 RADIUS + AD LDAP 双因子。"
namespace: "opspilot:public-kb"
classification: "internal"
language: "zh-CN"
version: "1.0.0"
created_at: "2026-05-01T10:00:00Z"
updated_at: "2026-05-01T10:00:00Z"

tags: ["vpn", "ipsec", "ikev2", "infrastructure"]
aliases: ["VPN 网关", "Corporate VPN", "IPSec gateway"]

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_88a277cf"
      sha256: "sha256:88a277cf857f9fdee36c4b8272b40bdfa121e3a9526956f9f21cc7198f3e456d"
      line_start: 21
      line_end: 33
  parent_pages: []

outbound_links: []                # 机器维护
inbound_link_count: 0             # 由 lint 回填

redacted: true
redaction_rules_version: "1.0.0"

lifecycle_state: "live"
owner: "vicente@example.com"
collaborators: []

kb_registration:
  kb_doc_id: null                 # 进入 live 后由 wiki→KB 注册流程回填
  registered_at: null
  embedding_model: null
  chunk_count: null

lint_state:
  last_linted_at: null
  open_issue_ids: []

extensions:
  entity:
    related_entities:
      - "radius-auth-backend"
      - "ad-ldap-corp"
    related_concepts:
      - "ipsec-vs-ssl-vpn"
      - "vpn-authentication-flow"
---

# 公司 VPN 网关 / Corporate VPN Gateway

## What is it

公司远程接入主入口；基于 IPSec / IKEv2，对外暴露 UDP 500（IKE）+ UDP 4500（NAT-T）。

## Key facts

- **协议**：IKEv2 over UDP；ESP（IP 协议号 50）走 NAT-T 封装
- **认证后端**：RADIUS（端口 1812/1813）→ AD LDAP（389/636）双因子
- **客户端**：strongSwan / Windows 内建 VPN / macOS 内建 VPN
- **常见症状关键词**：`authentication failed`、`peer auth failed`、`IKE_SA_INIT failed`、`IKE timeout`
- **多人同时认证失败 → 服务端鉴权链路问题**（不是单端）—— 见 [[ipsec-vs-ssl-vpn]]

## Diagnostics quick start

1. 客户端日志：`grep -E "auth|fail" vpn-client.log`
2. 服务端健康：RADIUS / AD LDAP 端口可达
3. 时间同步：`chronyc tracking` / `ntpq -p`，> 30s 偏差即报错

## Related

- describes → [[radius-auth-backend]]: RADIUS 后端的具体实现
- describes → [[ad-ldap-corp]]: AD LDAP 服务
- depends_on → [[ipsec-vs-ssl-vpn]]: 协议选型背景

## Cross-links

- describes → [[radius-auth-backend]]: 认证链路上游
- describes → [[ad-ldap-corp]]: 认证链路上游
- see_also → [[ipsec-vs-ssl-vpn]]
- see_also → [[vpn-incident-patterns-2026q1]]

## Sources

1. [VPN 故障排查 SOP（中文）](examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md:21-33) — 现象分类表与协议范围
2. [VPN 故障排查 SOP（中文）](examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md:37-46) — 认证错误排查步骤

## Changelog

- v1.0.0 (2026-05-01): initial; from doc_88a277cf
