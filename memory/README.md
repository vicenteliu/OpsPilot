# Memory & RAG — 记忆与本地知识库 / Memory & Local KB

> **状态 / Status**：规范阶段（spec-only）。本目录只定义三层 memory 抽象、schema、模板与存储 schema；不含运行实现。
> **Stage**：spec only — 3-tier memory abstraction, schemas, templates, storage schemas. No runtime here.

## TL;DR
Memory（记忆）= AI 在跨会话工作时的"上下文持久化层"。OpsPilot 把它分成 **短期 / 中期 / 长期** 三层，每层映射到合适的存储后端（in-memory + SQLite + LanceDB）。RAG（Retrieval-Augmented Generation，检索增强生成）是长期层之上的"取上下文"动作。

## 三层抽象 / Three-tier model

```
                ┌────────────────────────────────────────────────────────────────┐
                │                     Session 当前调用                            │
                └───────────────────────┬────────────────────────────────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        │                               │                               │
        ▼                               ▼                               ▼
┌──────────────┐              ┌──────────────────┐           ┌──────────────────┐
│ short-term   │              │  mid-term        │           │  long-term (KB)  │
│ 短期记忆       │              │  中期记忆          │           │  知识库            │
│              │              │                  │           │                  │
│ 对话窗口       │              │  跨 session       │           │  文档 + 向量索引    │
│ 滚动摘要       │              │  项目 / workspace │           │  RAG 检索          │
├──────────────┤              ├──────────────────┤           ├──────────────────┤
│ TTL: 单 session│             │ TTL: 项目持续      │           │ TTL: 长期          │
│ 存储: in-memory│             │ 存储: SQLite     │           │ 存储: md + LanceDB │
│ 形态: JSONL   │              │ 形态: markdown +  │           │ 形态: markdown +   │
│       + summary│             │       record      │           │       chunks      │
└──────────────┘              └──────────────────┘           └──────────────────┘
```

## 各层职责 / Responsibilities

### 短期（short-term）
- **是什么**：当前 session 的对话窗口 + 对超长内容做的滚动摘要 + scratchpad 工作区
- **为什么**：上下文有 token 上限；超过时必须裁剪/摘要而不能简单截断
- **来源**：直接复用 `session/trace.jsonl`（已有 schema），不重建
- **典型大小**：几 KB ~ 几百 KB
- **是否入仓库**：否；session 归档时摘要进 mid-term

### 中期（mid-term）
- **是什么**：跨 session 的"项目知识 + 用户偏好 + 决策记录 + TODO"
- **为什么**：避免每次重新解释项目背景；让 AI 像有经验的同事
- **类型**（与 Claude Code memory 对齐）：`user / feedback / project / reference`
- **存储**：SQLite（结构化 + FTS5 全文检索） + 配套 markdown 源（git 友好）
- **典型大小**：几百条记录、几 MB
- **是否入仓库**：项目内的中期 memory 应该入 git；个人偏好走 `~/.opspilot/memory/`

### 长期（long-term，KB / 知识库）
- **是什么**：公司 SOP、Runbook、产品文档、历史案例摘要、Wiki 导入
- **为什么**：AI 回答工单/事故必须有"组织私有知识"作底
- **存储**：
  - **源**：markdown 文件（git 管控、人类可读、可审计）
  - **索引**：LanceDB（向量） + SQLite（元数据 + FTS5 keyword）
- **管道**：ingest → chunk → embed → upsert；增量重建以 `content_hash` 为锚
- **典型大小**：几千~几十万 chunk
- **是否入仓库**：markdown 源入 git；LanceDB 数据目录走 `.gitignore`（按需 build）

## 数据流 / Data flow

```
                ┌────────────┐ ingest
docs/wiki ────▶ │ ingestion  │ ───▶ chunks ──┐
                │  pipeline  │                │ embed
                └────────────┘                ▼
                                        ┌──────────┐
                                        │ providers│ (embedding model)
                                        └─────┬────┘
                                              ▼
                            ┌─────────┐  ┌─────────┐
                            │LanceDB  │  │ SQLite  │
                            │(vector) │  │(meta+FTS)│
                            └────┬────┘  └────┬────┘
                                 │            │
                                 └─────┬──────┘
                                       │ retrieve (vector + keyword + filter)
                                       ▼
                                 ┌──────────┐
                                 │  rerank  │ (optional, cross-encoder / llm)
                                 └────┬─────┘
                                      ▼
                                 ┌──────────┐
                                 │ session  │ ◀── trace.tool_call: kb.search
                                 │  prompt  │ ──▶ 引用块 + 摘要 入 prompt
                                 └──────────┘
```

## 设计原则 / Principles

