# Memory & RAG — 详细规范 / Detailed Spec

## 1. 三层语义 / Three-tier semantics

| 层 | 范围 / Scope | TTL | 存储 / Backend | 命名空间 / Namespace |
|---|---|---|---|---|
| short-term | 单 session 内 | 与 session 状态绑定 | in-memory + 摘要写回 trace | session_id |
| mid-term | 项目 / workspace | 项目持续；可手动 expire | SQLite（含 FTS5） + markdown | `<workspace>:<scope>` |
| long-term (KB) | 知识库 | 长期；版本化 | markdown + LanceDB + SQLite meta | `<kb>:<scope>` |

## 2. Memory 类型（中期）/ Memory types (mid-tier)

与 Claude Code 等代理的 memory 模型对齐，便于跨工具迁移：

| `type` | 用途 | 例 |
|---|---|---|
| `user` | 用户角色、偏好、知识 | "用户是数据科学家，主攻 observability" |
| `feedback` | 用户对 AI 的纠正/确认（含 why） | "不要在 RCA 里堆砌时间戳；只列因果链" |
| `project` | 项目状态、决策、deadline、责任人 | "Q2 开始前完成 ITIL 落地试点；负责人 alice" |
| `reference` | 外部系统的指针（不是事实本身） | "工单系统在 Jira INC 项目；告警在 Grafana xx 板" |

`type` 是强约束（schema enum），用于检索过滤与显示分组。

## 3. Memory record 字段（中期） / Mid-term record fields

权威定义见 `schemas/memory-record.schema.json`。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | `mem_<sha8>` | ✓ | 内容寻址 |
| `type` | enum 见 §2 | ✓ | |
| `scope` | string | ✓ | 命名空间，例 `opspilot:user` / `opspilot:project` |
| `title` | string | ✓ | ≤80 字符；用于检索 hit list |
| `body` | string | ✓ | markdown 正文；带 **Why:** **How to apply:** 段（feedback/project 强约束） |
| `tags` | string[] | ✗ | 自由标签 |
| `source` | object | ✓ | 见 §4 |
| `created_at` | RFC3339 | ✓ | |
| `updated_at` | RFC3339 | ✓ | |
| `valid_until` | RFC3339 \| null | ✗ | 显式过期；过期后只读 |
| `confidence` | enum `low/medium/high` | ✓ | 影响检索权重 |
| `redacted` | bool | ✓ | 必须 true 才能入库 |

## 4. Source 追溯 / Source attribution

```yaml
source:
  origin: "session" | "user_input" | "ingest" | "system"
  session_id: "sess_..."        # 若 origin=session
  trace_seq: 42                  # 若来自具体 trace event
  document_id: "doc_..."         # 若 origin=ingest
  url: "https://..."             # 若来自外部
```

## 5. KB 文档（长期）/ KB document (long-term)

权威定义见 `schemas/kb-document.schema.json`。

```yaml
id: "doc_<sha8>"                 # sha8 of source_path + initial content_hash
source_path: "playbooks/sop_vpn.md"   # repo 内相对路径
source_url: null                  # 若来自外部 wiki，记录原 URL
title: "VPN 故障排查 SOP"
classification: "internal"        # public | internal | confidential | restricted
content_hash: "sha256:..."        # markdown 正文 sha256
version: "1.3.0"                  # 语义版本（可选）
ingested_at: "2026-05-01T10:00:00Z"
last_modified: "2026-04-28T08:30:00Z"
language: "zh-CN"
tags: ["vpn", "sop", "L1"]
namespace: "opspilot:public-kb"
chunk_strategy: "headings_then_size"  # 见 §7
chunk_count: 12
embedding_model: "ollama/nomic-embed-text@2024-02"
embedding_dim: 768
redaction_passed: true
redaction_rules_version: "1.0.0"
```

## 6. Chunk schema / Chunk metadata

权威定义见 `schemas/kb-chunk.schema.json`。

```yaml
id: "chk_<sha8>"
document_id: "doc_..."
seq: 0
content: "..."                    # 已脱敏的 chunk 文本（或 artifact 引用）
content_hash: "sha256:..."
char_start: 0                     # 在 markdown 源中的字符 offset
char_end: 1024
line_start: 1
line_end: 24
heading_path: ["VPN SOP", "故障排查", "认证错误"]   # 标题面包屑
embedding_model: "ollama/nomic-embed-text@2024-02"
vector_id: "<lancedb 行 id>"      # LanceDB 主键引用
metadata:
  tags: ["vpn", "auth"]
  namespace: "opspilot:public-kb"
  classification: "internal"
```

## 7. Chunking 策略 / Chunking strategies

允许的 `chunk_strategy`（在 `templates/ingestion.template.yaml` 中配置）：

