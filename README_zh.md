# OpsPilot (OpenOps AI)
**Practical AI Playbooks for IT Pros & Managers**  
**面向 IT 从业者与中低管理层的 AI 实战手册（开源优先 / 可复现 / 可落地）**

> OpsPilot 不是“AI 新闻搬运”。我们用 **开源工具 + 可复现工作流 + 治理与合规底线**，把 AI 变成你日常 IT 工作的生产力，并帮你看清 IT 任务如何被 AI 重构。

---

## What is OpsPilot? | OpsPilot 是什么？

### English
OpsPilot is a practical AI project for IT practitioners and mid-level IT managers.  
We publish reproducible demos, prompts, playbooks, and governance templates that help you:
- ship faster (tickets/docs/RCA/runbooks/scripts),
- integrate open-source AI stacks (local/on-prem friendly),
- adopt AI safely (redaction, access control, audit, retention),
- understand what work is being automated and what skills rise in value.

### 中文
OpsPilot 是一个面向 **IT 从业者**与**IT 中低管理层**的 AI 实战知识项目。  
我们提供可复现的 demo、提示词、SOP/Playbook 与治理模板，帮助你：
- 提速（工单/文档/RCA/Runbook/脚本/报告），
- 整合开源 AI 技术栈（支持本地/自托管/内网），
- 安全落地（脱敏、权限、审计、保留策略），
- 看清未来：哪些任务会被自动化、哪些能力会升值。

---

## Who is this for? | 适合谁？

### English
- **IT practitioners (ICs):** Service Desk, Desktop Support, Sysadmins, NOC, junior SRE/Ops, IT Ops, SecOps-adjacent roles
- **Managers:** Team Leads, IT Managers, Service Delivery/Ops Managers
- **Career shifters:** Former IT moving into product/project/ops leadership who need a clear AI delivery framework

### 中文
- **IT 实操人群（IC）：** Service Desk/桌面支持/系统管理员/NOC/初中级 SRE/运维/安全运营相关岗位  
- **管理者：** Team Lead、IT Manager、Service Delivery / Ops Manager  
- **转型者：** 曾从事 IT，希望把 AI 能力变成“可交付方法论”的人

---

## Core principles | 核心原则

- **Scenario-first / 场景优先**：从真实 IT 工作流出发，而不是从概念出发  
- **Open-source-first / 开源优先**：优先给可自托管方案，再给商业替代  
- **Reproducible / 可复现**：每个主题都尽量提供可运行资产（prompts / compose / workflows）  
- **Safety by default / 默认合规**：明确数据边界、脱敏策略、权限与审计建议  
- **Integration matters / 重在整合**：单点工具≠生产力，串起来才是

---

## Content pillars | 内容支柱（栏目）

### 1) Ticket & Ops Accelerator | 工单与运维加速器
- Ticket summarization, triage, draft replies | 工单摘要、分类、回复草稿
- Logs/errors → next-action checklist | 日志/报错 → 下一步动作清单
- SOP/runbook generation | SOP/Runbook 生成与标准化

### 2) Open-source Unboxing | 开源项目拆箱
- Clear “what it solves / where it fails / who it’s for” | 讲清能做什么/不能做什么/适合谁
- Quickstart + pitfalls + alternatives | 快速上手 + 坑位 + 替代方案

### 3) Mini Systems (Integration) | 整合小系统
- RAG over KB, workflow automation, local/on-prem stacks  
- KB 检索引用（RAG）、工作流编排、可自托管技术栈

### 4) Rollout & Governance | 落地与治理（管理向）
- Redaction, data classification, access control, audit, retention  
- 脱敏、数据分级、权限控制、审计与保留策略
- Pilot strategy + KPI/ROI templates | 试点策略 + KPI/ROI 模板

### 5) IT Task Map | IT 任务地图（未来清晰度）
- What gets automated vs what becomes premium work  
- 哪些任务会自动化、哪些能力更值钱（集成/流程/治理/架构/判断）

---

## Quick start | 快速开始

### English
Pick one of the paths:
1) **Prompts-only (fastest):** start with `/prompts/`  
2) **Run a demo (recommended):** go to `/demos/` and use Docker Compose  
3) **Team rollout:** read `/governance/` and `/playbooks/`

### 中文
选择一条路径开始：
1) **只用提示词（最快）：** 从 `/prompts/` 开始  
2) **跑 Demo（推荐）：** 进入 `/demos/`，按 Docker Compose 启动  
3) **团队落地：** 先看 `/governance/` 与 `/playbooks/`

> ⚠️ **Security note / 安全提示**：请勿把敏感信息（PII、密钥、token、内部机密）直接粘贴到任何模型或工具里。建议先看 `/governance/redaction.md`。

---

## 终端工作台（TUI）

```bash
opspilot tui                                     # 启动 8 模块交互式工作台
opspilot tui run --input ticket.json             # 直接打开运行弹窗
```

按数字键 `1`–`8` 切换模块：

