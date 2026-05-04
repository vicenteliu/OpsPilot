---
schema_version: "kb-document-v1"
title: "网络设备定期维护 SOP（中文）"
language: "zh-CN"
classification: "internal"
tags: ["network", "maintenance", "sop", "switch", "router"]
version: "1.0.0"
created_at: "2026-05-01T08:00:00Z"
---

# 网络设备定期维护 SOP

本 SOP 适用于 IT 运维团队对园区核心/接入层网络设备（交换机、路由器、防火墙）执行定期维护操作。

## 1. 维护窗口

- **每月第一个周六 00:00–04:00（本地时间）** 为标准维护窗口
- 紧急变更需提前 4 小时通知 NOC 并填写变更申请单（change-request.template.md）
- 维护期间停用自动告警静默（保留 P0 级别告警）

## 2. 维护前检查

### 2.1 备份配置

```bash
# Cisco IOS / IOS-XE
copy running-config tftp://<tftp-server>/backup/<hostname>-$(date +%Y%m%d).cfg

# H3C / Comware
save force
tftp <tftp-server> put startup.cfg backup/<hostname>-$(date +%Y%m%d).cfg
```

必须验证备份文件非空（`ls -lh` 检查文件大小 > 1 KB）。

### 2.2 记录基线指标

| 指标 | 采集命令 | 基线参考 |
|---|---|---|
| CPU 利用率 | `show processes cpu sorted` | < 40% |
| 内存利用率 | `show processes memory sorted` | < 70% |
| 接口错误计数 | `show interface counters errors` | 无持续递增 |
| BGP 邻居状态 | `show bgp summary` | 全 Established |
| STP 拓扑 | `show spanning-tree summary` | 无 TCN 风暴 |

### 2.3 通知上下游

- 通知 NOC 值班：邮件主题 `[维护通知] <设备名> <日期> <时间窗口>`
- 通知受影响业务负责人（如核心交换维护影响数据中心流量）

## 3. 常规维护操作

### 3.1 固件/OS 升级

1. 下载目标固件到本地 TFTP 服务器并校验 MD5
2. 上传到设备 flash：`copy tftp://<server>/<image> flash:`
3. 修改 boot 变量：`boot system flash:<image>`
4. 重启设备（计划内停机）
5. 重启后验证：版本号、接口状态、路由协议状态

**回滚方法**：若升级后出现异常，恢复原 boot 变量并重启。

### 3.2 日志清理

- 设备日志缓冲区满时可能丢弃新日志：每月清理一次
  ```
  clear logging
  ```
- 确认 syslog 服务器收到最近日志（不依赖设备本地缓冲）

### 3.3 端口安全审查

检查未使用端口是否已 shutdown：
```
interface range Gi0/1-48
 shutdown
```
仅对已确认闲置 ≥ 30 天的端口执行。

## 4. 专项检查：交换机 STP

- 确认 Root Bridge 是否为预期设备（变更可能导致拓扑漂移）
- 检查 BPDUGuard 是否在所有 Access 端口启用
- 若存在 TCN（拓扑变更通知），排查触发源（端口频繁上下线）

## 5. 专项检查：路由器 BGP

| 检查点 | 命令 | 处理方式 |
|---|---|---|
| 邻居状态 | `show bgp neighbors` | Idle/Active 状态需立即排查 |
| 路由前缀数 | `show bgp summary` | 与基线对比；骤降说明路由撤回 |
| MED / Local-Pref | `show bgp rib-failure` | 有 RIB 失败时排查策略冲突 |

## 6. 维护后验证

### 6.1 功能验证清单

- [ ] 所有核心接口 UP
- [ ] BGP/OSPF 邻居全部恢复
- [ ] 关键业务 ping 通（覆盖 DMZ、数据中心、办公区）
- [ ] STP 拓扑稳定（无 TCN）
- [ ] 告警系统恢复监控（取消静默）

### 6.2 写维护报告

填写 `maintenance-report.template.md`，包含：
- 操作摘要、执行人、时间戳
- 遇到的问题及处理结果
- 下次维护建议项

## 7. 常见问题 / FAQ

**Q: 备份命令超时怎么办？**
A: 检查 TFTP 服务器防火墙规则（UDP 69）；若 TFTP 不可用，改用 SCP：`copy running-config scp://<user>@<server>/backup/`。

**Q: 升级后 BGP 邻居一直 Idle？**
A: 检查 ACL 是否允许 TCP 179；检查 TTL（eBGP 默认 TTL=1，`ebgp-multihop` 场景需手动调整）。

**Q: STP Root Bridge 漂移后如何恢复？**
A: 在目标 Root Bridge 上执行 `spanning-tree vlan <id> root primary`，强制当选 Root；同步更新 priority 配置文档。
