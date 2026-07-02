# Session — 详细规范 / Detailed Spec

## 1. 生命周期与状态机 / Lifecycle & state machine

```
            ┌──────────┐
            │  draft   │  创建占位，尚未 redact
            └────┬─────┘
                 │ redact() 完成
                 ▼
            ┌──────────┐
            │  active  │  正在进行中（多轮对话/工具调用）
            └────┬─────┘
       ┌─────────┼──────────┐
       │ pause   │ resume   │ terminate
       ▼         │          ▼
  ┌─────────┐    │     ┌─────────┐
  │ paused  │────┘     │ aborted │
  └─────────┘          └─────────┘
                 │ user.archive()
                 ▼
            ┌──────────┐
            │ archived │  只读、可被 harness 引用
            └────┬─────┘
                 │ retention 到期
                 ▼
            ┌──────────┐
            │ purged   │  仅保留审计摘要（meta-only）
            └──────────┘
```

合法转移 / Allowed transitions：
- `draft → active`：脱敏完成且 meta 字段齐全
- `active ↔ paused`
- `* → aborted`：用户主动中止；保留所有已产生数据
- `active|paused → archived`：用户归档；产物只读
- `archived → purged`：保留期到，自动清理 inputs/artifacts，仅留 meta + audit 摘要

## 2. 字段定义（顶层 Session）/ Top-level fields

> 权威定义见 `schemas/session.schema.json`。本节为人类可读说明。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string `^sess_[0-9A-HJKMNP-TV-Z]{26}$` | ✓ | ULID |
| `schema_version` | string semver | ✓ | meta schema 版本，例 `"1.0.0"` |
| `owner` | string | ✓ | 主负责人（email 或 user id） |
| `collaborators` | string[] | ✗ | 协作者；权限策略由 RBAC 决定 |
| `playbook` | { id, version } | ✓ | 引用的 Playbook |
| `prompts` | { id, version }[] | ✗ | 用到的 prompt 与版本 |
| `model` | { provider_id, kind, name, version, params, ... } | ✓ | 模型与采样参数；详见 `providers/SPEC.md` §1.2，等价 `model_ref = <provider_id>/<name>@<version>`。`version` 禁用 `latest`/`auto`/`stable`。 |
| `status` | enum `draft|active|paused|aborted|archived|purged` | ✓ | 见状态机 |
| `created_at` | RFC3339 | ✓ | UTC |
| `updated_at` | RFC3339 | ✓ | UTC |
| `parent_id` | session_id | ✗ | replay/分支时指向父 Session |
| `retention_class` | enum `low|medium|high|critical` | ✓ | 见 `retention-policy.template.yaml` |
| `sensitivity` | enum `public|internal|confidential|restricted` | ✓ | 数据分级 |
| `tags` | string[] | ✗ | 自由标签 |
| `labels` | object | ✗ | k/v；用于检索与统计 |

## 3. Trace 事件 / Trace events

`trace.jsonl` 每行一条事件，按 `seq` 单调递增。

事件类型（discriminator = `type`）：

| type | 含义 | 关键字段 |
|---|---|---|
| `prompt` | 发往模型的 prompt | `role`, `content`, `prompt_ref` |
| `response` | 模型回复 | `content`, `finish_reason`, `usage` |
| `tool_call` | 模型请求调用工具 | `tool`, `args` |
| `tool_result` | 工具执行结果 | `tool`, `exit_code`, `stdout_ref`, `artifact_ids` |
| `redaction` | 脱敏触发记录 | `pattern`, `count`, `placeholder` |
| `user_action` | 用户介入（采纳/拒绝/编辑/审批） | `action`, `payload_diff` |
| `system` | 状态切换、错误 | `event`, `details` |

权威 schema：`schemas/trace-event.schema.json`。

## 4. Artifacts 产物

- 路径：`artifacts/<artifact_id>.<ext>`
- ID：`art_<sha256前16位>`（内容寻址，去重 + 防篡改）
- 必须配 sidecar：`artifacts/<artifact_id>.meta.yaml`（见模板）
- artifact 不直接写入大文件正文到 trace；trace 只引用 `artifact_id`

## 5. 脱敏接入点 / Redaction integration

- **入口**：所有写入 `inputs/` 与 `trace.jsonl` 的内容必须经过 redactor
- **占位符格式**：`[REDACTED:<type>:<8位hash>]`，例 `[REDACTED:email:a1b2c3d4]`
- **可逆映射**：原文 ↔ 占位符 的映射只存于 `audit.log`（受限读取），不入 trace
- 规则模板：`templates/redaction-rules.template.yaml`
- 与 `governance/redaction.md` 保持一致；以 governance 为准

## 6. 保留策略 / Retention

- `retention_class` 决定到期天数；详见 `templates/retention-policy.template.yaml`
- 到期动作：清空 `inputs/` + `artifacts/`，保留 `meta.yaml` 和 `audit.log` 摘要
- `audit.log` 保留期单独定义（默认更长，例如 365 天）
- 用户可主动 `archive` 或 `delete`；`delete` 不可逆，必须二次确认

## 7. 复现与 Diff / Replay & diff

- 用同一 `inputs/` + 不同 `model` 或 `prompts` 重跑 → 新建 Session 并设置 `parent_id`
- Diff 维度：响应文本、tool_call 序列、artifact 内容、token/成本/延迟、harness 评分
- replay 必须 deterministic 友好：记录温度、seed、top_p 等采样参数

## 8. RBAC 与审计 / RBAC & audit

最小角色（建议）：
- `owner`：完全控制
- `collaborator`：读写 trace + artifacts，不可改 meta/retention
- `viewer`：只读
- `auditor`：只读 audit.log + meta（含被 redact 的原文映射）

`audit.log` 必须仅追加（append-only），格式：
```
<rfc3339>\t<actor>\t<action>\t<target>\t<details_json>
```

## 9. 强约束 / Hard requirements

- 所有时间戳一律 **UTC + RFC3339**
- 文件编码一律 **UTF-8**（不带 BOM）
- `trace.jsonl` 必须保证逐行有效 JSON，单行 ≤ 1 MiB；超出走 artifact 引用
- `purged` 状态后，除 `meta.yaml` 与 `audit.log` 外，目录其余内容必须清空
- 任何时候，Session 不得包含未脱敏的 PII / 密钥（**这是合规底线**）

## 10. 扩展点 / Extension points

- `meta.yaml.extensions.<vendor>` —— 厂商/工具自定义元数据，不得与已定义字段冲突
- `trace-event.extensions.<vendor>` —— 自定义事件子类型，必须使用命名空间前缀
- 自定义 evaluator（harness）可读 trace 但不得回写 Session

## 11. Memory 集成 / Memory integration

Session 与 `memory/` 目录的契约：
- **短期 memory** 复用 `trace.jsonl`，上下文窗口管理与摘要策略见 `memory/templates/short-term-config.template.yaml`
- **检索注入**：trace 中以 `tool_call: kb.search` / `tool_call: memory.search` 触发；返回结果通过 `tool_result` 写回，并在后续 prompt 中以 footnote 形式引用
- **归档收割**：Session 状态从 `archived` 转入 finalize 时，按 `harvest_to_mid_term` 规则把候选事实写入中期 memory（默认走 candidate_review，需用户确认）
- **检索请求/响应** schema：见 `memory/schemas/retrieval-query.schema.json`
- **强约束**：进入 memory 的内容必须已脱敏（与 §5 的 redaction 接入点一致）