| 键 | 模块 | 说明 |
|----|------|------|
| `1` | Dashboard | 会话 / KB / Wiki 统计 |
| `2` | Sessions | 所有运行记录；`W` → 对选中会话生成 Wiki 页 |
| `3` | KB Browser | 已入库文档与 chunk 数量 |
| `4` | Wiki Tree | 所有 Wiki 页；`P` → 将选中的 draft/reviewed 页升为 live |
| `5` | Harness | 评估运行历史 |
| `6` | Lint Issues | Wiki 静态检查（孤儿页、断链、脱敏警告） |
| `7` | Providers | Ollama / Anthropic / OpenAI 连通状态 |
| `8` | Config | 当前配置项 |
| `R` | — | 打开运行弹窗（任意屏幕有效） |

---

## Wiki 知识沉淀层

Wiki 层把 KB 文档和会话响应转化为可浏览、可校验、有生命周期的知识库。

```bash
# 将已入库 KB 文档生成 wiki 摘要页
opspilot wiki ingest <doc_id>

# 自动扫描合格的归档会话，生成 synthesis 页（需要 Ollama）
opspilot wiki query-to-page
opspilot wiki query-to-page --session sess_<id>   # 单条会话

# 推进页面生命周期
opspilot wiki promote <slug>            # draft → live（默认）
opspilot wiki promote <slug> --to reviewed

# 静态检查
opspilot wiki lint
```

**Wiki 页面生命周期**：`draft` → `reviewed` → `live` → `stale` → `archived`

自动化工具（ingest / query-to-page）始终写入 `draft`；人工审核后通过 CLI 或 TUI `P` 键升为 `live`。

**触发 query-to-page 的条件（满足其一即可）：**
- 会话中 `kb_search` 工具调用次数 ≥ 2
- 会话 trace 中存在 `user_action.accept` 事件

**四类 lint 检查：**

| 类型 | 说明 |
|------|------|
| `orphan` | 页面无入链且非归档状态 |
| `broken_link` | `[[slug]]` 引用的目标页不存在 |
| `redaction_warning` | 正文中出现 `[REDACTED:` 残留占位符 |
| `schema_invalid` | 前置 YAML 解析失败、slug 冲突或 summary 类页缺少必要章节 |

---

## Repository structure | 仓库结构

```text
.
├── prompts/                # Copy/paste prompts (redaction-first) | 可复制提示词（先脱敏）
├── playbooks/              # SOPs & workflows | SOP/工作流打法
├── demos/                  # Runnable demos (compose/workflows) | 可运行 demo
│   ├── docker-compose/     # One-command stacks | 一键启动栈
│   └── workflows/          # n8n exports etc. | 工作流导出
├── governance/             # Security & compliance templates | 治理/合规模板
├── case-studies/           # Measured outcomes & lessons | 案例与复盘
│
│  # ── Spec-only scaffolding (规范+模板，先文档后实现) ────────────────
├── providers/              # LLM 提供方抽象 | LLM provider abstraction
│   ├── SPEC.md             # endpoint / auth / capabilities / cost / retry
│   ├── catalogs.md         # 6 家 provider 已知模型清单（带核验日期）
│   ├── schemas/            # provider-config JSON Schema
│   └── templates/          # registry + ollama/openrouter/openai/anthropic/gemini/grok
├── skills/                 # 技能注册、制作、蒸馏、迭代 | Skill registry, authoring, distillation, iteration
│   ├── SPEC.md             # frontmatter / lifecycle / tool binding / distillation / iteration overview
│   ├── ITERATION.md        # 迭代机制详细规范（lineage / variants / feedback / decision）
│   ├── catalogs.md         # 已知 skill 来源 + 跨平台字段映射 + 推荐 MCP 清单
│   ├── schemas/            # skill / registry / tool-binding / mcp-config / distillation / iteration / variant / feedback
│   └── templates/          # SKILL + 蒸馏 4 类 + iteration recipe/policy + feedback collector + lifecycle + wiki-maintainer
├── wiki/                   # LLM 持续维护的 synthesis 层 | LLM-maintained compounding wiki
│   ├── SPEC.md             # page kinds / ingest / query→page / lint contracts
│   ├── CONVENTIONS.md      # 编辑约定（schema 等价物）
│   ├── schemas/            # wiki-page / wiki-link / lint-issue
│   └── templates/          # 5 类 page + index/log + ingest/query→page/lint recipes
├── memory/                 # 记忆与本地知识库 | Memory & local KB / RAG
│   ├── SPEC.md             # 三层 memory + RAG pipeline + 检索/重排契约
│   ├── schemas/            # memory-record / kb-document / kb-chunk / retrieval-query
│   ├── templates/          # short/mid/kb config + ingestion + retrieval + md 样例
│   └── storage/            # SQLite DDL（含 FTS5） + LanceDB 表与索引说明
├── session/                # AI 会话与轨迹规范 | Session & trace spec
│   ├── SPEC.md             # 字段、状态机、redaction、retention、RBAC
│   ├── schemas/            # session / trace-event JSON Schemas
│   └── templates/          # meta / redaction-rules / retention-policy
├── sandbox/                # AI 动作隔离执行规范 | Sandbox execution spec
│   ├── SPEC.md             # action 契约、生命周期、策略契约
│   ├── backends/           # Docker / gVisor / Firecracker / Remote VM 选型
│   ├── policies/           # network / seccomp / resource quota
│   └── templates/          # action-request / approval-policy
├── harness/                # 评估与回归骨架 | Eval & regression harness
│   ├── SPEC.md             # 对象模型、evaluator 分类、指标
│   ├── schemas/            # fixture / eval-result JSON Schemas
│   └── templates/          # fixture / golden / rubric / eval-config
│
└── examples/               # 端到端样例（spec 闭环自验证）| End-to-end samples
    ├── scn_ticket_summary_zh/   # 中文工单摘要全链路 (zh-CN)
    └── scn_ticket_summary_en/   # 英文工单摘要全链路 (en) — i18n 镜像
        # 每个样例含: README + checks.md + kb/ + retrieval/ + session/ + harness/
```

