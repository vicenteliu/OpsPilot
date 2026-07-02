---
# 长期 KB 文档模板 / Long-term KB document template
# frontmatter 字段须符合 schemas/kb-document.schema.json
# 文档内容（frontmatter 之外的 markdown 正文）会被 chunked + embedded

id: "doc_e5f6g7h8"
source_path: "playbooks/sop_vpn_zh.md"
source_url: null
title: "VPN 故障排查 SOP（中文）"
classification: "internal"
content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000"
version: "1.3.0"
ingested_at: "2026-05-01T10:00:00Z"
last_modified: "2026-04-28T08:30:00Z"
language: "zh-CN"
tags: ["vpn", "sop", "L1", "ipsec"]
namespace: "opspilot:public-kb"

chunk_strategy: "headings_then_size"
chunk_count: 12

embedding_model: "ollama-local/nomic-embed-text@2024-02"
embedding_dim: 768

redaction_passed: true
redaction_rules_version: "1.0.0"

license: null
extensions: {}
---

# VPN 故障排查 SOP

> 适用范围：公司 IPSec/IKEv2 VPN；不覆盖 SSL VPN（见 doc_xxxxxxxx）

## 1. 现象分类

| 现象 | 关键词 | 优先怀疑 |
|---|---|---|
| 认证失败 | `authentication failed`、`peer auth failed`、`IKE_SA_INIT 错误` | 认证后端 / 用户密码 / 时间不同步 |
| 隧道建不起 | `IKE timeout`、`UDP 500/4500 dropped` | 网络层 / 防火墙 / NAT |
| 速度极慢 | 连上但延迟 > 200ms、吞吐 < 1Mbps | MTU / 拥塞 / 服务端负载 |

## 2. 排查顺序

### 2.1 认证错误
1. 看客户端日志：`grep -E "auth|fail" vpn-client.log`
2. 确认服务端：RADIUS / AD 是否健康（端口 1812/1813、LDAP 389/636）
3. 用 `[USERNAME]` 在管理控制台试登录（不要用真实账号入工单）
4. 时间不同步会导致证书校验失败：`ntpq -p` / `chronyc tracking`

### 2.2 隧道建立失败
1. 端到端连通：`nc -vzu <vpn_gw> 500` / `nc -vzu <vpn_gw> 4500`
2. ESP（IP 协议号 50）是否被 NAT 设备丢弃：必须支持 NAT-T
3. MTU：`ping -M do -s 1400 <vpn_gw>`，逐步降到 1200 看是否变通

## 3. 升级策略

> 升级到 L2 的判断：
> - 多人受影响 + 服务端日志无认证记录 → L2 网络组
> - 单人长期无法连接 + 客户端可重装 → L2 终端组

## 4. 相关链接

- doc_aaaaaaaa：SSL VPN 排查 SOP
- doc_bbbbbbbb：网络变更窗口 SOP
