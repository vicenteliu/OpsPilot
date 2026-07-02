---
# Comparison page — 多对象/方案对比
# 与 schemas/wiki-page.schema.json 等价（kind=comparison）

page_id: "wpg_33333333"
slug: "radius-vs-ldap-auth"
kind: "comparison"
title: "RADIUS vs AD LDAP — 认证后端选型对比"
summary: "对比 RADIUS 与 AD LDAP 在 VPN 认证场景下的延迟、可用性、可观察性、运维边界差异。"
namespace: "opspilot:public-kb"
classification: "internal"
language: "zh-CN"
version: "1.0.0"
created_at: "2026-05-01T10:00:00Z"
updated_at: "2026-05-01T10:00:00Z"

tags: ["comparison", "auth", "radius", "ldap"]
aliases: ["认证后端对比"]

derived_from:
  sources:
    - kind: "kb_document"
      ref: "doc_88a277cf"
      sha256: "sha256:88a277cf857f9fdee36c4b8272b40bdfa121e3a9526956f9f21cc7198f3e456d"
      line_start: 42
      line_end: 42
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
  comparison:
    subjects:
      - "RADIUS"
      - "AD LDAP"
    criteria:
      - "协议端口"
      - "延迟"
      - "可观察性"
      - "高可用方案"
      - "运维责任"
---

# RADIUS vs AD LDAP

## Subjects

- **RADIUS**：经典 AAA 协议，端口 UDP 1812（auth）/ 1813（accounting）
- **AD LDAP**：基于 LDAP 的目录服务，端口 TCP 389（明文）/ 636（TLS）

## Comparison table

| 维度 | RADIUS | AD LDAP |
|---|---|---|
| 端口 | UDP 1812/1813 | TCP 389/636 |
| 协议层语义 | AAA（认证 + 授权 + 账务）| 目录查询（authenticate via simple bind 或 SASL）|
| 延迟 | 低（UDP，单 RTT 一般 < 50ms 内网）| 中（TCP 握手 + 可能 TLS 握手）|
| 高可用 | proxy / multiple servers | DC replication |
| 失败可观察性 | 计费/拒绝原因明确 | bind 错误码 + LDAP 32/49/53 等 |
| VPN 场景常见用法 | 前置认证（用户名+密码 / OTP）| RADIUS 后端再去查 AD LDAP |
| 故障排查关键词 | `Access-Reject`、`silently discarded` | `LDAP_INVALID_CREDENTIALS`（49）、`LDAP_NO_SUCH_OBJECT`（32）|

## Verdict / when to use which

- 多数公司 VPN 场景：**RADIUS 在前，AD LDAP 在后**（RADIUS 把请求转给 AD LDAP）—— 见 [[vpn-gateway-corp]]
- 单纯应用登录（HTTP API、内部工具）：**AD LDAP 直接 bind**
- 需要计费/会话计数 → RADIUS（accounting 包）
- 需要存放复杂用户属性 → AD LDAP

## Cross-links

- compares → [[radius-auth-backend]]
- compares → [[ad-ldap-corp]]
- depends_on → [[vpn-gateway-corp]]
- see_also → [[vpn-authentication-flow]]

## Sources

1. [VPN 故障排查 SOP（中文）](examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md:42) — RADIUS / AD LDAP 端口与排查路径

## Changelog

- v1.0.0 (2026-05-01): initial; from doc_88a277cf