## Architecture: Providers × Skills × Memory × Session × Sandbox × Harness

六者构成 OpsPilot 的"AI 代办闭环"：

```
   ┌───────────┐  ┌───────────┐  ┌───────────────────────────┐
   │ providers/│  │  skills/  │  │  memory/                   │
   │  models   │  │ registry +│  │  short / mid / long-term   │
   │           │  │ distillation│ │  SQLite + LanceDB + md     │
   │           │  │ + tool/MCP│  │  RAG (kb.search /          │
   │           │  │  bindings │  │       memory.search)       │
   └─────┬─────┘  └─────┬─────┘  └──────────┬─────────────────┘
         │ model_ref    │ skill_ref +       │ kb.search results
         ▼              ▼ tool/mcp bindings ▼ + memory recall
playbooks/  ──▶  Session(create) ◀──────────┘
                        │
                        ▼
                  proposed_action ──▶ sandbox/  ──▶ artifact
                        │                              │
                        ▼                              ▼
                  Session.trace  ◀────────  recording
                        │  (archive 时归约 → mid-term memory
                        │     + 可作为 skill distillation 源)
                        ▼
                  harness/(eval) ──▶  case-studies/
```

- **providers/**：可插拔 LLM 提供方（Ollama / OpenRouter / OpenAI / Anthropic / Gemini / Grok）；统一鉴权、能力声明、成本与降级
- **skills/**：技能注册 + **制作 + 蒸馏 + 迭代 + 工具/MCP 绑定**；从 traces / 文档 / 他人 skill / 跨平台 skill 蒸馏新技能；通过 lineage + variants + feedback signals 驱动持续演进
- **memory/**：三层记忆——短期（trace 内摘要）/ 中期（SQLite + markdown）/ 长期（LanceDB + markdown）；RAG 检索与重排
- **wiki/**：在 memory 长期 KB 之上叠的"LLM 持续维护的 synthesis 层"——5 类 page + cross-link + lint；与 LLM Wiki 模式对齐；query 答案可回写为新 page，形成 compounding insight loop
- **session/**：AI 任务的"上下文 + 轨迹 + 产物 + 审计"打包单元；合规落地的载体
- **sandbox/**：AI 提出动作的"先跑给你看，再决定要不要落地"的隔离执行层；默认 deny-all
- **harness/**：Prompt/Playbook 的"单元测试 + 回归门"；模型升级前后必跑

---

## 检索模式

| 模式 | 工作方式 | 适合场景 |
|------|---------|---------|
| `tool` | 模型通过 ReAct 循环自主调用 `kb_search` | Claude、GPT-4 等强模型 |
| `prefetch` | Orchestrator 提前检索并注入 system prompt，禁用工具调用 | Gemma、Phi 等弱 tool-call 本地模型 |

Playbook 通过 `retrieval.mode` 字段声明；`prefetch` 模式下 trace.jsonl 仍写入 `tool_call + tool_result` 事件，harness 评估口径不变。

---

## Rust 扩展

`src/opspilot_chunker/` 和 `src/opspilot_tokenizer/` 是 PyO3/maturin 编译的 Rust 扩展：

| 扩展 | 加速比 | 说明 |
|------|--------|------|
| `opspilot_chunker` | 9.6× | 标题感知文本分块 |
| `opspilot_tokenizer` | 45× | BPE-ish token 计数 |

安装时自动编译（`pip install -e ".[dev]"`），无需手动操作。

---

> ⚠️ **当前状态 / Status**：六个顶层目录均为 **spec-only**（规范+模板），不含运行实现。`src/opspilot/` 为可运行实现。
> ⚠️ **模型版本**：所有 `model_ref` 与 `embedding_model` 必须显式锁版本；禁用 `latest` / `auto` / `stable`。
> ⚠️ **PII 红线**：未脱敏内容不得入向量库 / SQLite / 蒸馏 pipeline；redaction 规则参见 `session/templates/redaction-rules.template.yaml`。
> ⚠️ **Skill 信任**：community / unknown 等级 skill 默认禁写动作 + 强制 sandbox；详见 `skills/templates/lifecycle-policy.template.yaml`。