| 策略 | 适用 | 关键参数 |
|---|---|---|
| `headings_then_size` | markdown / SOP（**推荐默认**） | `target_size_tokens=512`, `max_size_tokens=1024`, `overlap_tokens=64` |
| `fixed_size` | 纯文本 / 日志样本 | `size_tokens=512`, `overlap_tokens=64` |
| `sentence_boundary` | 长段落、合规文档 | `max_size_tokens=512`, `overlap_sentences=2` |
| `code_aware` | 代码 / 配置 | 按语言 AST / 顶层 def-block 切分 |
| `semantic` | 实验性 | embedding 相似度突变作为切点；成本高 |

强约束：
- 任何策略都要保留 `heading_path`（markdown 标题层级），便于检索结果归位
- token 计数器必须与下游 embedding 模型一致（避免实际超长被截）
- `overlap` 不允许为 0（除非 fixed_size + 短文档）

## 8. Embedding 选型与对接 providers / Embedding selection

embedding 调用走 `providers/` 抽象层（要求 provider 的 `capabilities.embeddings: true`）。

推荐组合（信息日期 2026-05-01；以 catalogs.md 为准）：

| 用途 | 推荐 model_ref | dim | 备注 |
|---|---|---|---|
| **本地 / 离线（默认）** | `ollama-local/nomic-embed-text@2024-02` | 768 | 中英通用；零成本；自托管 |
| 中文偏强 | `ollama-local/bge-m3@2024-06` | 1024 | 多语言 + 长文本 |
| 云端高质量 | `openai-main/text-embedding-3-large@2024-01` | 3072 | 需出网；按 token 计费 |
| 云端低成本 | `openai-main/text-embedding-3-small@2024-01` | 1536 | 折中 |
| Gemini | `gemini-main/text-embedding-004@2024-04` | 768 | 与 Gemini 生态一致时 |

**强约束**：
- 一个 KB namespace 一旦确定 embedding 模型，**不允许混用其他模型**（向量空间不可比）
- 升级 embedding 模型 = 新建 namespace 或全量重建索引
- `embedding_model` 字段必须含具体版本，禁用 `latest`

## 9. Retrieval 契约 / Retrieval contract

权威定义见 `schemas/retrieval-query.schema.json`。

### 9.1 请求 / Request

```yaml
query: "VPN 认证失败如何排查"
mode: "hybrid"                    # vector | keyword | hybrid
scopes:
  - "opspilot:public-kb"
top_k: 8
filters:
  classification:
    in: ["public", "internal"]
  tags:
    any_of: ["vpn", "auth"]
  language: "zh-CN"
hybrid:
  vector_weight: 0.6
  keyword_weight: 0.4
  fusion: "rrf"                   # rrf (Reciprocal Rank Fusion) | weighted_sum
rerank:
  enabled: true
  type: "cross_encoder"           # cross_encoder | llm | none
  top_n: 4
  model_ref: "ollama-local/bge-reranker-v2-m3@2024-08"
budget_usd: 0.02
return_citations: true
```

### 9.2 响应 / Response

```yaml
query_id: "q_<ULID>"
results:
  - chunk_id: "chk_..."
    document_id: "doc_..."
    score: 0.87                   # 归一到 [0,1]
    rank: 1
    content: "...摘录..."
    citation:
      source_path: "playbooks/sop_vpn.md"
      line_start: 41
      line_end: 58
      heading_path: ["VPN SOP", "故障排查", "认证错误"]
      anchor: "#故障排查-认证错误"   # 可选 markdown anchor
    namespace: "opspilot:public-kb"
    classification: "internal"
metadata:
  total_candidates: 32
  vector_hits: 24
  keyword_hits: 18
  rerank_used: true
  cost_usd: 0.001
  latency_ms: 412
```

## 10. Retrieval 模式 / Retrieval modes

| mode | 引擎 | 适合 |
|---|---|---|
| `vector` | LanceDB ANN | 语义近似、模糊查询 |
| `keyword` | SQLite FTS5 (BM25) | 精确名词、错误码、命令 |
| `hybrid` | 两者并行 + 融合（默认） | 通用 |

融合方式：
- **RRF**（Reciprocal Rank Fusion，**默认**）：`score = Σ 1 / (k + rank_i)`，k=60；对排名鲁棒
- **weighted_sum**：归一化分数加权；需要谨慎调权重

## 11. Rerank 策略 / Rerank

| type | 说明 | 适合 |
|---|---|---|
| `none` | 不重排 | 简单查询、低成本 |
| `cross_encoder` | 跨编码器 reranker（如 bge-reranker-v2） | 默认推荐；本地可跑；几十 ms |
| `llm` | LLM-as-rerank（小 judge 模型） | 复杂语义；成本与延迟高 |

强约束：
- rerank 模型版本同样必须锁定
- `top_k > top_n`：先粗排取 k，再精排到 n
- `budget_usd` 必须能覆盖 rerank 调用

## 12. Ingestion pipeline / 摄入流程

阶段（每阶段都必须可重入、可恢复）：

```
discover ──▶ classify ──▶ redact ──▶ chunk ──▶ embed ──▶ upsert
   │           │            │         │         │          │
   ▼           ▼            ▼         ▼         ▼          ▼
 source     metadata     redacted  chunks   vectors    indices
 manifest    record      content                       updated
```