1. **Markdown 是源 / Markdown is the source**：人类可读、git diff 友好；SQLite/LanceDB 是派生索引，可重建
2. **PII 不入向量库 / No PII in vectors**：摄入前强制走 `session/templates/redaction-rules.template.yaml`，hard-fail PII 检查
3. **锁定 embedding 版本 / Pin embedding model**：embedding 模型升级 = 全量重建索引；版本变更必须显式触发
4. **混合检索默认 / Hybrid retrieval by default**：vector (语义) + BM25 (关键字) + metadata filter（结构）；纯向量易漏关键字
5. **可追溯到源 / Citation mandatory**：每条检索结果必须能映射回 `source_path:line_start-line_end`；prompt 中注入引用标记
6. **增量同步 / Incremental sync**：以 `content_hash` 为锚；变更才重 chunk/embed
7. **多租户隔离 / Namespaces**：scope（team/product/sensitivity）级隔离；检索时强约束

## 范围 / Scope

In scope：
- 三层 memory 的数据模型与生命周期
- RAG ingestion + retrieval pipeline 契约
- SQLite + LanceDB schema 与命名约定
- 与 providers / session / sandbox / harness 的接口

Out of scope（暂不在此目录）：
- 具体 ingestion 实现（Python pipeline）
- 具体 retrieval client SDK
- UI 检索界面
- Graph RAG / Knowledge Graph（后续考虑）

## 目录结构 / Directory layout

```
memory/
├── README.md                              # 本文件
├── SPEC.md                                # 详细规范（含 RAG pipeline）
├── schemas/
│   ├── memory-record.schema.json          # 中期 memory record
│   ├── kb-document.schema.json            # 长期 KB 文档
│   ├── kb-chunk.schema.json               # chunk + vector ref
│   └── retrieval-query.schema.json        # 检索请求/响应
├── templates/
│   ├── memory-record.template.md          # 中期：markdown + frontmatter
│   ├── kb-document.template.md            # 长期：KB 文档样例
│   ├── short-term-config.template.yaml    # 短期：窗口/摘要策略
│   ├── mid-term-config.template.yaml      # 中期：SQLite/命名空间
│   ├── kb-config.template.yaml            # 长期：KB 路径与命名空间
│   ├── ingestion.template.yaml            # 摄入 pipeline
│   └── retrieval.template.yaml            # 检索/重排配置
└── storage/
    ├── sqlite-schema.sql                  # SQLite DDL（含 FTS5）
    └── lancedb-schema.md                  # LanceDB 表与索引说明
```

## 技术选型理由 / Why these stacks

| 组件 | 选 | 不选 | 原因 |
|---|---|---|---|
| 长期向量库 | **LanceDB** | Chroma / Weaviate / Qdrant / pgvector | embedded（无服务进程） + 列式（PyArrow） + 增量更新 + git-friendly 文件布局 |
| 元数据 / 关键字 | **SQLite + FTS5** | Postgres / Elastic | embedded、零运维；FTS5 内置 BM25；与 LanceDB 同为 file-based |
| 源格式 | **Markdown + frontmatter** | JSON / DB-only | 人类可读、git diff 友好、跨工具兼容（Obsidian / Foam / Logseq） |
| 短期 | 复用 session/trace | 单独再建一层 | 避免重复 schema；trace 已含 redaction、retention |

## 与其他目录的契约 / Contracts

| 上游 | 给 memory 的输入 |
|---|---|
| `providers/` | embedding model（必有 `capabilities.embeddings: true`） + 锁版本 |
| `governance/` | 数据分级 + redaction 规则 + 保留策略 |
| `playbooks/` | 声明检索需求（scopes、top_k、过滤器） |
| `session/` | 归档时把 session 摘要写入 mid-term；trace 中的 `tool_call: kb.search` 触发检索 |

| 下游 | memory 提供的产物 |
|---|---|
| `session/` | 检索结果作为 `tool_result`，引用块写入 prompt |
| `harness/` | KB-aware fixture（含已知应被检索的源） |
| `case-studies/` | 跨 session 知识沉淀 |

## 安全红线 / Hard nos

- ❌ 不允许把未脱敏文档摄入 KB（即使是私有部署）
- ❌ 不允许把 LanceDB 数据目录提交到 git（`.gitignore` 必含 `*.lance/` `data/lancedb/`）
- ❌ 不允许 sandbox 内的 sandbox 命令直接读 SQLite 文件（需走 retrieval API）
- ❌ 不允许 embedding 用 `latest`（与 providers 一致）
- ❌ 不允许在多租户场景下放开 namespace 过滤（防越权检索）

## 开放问题 / Open questions

- [ ] 短期 memory 的"摘要触发"由谁决策：Session 引擎、playbook、还是模型自决？
- [ ] 中期 memory 的"自动收割"（从 session 归档 → mid-term）需不需要 LLM 抽取还是规则即可？
- [ ] 多 embedding 模型并行（中文走 bge / 英文走 text-embedding-3）是否纳入默认配置？
- [ ] Graph RAG / 知识图谱是否要单独建一层 `memory/graph/`？
