# Skills — 技能注册、制作与蒸馏 / Skills Registry, Authoring & Distillation

> **状态 / Status**：规范阶段（spec-only）。本目录定义 skill 数据模型、生命周期、工具/MCP 绑定契约、蒸馏 pipeline 与模板；不含运行实现。
> **Stage**：spec only — schemas, templates, contracts. No runtime here.

## TL;DR
Skill = 一段**可重用的"做某类活"的指令包**：含触发条件（description）、操作步骤（markdown body）、依赖工具/MCP（声明式），**可被打包、版本化、共享、蒸馏**。OpsPilot 的 skills 子系统在 Anthropic skills 形态之上加了三件事：

1. **Authoring（制作）**：给写新 skill 的人提供模板 + checklist + description 调优指南
2. **Distillation（蒸馏）**：从 session traces / 文档 / 他人 skill / 跨平台 skill **自动产出 skill 草稿**——这是 OpsPilot 区别于纯 skill 仓库的核心
3. **Tool & MCP integration**：skill 可声明所需 builtin 工具（kb.search 等）与 MCP server，registry 在加载时校验依赖

## 与 Anthropic skills 形态的关系 / Relation to Anthropic skills

兼容：单文件 `SKILL.md` + frontmatter + 同目录 resources/ 的形态保留——可以直接 import / export。

扩展：
- frontmatter 增加 `requires.tools`、`requires.mcps`、`requires.providers`（依赖声明）
- 增加 `safety` 段（classification、telemetry、approval_required）
- 增加 `distillation` 段（声明蒸馏来源，便于追溯）
- 增加 `compat`（跨工具/平台映射）

不破坏 Anthropic skills 的最小形态——多余字段对原生 runner 来说是 unknown frontmatter，可忽略。

## Skill 生命周期 / Lifecycle

```
                ┌─────────┐
                │  draft  │  作者写或蒸馏出
                └────┬────┘
                     │ author/distill
                     ▼
                ┌─────────┐
                │reviewed │  人工/自动 review 通过
                └────┬────┘
                     │ review.pass
                     ▼
                ┌─────────┐
                │ trusted │  纳入受信源；安装时不再走 sandbox 隔离
                └────┬────┘
                     │
            ┌────────┴────────┐
            │                 │
            ▼                 ▼
       ┌─────────┐       ┌──────────┐
       │installed│       │community │  受信但未安装；或来自社区
       └────┬────┘       └─────┬────┘
            │ enable            │
            ▼                   ▼
       ┌─────────┐       (sandbox-only invocation)
       │ enabled │  能被 session 触发并调用
       └────┬────┘
            │ invoke / update / deprecate
            ▼
       ┌──────────┐
       │ archived │
       └──────────┘
```

## 信任分级 / Trust tiers

| Tier | 来源 | 调用约束 |
|---|---|---|
| `self_authored` | 本地作者 | full（按 skill 自身声明的权限）|
| `distilled` | 从内部 traces/docs 蒸馏；通过本地 review | full |
| `imported_trusted` | 从受信源（白名单组织/作者）导入 | full |
| `imported_community` | 社区/未审计来源 | **强制 sandbox 调用**；只读权限；禁出网默认 |
| `imported_unknown` | 不明来源 | 默认拒绝；显式 opt-in 才进入 community 等级 |

详见 `templates/lifecycle-policy.template.yaml`。

## 四类核心能力 / Four core capabilities

### 1. Skill Authoring 制作

帮人写出**可触发率高、依赖清晰、安全合规**的新 skill。

- `templates/SKILL.template.md`：单 skill 模板（frontmatter + body）
- `SPEC.md` §3 *Description tuning*：description 怎么写才能让模型在合适时候召回
- `SPEC.md` §4 *Quality checklist*：发布前必跑的 7 条自检
- `SPEC.md` §5 *Trigger eval*：用 `harness/` 评估 description 触发准确率

### 2. Skill Distillation 蒸馏（项目核心）

从 4 类来源**自动生成 skill 草稿**，避免人工从零写：

| 来源 | 模板 | 适合 |
|---|---|---|
| 自家 session traces | `distillation-from-traces.template.yaml` | 把团队反复做的成功流程固化为 skill |
| 别人的 skill 集合 | `distillation-from-skills.template.yaml` | 学习共有结构与风格，做 meta-template |
| 文档/SOP/playbook | `distillation-from-docs.template.yaml` | 把人写的 markdown SOP 自动转 skill |
| 跨平台 skill | `distillation-from-foreign.template.yaml`（占位） | Anthropic skill ↔ OpenAI GPTs ↔ LangChain agent 翻译 |

每条蒸馏 pipeline 都要：
1. **redact**（脱敏）— 与 session 对齐
2. **mine** 模式 — pattern mining / LLM-distill
3. **draft** 草稿 — 产出 SKILL.md + tool-binding.yaml
4. **review** 审阅 — 人工或 auto-review
5. **register** 入库 — 写入 skill-registry

蒸馏来源必须可追溯：每份草稿在 frontmatter 的 `distillation.source` 字段记录原始数据引用。

