---
id: "doc_88a277cf"
source_path: "examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md"
title: "VPN 故障排查 SOP（中文）"
classification: "internal"
content_hash: "sha256:88a277cf857f9fdee36c4b8272b40bdfa121e3a9526956f9f21cc7198f3e456d"
version: "1.3.0"
ingested_at: "2026-05-01T10:00:00Z"
last_modified: "2026-04-28T08:30:00Z"
language: "zh-CN"
tags: ["vpn", "sop", "L1", "ipsec", "ikev2"]
namespace: "opspilot:public-kb"
chunk_strategy: "headings_then_size"
chunk_count: 3
embedding_model: "ollama-local/nomic-embed-text@2024-02"
embedding_dim: 768
redaction_passed: true
redaction_rules_version: "1.0.0"
---

# VPN 故障排查 SOP

> 适用范围：公司 IPSec / IKEv2 VPN；不覆盖 SSL VPN（见 doc_aaaaaaaa）

## 1. 现象分类

按客户端报错与日志关键字快速归位：

| 现象 | 关键词 | 优先怀疑方向 |
|---|---|---|
| 认证失败 | `authentication failed`、`peer auth failed`、`IKE_SA_INIT failed` | 认证后端 / 用户密码 / 时间不同步 |
| 隧道建不起 | `IKE timeout`、`UDP 500/4500 dropped` | 网络层 / 防火墙 / NAT |
| 连上但极慢 | 延迟 > 200ms、吞吐 < 1Mbps | MTU / 拥塞 / 服务端负载 |

## 2. 排查顺序

### 2.1 认证错误

多人同时认证失败基本指向**服务端鉴权链路**，不是单端问题。先做服务端复核：

1. **看客户端日志**：`grep -E "auth|fail" vpn-client.log`，确认是 `peer authentication failed` 还是 `local auth failed`
2. **服务端健康**：RADIUS（端口 1812/1813）/ AD LDAP（389/636）是否在线；近期是否有变更窗口
3. **管理控制台试登录**：用一个测试账号在 VPN 网关后台登录，复现是否同样失败
4. **时间同步**：证书校验对时间敏感；服务端 `chronyc tracking` / 客户端 `ntpq -p`，时差 > 30s 即报错

升级到 L2 的判断：多人受影响 + 服务端日志无认证记录 → L2 网络组。

### 2.2 隧道建立失败

1. 端到端连通：`nc -vzu <vpn_gw> 500` / `nc -vzu <vpn_gw> 4500`
2. ESP（IP 协议号 50）是否被 NAT 设备丢弃：必须支持 NAT-T
3. MTU：`ping -M do -s 1400 <vpn_gw>`，逐步降到 1200 看是否变通

## 3. 升级策略

> - 多人受影响 + 服务端日志无认证记录 → L2 网络组
> - 单人长期无法连接 + 客户端可重装 → L2 终端组
> - 涉及证书过期 / CA 变更 → L3 安全组

## 4. 相关链接

- doc_aaaaaaaa：SSL VPN 排查 SOP
- doc_bbbbbbbb：网络变更窗口 SOP