| 阶段 | 输入 | 输出 | 失败处理 |
|---|---|---|---|
| discover | 配置中的 sources | source manifest（路径 + last_modified） | skip + 记录 |
| classify | source | classification + tags | 默认 internal |
| redact | 原文 | 脱敏文本 + 命中记录 | hard-fail（PII 残留即拒绝入库） |
| chunk | 脱敏文本 | chunk 列表（含 heading_path） | 跳过该文档 + 标记 dirty |
| embed | chunk 文本 | 向量 | 重试 → 标记 pending |
| upsert | 文档 + chunk + 向量 | LanceDB + SQLite 行更新 | 事务回滚 |

**增量同步**：
- 以 `source_path` + `content_hash` 为锚
- `content_hash` 不变 → 跳过整个文档
- `content_hash` 变化 → 删旧 chunks（按 document_id）+ 重新 chunk/embed/upsert
- 文档被删除 → cascade 删除该 doc 下所有 chunks

## 13. 短期 memory 的实现要点 / Short-term details

短期 memory 不单独建表，而是**复用 `session/trace.jsonl`** + 一组运行时策略。

策略（在 `short-term-config.template.yaml` 中）：

```yaml
context_window:
  max_tokens: 100000              # 与 model 的 long_context_tokens 对齐
  reserve_for_response: 8000
  reserve_for_system: 4000

policy:
  on_overflow: "summarize_oldest"  # truncate | summarize_oldest | summarize_smart
  summarize_when_remaining_lt: 16000   # 触发摘要的剩余预算阈值
  keep_pinned: true                # user_action=pin 的事件不参与裁剪
  keep_last_n_user_turns: 4

summary:
  use_provider_alias: "@chat-fast" # 摘要走快速档；与主 playbook provider 解耦
  template_ref: "prompts/summarize_session_zh.md"
  max_summary_tokens: 1024
  store_as_trace_event: "system"    # 写回 trace（type=system, event=summary_marker）
```

## 14. 中期 memory 的写入与收割 / Mid-term write & harvest

写入路径：
1. **直写**：用户/playbook 显式提交（`memory.add(...)`）
2. **收割**：session 归档时，从 trace 抽取出值得长期保留的事实

收割规则（建议）：
- `user_action=accept` 后被显式标记 `pin_to_memory`
- `user_action=edit` 携带的 `payload_diff` 含 "remember"/"记住" 字眼
- session 状态从 `archived → finalize` 时，由 summarizer 输出候选，等用户确认

**反模式（不要做）**：
- 不要把"代码模式 / 文件路径 / 项目结构"放进 memory（grep 即可得）
- 不要把"git history / 谁改了什么"放进 memory（`git log`/`git blame` 是权威）
- 不要把"调试解决方案"放进 memory（修复在代码里，commit message 有 context）

参考：与 Claude Code 的 memory 系统设计对齐，便于跨工具复用。

## 15. 安全与脱敏 / Security & redaction

强约束（在 schema / pipeline 中硬编码）：
- 进入 SQLite / LanceDB 的内容必须 `redacted=true`
- ingestion pipeline 必须在 chunking **之前** 跑 redact
- 用 `session/templates/redaction-rules.template.yaml` 作为最小集
- 命中规则的全部记录写入 `audit.log`（与 session 同格式）
- `classification=restricted` 文档默认不入向量库；只走 keyword + 受限命名空间

## 16. 与其他目录的接口 / Interfaces

### 16.1 Session（trace 中的工具调用）

memory 暴露给 session 的工具：

```yaml
tool: "kb.search"
args:
  query: "<string>"
  scopes: [...]
  top_k: 8
  filters: {...}

tool: "memory.add"
args:
  type: "feedback" | "project" | ...
  scope: "..."
  title: "..."
  body: "..."

tool: "memory.search"
args:
  type_filter: ["feedback"]
  scope: "..."
  query: "..."
```

### 16.2 Sandbox

sandbox 不直接访问 SQLite/LanceDB 数据文件；只能通过 `kb.search` / `memory.search` 工具调用。

### 16.3 Harness

harness 评估 RAG playbook 时：
- fixture 含"应被检索到的文档 id 列表"作为 ground truth
- evaluator 类型扩展：`rag.recall@k`、`rag.precision@k`、`rag.citation_validity`

### 16.4 Providers

- embedding：要求 `capabilities.embeddings: true`
- rerank：可选 LLM rerank 时走 `@judge` alias

## 17. 强约束 / Hard requirements

- markdown 是源；SQLite/LanceDB 可重建
- 所有 ID 内容寻址（`mem_<sha8>` / `doc_<sha8>` / `chk_<sha8>`）
- `embedding_model` 字段含具体版本；同 namespace 不允许混用
- `redacted=true` 是入库前置条件
- `classification=restricted` 文档不入向量库
- 每条检索结果必须有 `citation`，可定位到 `source_path:line_range`
- LanceDB 数据目录加入 `.gitignore`；markdown 源入 git