### 3. Iteration（迭代）⭐

让 skill 从初版 → 持续改进 → 收敛到稳定，不是手动 bump semver。详细规范见 `ITERATION.md`，要点：

- **Lineage**：每个 skill 的演化是有向图（parent_variant_id / merged_from），可追溯每次变更原因
- **Variants**：同 skill 的多个候选并行，由 harness 跑矩阵后比对 baseline
- **Feedback signals**：把 session 中的 user_action、harness 评分、蒸馏候选模式、模型漂移、trace 失败汇集成结构化信号
- **6 类触发条件**：`regression_detected` / `feedback_signal` / `distillation_candidate` / `model_upgrade` / `scheduled` / `manual`
- **晋升标准**：anchor fixtures 无回归 + 加权分 +0.01 + cost 增长 ≤10% + trigger eval 仍达标 + 静态检查全过
- **回滚窗口**：默认保留 3 个稳定版本；30 天内可一键回滚

文件：
- `ITERATION.md` 详细规范
- `schemas/iteration.schema.json` / `skill-variant.schema.json` / `feedback-signal.schema.json`
- `templates/iteration-recipe.template.yaml` / `iteration-policy.template.yaml` / `feedback-collector.template.yaml`

### 4. Tool & MCP Integration 工具与 MCP 集成

Skill 可调用三类操作：

| 类 | 例 | 注册方式 |
|---|---|---|
| **Builtin tools** | `kb.search`, `memory.add`, `artifact.write` | 由 OpsPilot core 提供；无需注册 |
| **MCP tools** | `mcp__notion__*`, `mcp__slack__*` | 在 `mcp-config.template.yaml` 注册 server |
| **Sandbox actions** | shell / script / sql_readonly | 走 `sandbox/templates/action-request.template.yaml` |

`tool-binding.template.yaml` 把 skill 的 `requires.tools[]` 与具体的 builtin / MCP / sandbox 实现绑定，并附 safety_class（read / write / execute / sensitive）与 approval_required。

## 范围 / Scope

In scope：
- skill 数据模型（frontmatter + body + resources）
- registry / lifecycle / trust tiers
- 蒸馏 pipeline 的契约（4 类来源）
- 工具与 MCP 绑定声明
- 与 session/sandbox/harness/memory 的接口

Out of scope（暂不在此目录）：
- 蒸馏 runner 实现（Python pipeline）
- skill marketplace（社区分发）
- skill 自动安装的 CLI

## 目录结构 / Directory layout

```
skills/
├── README.md                                  # 本文件
├── SPEC.md                                    # 详细规范
├── catalogs.md                                # 已知 skill 来源 + 跨平台映射
├── schemas/
│   ├── skill.schema.json                      # SKILL.md frontmatter
│   ├── skill-registry.schema.json             # registry 条目
│   ├── tool-binding.schema.json               # 工具/MCP 调用契约
│   ├── mcp-config.schema.json                 # MCP server 配置
│   └── distillation-recipe.schema.json        # 蒸馏配方
└── templates/
    ├── SKILL.template.md
    ├── skill-registry.template.yaml
    ├── tool-binding.template.yaml
    ├── mcp-config.template.yaml
    ├── distillation-from-traces.template.yaml
    ├── distillation-from-skills.template.yaml
    ├── distillation-from-docs.template.yaml
    └── lifecycle-policy.template.yaml
```

## 与其他目录的契约 / Contracts

| 上游 | 给 skills 的输入 |
|---|---|
| `session/` | 历史 trace.jsonl 作为蒸馏源（必须脱敏后） |
| `memory/` | KB 文档作为 from_docs 蒸馏源 |
| `harness/` | description 触发评估 + skill 回归测试 |
| `providers/` | `requires.providers[]` 声明所需 capability（如 vision/tools） |

| 下游 | skills 提供的产物 |
|---|---|
| `session/` | 被激活后注入到 prompt（系统消息或工具描述）|
| `sandbox/` | skill 中声明的 sandbox actions 走 sandbox 执行 |
| `case-studies/` | 蒸馏报告归档 |

## 安全红线 / Hard nos

- ❌ 不允许把未脱敏 trace 直接喂给 distillation pipeline
- ❌ 不允许 community/unknown 等级 skill 调用写类工具（kb.write、memory.add、sandbox.apply）
- ❌ 不允许 skill 在运行时修改 mcp-config（防 prompt-injection 改路由）
- ❌ 不允许 skill description 中含 prompt injection 语句（"ignore previous instructions" 等）—— 加载时静态扫描
- ❌ MCP API key 一律走 env，不入仓库

## 开放问题 / Open questions

- [ ] Skill 版本升级时，是否要求过 harness 触发回归（旧 fixture 仍能命中新 skill）？
- [ ] 蒸馏出的 skill 是否默认进 `distilled` tier，还是要先入 `draft` 等人工 review？
- [ ] MCP server 的健康检查频率（与 providers 复用 `health_probe` 还是单独定义）？
- [ ] 跨平台 skill 翻译的目标平台优先级（Anthropic skills / Claude Code skills / OpenAI GPTs / LangChain）？
