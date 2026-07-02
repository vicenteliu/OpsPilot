# Session — 会话与轨迹规范 / Session & Trace Spec

> **状态 / Status**：规范阶段（spec-only）。本目录只定义数据模型、模板与策略；不含运行实现。
> **Stage**：spec only — schemas, templates, policies. No runtime implementation here.

## TL;DR
Session（会话）= 一次 AI 任务的"上下文 + 轨迹 + 产物 + 审计"打包单元。它是 OpsPilot 合规落地（脱敏 / 审计 / 保留 / 复现）的载体，也是 Sandbox 与 Harness 的输入/输出锚点。

## 在 OpsPilot 闭环中的位置 / Where it sits

```
playbooks/  ──▶  Session(create)  ──▶  prompt/LLM
                       │
                       ▼
                 proposed_action  ──▶  sandbox/  ──▶  artifact
                       │                                │
                       ▼                                ▼
                 Session.trace  ◀───────────  recording
                       │
                       ▼
                 harness/(eval)  ──▶  case-studies/
```

## 范围 / Scope

In scope：
- 会话生命周期与状态机（lifecycle / state machine）
- 数据模型（meta / trace / artifact / audit）
- 脱敏接入点（redaction integration point）
- 保留策略（retention policy）
- 复现/对比语义（replay & diff semantics）

Out of scope（暂不在此目录）：
- 具体存储实现（Postgres / SQLite / 文件系统）
- UI / Web 控制台
- 计费与配额（quota & billing）

## 目录结构 / Directory layout

```
session/
├── README.md                         # 本文件
├── SPEC.md                           # 详细规范
├── schemas/
│   ├── session.schema.json           # 顶层 Session 元数据
│   └── trace-event.schema.json       # 轨迹事件
└── templates/
    ├── session-meta.template.yaml    # 可复制的会话元数据示例
    ├── redaction-rules.template.yaml # 默认脱敏规则
    └── retention-policy.template.yaml# 默认保留策略
```

## 文件级存储约定 / On-disk layout (推荐)

```
sessions/<session_id>/
├── meta.yaml          # 符合 schemas/session.schema.json
├── inputs/            # 已脱敏的原始输入
├── trace.jsonl        # 每行一个 trace event，符合 trace-event.schema.json
├── artifacts/         # 产物（脚本、SOP、diff、报告）
└── audit.log          # 仅追加，审计事件
```

## ID 约定 / ID conventions
- `session_id` ：`sess_<ULID>`（时间有序，分布式友好）
- `trace_id` ：`trc_<ULID>`
- `artifact_id` ：`art_<sha256[:16]>`（内容寻址，便于去重与防篡改）

## Quickstart（给读规范的人）

1. 读 `SPEC.md` —— 字段语义、状态机、强约束
2. 用 `templates/session-meta.template.yaml` 起一个新会话元数据
3. 在 `governance/redaction.md` 与本目录 `redaction-rules.template.yaml` 之间对齐脱敏规则
4. 决定保留等级 → 套 `retention-policy.template.yaml`

## 与其他目录的契约 / Contracts

| 上游 / Upstream | 给 Session 的输入 |
|---|---|
| `playbooks/` | playbook_id（必填）、版本号 |
| `prompts/` | 引用的 prompt id 与版本 |
| `governance/` | 脱敏规则、保留策略、RBAC |

| 下游 / Downstream | Session 提供的产物 |
|---|---|
| `sandbox/` | proposed action（trace event 中的 `tool_call`） |
| `harness/` | trace.jsonl 作为评估输入 |
| `case-studies/` | 已归档 Session 的脱敏摘要 |

## 开放问题 / Open questions

- [ ] 多人协作时，`owner` 是单值还是多值（owner + collaborators）？
- [ ] `parent_id` 用于 replay 时，是否需要"分支语义"（fork tree）？
- [ ] artifact 是否需要签名（cosign / minisign）以满足审计？
