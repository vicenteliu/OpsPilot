# Sandbox — 隔离执行规范 / Sandbox Execution Spec

> **状态 / Status**：规范阶段（spec-only）。本目录只定义动作契约、策略与后端选型文档；不含运行实现。
> **Stage**：spec only — action contracts, policies, backend selection docs. No runtime here.

## TL;DR
Sandbox（沙箱）= AI 提出的动作（命令 / 脚本 / 工作流 / HTTP / 只读 SQL）的"先跑给你看，再决定要不要落地"的隔离执行层。**默认 dry-run**，**默认 deny-all 网络**，**默认无密钥**。

## 设计原则 / Principles

1. **Default deny / 默认拒绝**：网络、文件系统、密钥、系统调用——一律默认拒绝，按需放行。
2. **Dry-run first / 先预演**：所有动作默认进入 dry-run，输出 diff/将执行命令；显式 `--apply` 才落地。
3. **Recordable / 可记录**：stdin、argv、env、stdout、stderr、文件变更、退出码——全部回写到 Session。
4. **Reversible by design / 可回滚**：apply 前必须有 dry-run 产物；高风险动作要求审批门 + 回滚指引。
5. **Pluggable isolation / 可插拔后端**：从 Docker（默认）→ gVisor/Firecracker（强隔离）→ 远端 VM（生产灰度）。

## 后端选型矩阵 / Backend selection matrix

| 后端 / Backend | 隔离强度 | 启动开销 | 复杂度 | 推荐场景 |
|---|---|---|---|---|
| Docker (L1) | 中 | 低（亚秒） | 低 | **默认**：开发机、自托管、内网试点 |
| Docker hardened (L2) | 中高 | 低 | 中 | seccomp/AppArmor + cap-drop + RO rootfs |
| gVisor | 高 | 中 | 中 | 处理可疑/外部输入；多租户共享主机 |
| Firecracker / Kata | 很高 | 中（百毫秒级 microVM） | 中高 | 强隔离需求；需要 KVM 主机 |
| Remote VM | 取决环境 | 高 | 高 | 生产灰度；跨区域执行 |

详见 `backends/README.md`。

## 范围 / Scope

In scope：
- Action types 契约（shell / script / http / sql_readonly / workflow_dryrun）
- Policy contract（network / fs / resource / secrets）
- Dry-run vs apply 语义
- Recording 字段与回写约定
- Approval gate 触发条件

Out of scope：
- 具体后端实现（dockerfile、镜像构建脚本）
- 网络代理实现
- 密钥管理实现（仅约定接口）

## 目录结构 / Directory layout

```
sandbox/
├── README.md                                # 本文件
├── SPEC.md                                  # 动作契约 + 策略契约 + 生命周期
├── backends/
│   └── README.md                            # 5 类后端对比与选型说明
├── policies/
│   ├── network-allowlist.template.yaml      # 出网白名单
│   ├── seccomp.template.json                # seccomp 基线
│   └── resource-quota.template.yaml         # CPU/内存/磁盘/超时
└── templates/
    ├── action-request.template.yaml         # 动作请求信封
    └── approval-policy.template.yaml        # 审批门规则
```

## Action 生命周期（高层） / Action lifecycle

```
proposed → validated → dry_run → [approval?] → applied → recorded
                                       │
                                       └──▶ rejected / aborted
```

详细状态语义见 `SPEC.md`。

## 与其他目录的契约 / Contracts

| 上游 | 给 Sandbox 的输入 |
|---|---|
| `session/` | trace event `tool_call` → 转为 action request |
| `playbooks/` | 动作模板与策略推荐 |

| 下游 | Sandbox 提供的产物 |
|---|---|
| `session/` | recording → trace event `tool_result` + artifact |
| `harness/` | sandbox 执行结果作为 evaluator 输入 |

## 安全红线 / Hard nos

- ❌ 不直接挂载用户主机的 `~/.ssh`、`~/.aws`、`~/.kube` 等凭证目录
- ❌ 不把密钥/Token 通过环境变量或参数注入；必须经 Secrets Broker 接口
- ❌ 不允许 sandbox 直接调用生产 API，除非显式 `apply` + 审批通过
- ❌ 不允许自动执行 `rm -rf` / `DROP` / `DELETE` / IAM 变更等高危动作

## 开放问题 / Open questions

- [ ] Secrets Broker 接口选型：本地 file-based vs Vault agent vs SPIFFE/SPIRE？
- [ ] 录制产物加密方案：默认明文 + 文件系统级加密（LUKS/eCryptfs）？
- [ ] gVisor 在 macOS 主机的体验（需 Linux VM 中转）是否值得纳入默认推荐？
