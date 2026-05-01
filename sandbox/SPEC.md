# Sandbox — 详细规范 / Detailed Spec

## 1. Action 类型契约 / Action type contract

| `type` | 用途 | 默认网络 | 默认文件 | 备注 |
|---|---|---|---|---|
| `shell` | 任意 shell 命令 | deny-all | overlay tmpfs | 最常用；务必 dry-run |
| `script` | 运行脚本（python/bash/ansible） | deny-all | overlay tmpfs | 需要指定 `interpreter` 与入口 |
| `http` | HTTP 请求 | 仅白名单 host | 无文件写 | method/headers/body 必须显式 |
| `sql_readonly` | 只读 SQL 查询 | 仅白名单数据源 | 无文件写 | 强制 `READ ONLY` 事务；禁 DDL/DML |
| `workflow_dryrun` | n8n / Argo / Airflow 试运行 | 按工作流策略 | 无落地 | 仅返回执行计划与样例输出 |

每个 action 必须填写 `requested_policy`（即使是空对象），明确声明其需要的能力。

## 2. Action 信封 / Action envelope

权威字段定义见 `templates/action-request.template.yaml`。核心字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | ✓ | `act_<ULID>` |
| `session_id` | ✓ | 关联 Session |
| `proposed_by` | ✓ | `model:<name>:<version>` 或 `user:<id>` |
| `type` | ✓ | 见上表 |
| `payload` | ✓ | 类型相关参数（command/script/http/sql/workflow） |
| `requested_policy` | ✓ | network/fs/resource/secrets 的请求清单 |
| `dry_run` | ✓ | bool，默认 `true` |
| `approval_required` | ✓ | bool；由 `approval-policy` 计算 |
| `expected_effects` | ✗ | 模型自述将产生的副作用（用于审计） |
| `rollback_hint` | ✗ | 模型自述如何回滚（见 §6） |

## 3. Action 生命周期 / Action lifecycle

```
proposed ──▶ validated ──▶ dry_run ──▶ [approval?] ──▶ applied ──▶ recorded
   │             │             │             │            │
   └──▶ rejected └──▶ rejected └──▶ aborted  └──▶ rejected └──▶ failed
```

各状态语义：
- **proposed**：信封已生成，未通过 schema 校验
- **validated**：通过 schema + policy 静态校验
- **dry_run**：在沙箱中执行，但禁止外部副作用（apply 类动作变为 plan）
- **approval**：超过审批门阈值时进入；记录审批人/时间/结论
- **applied**：实际执行（仍在沙箱内，但放行配置允许的副作用）
- **recorded**：所有 stdout/stderr/diff/退出码已写回 Session
- **rejected/aborted/failed**：错误终态；必须写入失败原因到 `tool_result`

## 4. 策略契约 / Policy contract

### 4.1 网络 / Network

```yaml
network:
  mode: deny-all | allowlist | open      # 默认 deny-all
  egress:
    - host: pkg.debian.org              # 完整域名匹配
    - cidr: 10.0.0.0/8                  # 内网网段
  dns:
    resolvers: [1.1.1.1, 8.8.8.8]
    block_dot_local: true
```

模板：`policies/network-allowlist.template.yaml`

### 4.2 文件系统 / Filesystem

```yaml
fs:
  rootfs: read_only
  workdir: /work                         # tmpfs overlay
  mounts:
    - source: <session>/inputs           # 来自 Session 的脱敏输入
      target: /input
      mode: ro
    - source: <session>/artifacts        # 产物输出
      target: /output
      mode: rw
  forbidden:
    - /home/**/.ssh
    - /home/**/.aws
    - /home/**/.kube
    - /var/run/docker.sock
```

### 4.3 资源 / Resource

模板：`policies/resource-quota.template.yaml`，常用键：
- `cpu`：CPU 配额（核数或百分比）
- `memory`：内存上限
- `pids`：最大进程数
- `disk`：tmpfs 上限
- `timeout`：墙钟超时（默认 30 s）

