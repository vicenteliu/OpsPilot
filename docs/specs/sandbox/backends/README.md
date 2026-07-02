# Sandbox Backends — 隔离后端选型 / Backend Selection Guide

> 本文档**不**包含运行实现，仅给出后端能力对比、选型建议与上线注意事项。
> Spec only — capability comparison, selection guidance, and rollout notes.

## TL;DR
- **默认起步**：Docker（L1）
- **加固生产试点**：Docker hardened（L2，加 seccomp + cap-drop + RO rootfs）
- **多租户/外部输入**：gVisor
- **强隔离/微 VM**：Firecracker 或 Kata
- **生产灰度跨网段**：Remote VM

## 能力对比 / Capability matrix

| 维度 / Dimension | Docker (L1) | Docker hardened (L2) | gVisor | Firecracker / Kata | Remote VM |
|---|---|---|---|---|---|
| 隔离强度 | 中 | 中高 | 高（用户态内核） | 很高（microVM） | 取决环境 |
| 启动开销 | 亚秒 | 亚秒 | 中 | ~125 ms | 数秒～分钟 |
| 复杂度 | 低 | 中 | 中 | 中高 | 高 |
| Linux 主机要求 | Docker engine | + seccomp/AppArmor | + runsc | + KVM | 远端 |
| macOS 主机体验 | 良好（Docker Desktop） | 同 L1 | 需 Linux VM | 不可（无 KVM） | 良好 |
| 适合场景 | 开发机 / 自托管试点 | 内网生产小流量 | 多租户 / 处理可疑输入 | 强合规 / 多租户高密度 | 生产灰度 |
| 已知短板 | namespace 共享内核 | 同 L1 性能 | 部分 syscall 不兼容 | 部署链路较长 | 网络延迟、成本 |

## 1. Docker (L1) — 默认 / Default

适用：开发、试点、自托管、内网、个人。

要点：
- 镜像建议：`debian:stable-slim` 或 `ubuntu:24.04` + 仅装必要工具
- 关键参数（建议默认）：
  ```
  --rm
  --read-only
  --tmpfs /tmp:rw,nosuid,nodev,size=64m
  --cap-drop=ALL
  --network=none
  --pids-limit=128
  --memory=512m
  --cpus=1
  --security-opt=no-new-privileges
  -u 65534:65534          # nobody:nogroup
  ```
- 不要挂载 `~/.ssh`、`~/.aws`、`~/.kube`、`/var/run/docker.sock`

风险：
- 共享主机内核；内核级 0day 仍可逃逸
- 默认 root 用户；务必 `-u` 切换非特权 UID

## 2. Docker hardened (L2) — 加固模式

在 L1 之上增加：
- `--security-opt seccomp=policies/seccomp.template.json`
- `--security-opt apparmor=opspilot-default`（需主机配置 AppArmor profile）
- 镜像层面：去掉 `setuid`/`setgid` 二进制；最小依赖
- 内核 capabilities：仅在必要时添加（默认 `--cap-drop=ALL`）

适用：内网试点扩到部分生产；处理半可信输入。

## 3. gVisor

> 文档：https://gvisor.dev/docs/

定位：用户态内核（runsc），拦截 syscall，把"容器隔离"补到接近 VM。

适用：
- 多租户共享主机
- 处理外部/可疑输入（如客户上传日志）
- 不希望把信任完全押在 Linux 内核上

要点：
- Docker 集成：`--runtime=runsc`
- 性能：CPU/IO 有损（10–30% 量级，依工作负载而定）
- 兼容性：少量 syscall 不支持（如某些 `io_uring` 路径）；先在 staging 跑 fixture 检测

部署清单（高层）：
1. 主机安装 `runsc`
2. `/etc/docker/daemon.json` 注册 runtime
3. 测试：`docker run --runtime=runsc -it debian:stable-slim uname -a`

> **已实现（L3）**：OpsPilot 的 gVisor 后端见 `src/opspilot/sandbox/docker_l3.py`
> （选型决策见 [ADR-0009](../../../adr/0009-sandbox-l3-gvisor-over-firecracker.md)）。
> 用法：`opspilot sandbox run --level l3 <action.yaml>`。`runsc` 未注册时
> **fail-closed**（不降级到 L2）。

## 4. Firecracker / Kata Containers

> 文档：https://firecracker-microvm.github.io/  https://katacontainers.io/

定位：microVM，~125 ms 启动，强硬件隔离（依赖 KVM）。

适用：
- 强合规要求（金融、政府）
- 多租户高密度
- 已有 Kubernetes + Kata 链路

要点：
- 必须：Linux 主机 + KVM（`/dev/kvm`）
- macOS / 嵌套虚拟化（云上小机型）通常不可用
- 部署链路：Firecracker → containerd shim → Kubernetes（CRI）；自建较重，建议先评估 Kata
- 资源开销：每个 microVM 约 5 MiB 内存底座

## 5. Remote VM — 远端隔离 VM

定位：把 sandbox 跑在独立 VM/账号，最大化爆炸半径隔离。

适用：
- 生产灰度（跨网段、跨账号）
- 需要触达内网/特定网络位置
- 多团队共用 OpsPilot 但隔离审计

要点：
- 控制面（OpsPilot）↔ 数据面（远端 VM）走 mTLS 通道
- 凭证：远端 VM 不存 OpsPilot 主账号凭证；按动作下发短期凭证
- 成本：VM 常驻 vs 按需启停 —— 按需启停启动延迟高，常驻成本高，需权衡

## 选型决策树 / Decision tree

```
是否仅本机/小团队试点？──▶ 是 ──▶ Docker (L1)
        │
        否
        ▼
是否处理外部/可疑输入？──▶ 是 ──▶ gVisor 或 Firecracker
        │
        否
        ▼
是否生产环境跨网段？──▶ 是 ──▶ Remote VM (+ 内层 Docker hardened)
        │
        否
        ▼
是否合规等级很高？──▶ 是 ──▶ Firecracker / Kata
        │
        否 ──▶ Docker hardened (L2)
```

## 跨后端的统一接口要求 / Backend abstraction

任何后端实现都必须满足以下契约（实现细节不在此目录）：

```
backend.run(action_request, policy) -> action_record
backend.dry_run(action_request, policy) -> dry_run_record
backend.cancel(action_id) -> ok
backend.health() -> {ok|degraded|down, details}
```

- `action_record` / `dry_run_record` 字段必须能映射回 `session/schemas/trace-event.schema.json` 中的 `tool_result`
- 所有后端必须支持 `--network=none` 等价语义

## 备份 / 回滚 注意 / Backup & rollback notes

- 切换默认后端属于**主路径**变更；变更前先在 staging 跑 harness 全量
- 切回滚路径：保留前一后端 6 周可回滚；变更前打镜像 tag 与 docker-compose 版本
- gVisor / Firecracker 升级：先 dry-run 跑 fixture；不兼容 syscall 会显式报错