### 4.4 系统调用 / Syscalls

- 默认采用 Docker default seccomp profile
- Hardened 模式使用 `policies/seccomp.template.json`（更严格的 allowlist）
- 高风险 syscall 默认禁用：`mount`, `umount`, `reboot`, `kexec_load`, `init_module`, `delete_module`, `bpf`, `ptrace`（除非显式放行）

### 4.5 密钥 / Secrets

- **不允许** 通过 env/argv 注入敏感凭证
- 必须通过 Secrets Broker 接口；动作运行期间挂载短期凭证到 `/run/secrets/<name>`，结束自动卸载
- Broker 实现选型留待后续；本规范仅约定接口形态：

```
GET  /broker/v1/lease  body: {action_id, name, ttl_seconds}
                       resp: {value, expires_at}
POST /broker/v1/release body: {lease_id}
```

## 5. Dry-run 语义 / Dry-run semantics

- `shell` / `script`：进入容器执行，但写入挂载点变更为 overlay 之上的 overlay；输出 diff 视图
- `http`：仅返回"将发送的请求摘要 + curl 等价命令"，不真正发起
- `sql_readonly`：可执行（本身只读），返回行数与样例
- `workflow_dryrun`：调用工作流引擎的 plan/dry-run 接口

dry-run 产物必须包含：
- 将要执行的命令/请求/SQL（脱敏后）
- 预期文件变更列表
- 预期网络访问目标
- 预期资源使用估算（best-effort）

## 6. 回滚指引 / Rollback hints

模型在 `rollback_hint` 中应给出"逆操作"建议（最佳努力）：
- 文件变更 → 备份目录路径 + 还原命令
- 包安装 → `apt-get remove <pkg>` 或快照回滚
- 配置变更 → 备份文件 sha256 与还原命令
- 不可逆动作（删除）→ 显式标注 `irreversible: true`，必触发审批门

## 7. 审批门 / Approval gate

触发条件（任一即触发）：
1. `payload` 含高危关键词：`rm -rf`, `DROP`, `TRUNCATE`, `chmod 777`, `:(){ :|:& };:`
2. 目标环境标签为 `prod` / `production`
3. 涉及 IAM / RBAC / 网络策略修改
4. 网络出网超出当前 allowlist
5. `irreversible: true`

模板：`templates/approval-policy.template.yaml`

## 8. 录制 / Recording

每个 action 完成后，必须向 Session 写入：
- 一条 `tool_result` trace 事件（含 exit_code、usage 摘要、artifact_ids）
- 一个或多个 artifact：
  - `stdout`/`stderr`：超过 8 KiB 走 artifact，否则 inline
  - `diff`：dry-run 与 apply 的产物 diff
  - `manifest`：实际应用的 policy 快照（用于事后审计）

## 9. 失败模式 / Failure modes

| 失败类 | 处理 |
|---|---|
| schema 校验失败 | 返回 `rejected`，不进入 dry_run |
| 策略校验失败（请求超出允许） | 返回 `rejected`，建议降级方案 |
| 超时 | 强杀容器；状态置 `failed`；记录 `timeout` 标志 |
| OOM | 状态 `failed`；记录 `oom_killed` |
| 网络违规（试图访问非白名单） | 中断动作；记录违规事件；状态 `aborted` |
| 后端异常（docker daemon 挂掉） | 状态 `failed`；上报到 audit.log |

## 10. 强约束 / Hard requirements

- 任何 action 都必须有 `dry_run` 阶段产物（即使最终 apply）
- 不允许 sandbox 进程逃逸到主机命名空间（PID/NET/USER/MNT 必须隔离）
- `requested_policy` 必须显式列出，缺省视为 deny
- 所有日志按 UTF-8 + RFC3339 时间戳
- 后端实现可替换，但必须满足以上接口与字段
