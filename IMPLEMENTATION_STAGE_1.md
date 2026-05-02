# Stage 1 实现设计 / Implementation Design — Stage 1

> **本文目的**：把 ARCHITECTURE.md §8 Stage 1 拆解为可执行的设计：repo layout、模块边界、API 契约、CLI 命令、测试策略、增量 PR 计划。
> **状态**：设计阶段（design only）；本文不含真实代码，但每个模块都给出 protocol/类型签名。
> **读完应知**：①第一行代码该写在哪里，②每个 PR 的退出标准是什么。

## TL;DR

- **范围**：Ollama 单 provider + 1 份 KB 文档 + 1 个 hardcoded playbook + memory long-term + session + harness 单 fixture
- **不做**：sandbox / skills / wiki / iteration / distillation / 其他 5 个 provider
- **退出标准**：CLI 跑 `examples/scn_ticket_summary_zh/` 的 fixture，输出**结构等价 + schema valid + RAG 三件套全过 + judge ≥ 0.85**（不是字节一致）
- **栈**：Python 3.12 + Typer + Pydantic + LanceDB + SQLite/FTS5 + httpx (Ollama) + jsonschema + pytest
- **PR 切分**：8 个，每个 ≤ 600 行；从 schema 工具链开始，最后做 golden test
- **总时长估计**：1.5–2 周（单人全职）

---

## 0. CLAUDE.md §1 实施前的反思 / Pre-build sanity check

按 CLAUDE.md "Don't assume. Surface tradeoffs"：

### 0.1 错误假设：bytes-exact 输出可达

ARCHITECTURE.md §8 退出标准写的是"与样例字节级一致"——这是不可达的：

- LLM 输出有随机性；即使锁 `seed`、`temperature=0`，**不同硬件/驱动版本的浮点不一致**仍会导致 token 不同
- Ollama 的 `seed` 参数支持因模型而异
- 即使全锁住，**新版模型（如 Sonnet 后续小版本）发布后**就不一致

**修正**：Stage 1 退出标准改为"**结构等价**"——同 schema 通过 + 同关键字段命中 + 同 RAG ground truth 命中 + judge.llm 评分 ≥ 0.85。详见 §9。

### 0.2 已识别的 trade-offs

| 决定 | 选 A | 选 B | 决定 | 理由 |
|---|---|---|---|---|
| 同步 vs 异步 | sync | async | **sync** | Stage 1 单线程足够；async 留 Stage 3 多 provider 并发时引入 |
| Provider 抽象 | LiteLLM | 手撸 | **手撸**（仅 Ollama） | LiteLLM 抽象漏（Anthropic 工具调用/缓存被磨平）；Stage 2 再评估是否引入 |
| Playbook 形态 | 纯 markdown + 运行时解释 | hardcoded Python | **hardcoded Python**（Stage 1 一个） | 通用 playbook runner 留 Stage 3；首版避免 over-engineering |
| Embedding | sentence-transformers 本地 | Ollama embedding | **Ollama embedding** (`nomic-embed-text`) | 跟样例 model_ref 一致；零额外依赖 |
| Chunking | LangChain text splitter | 手撸 markdown-aware | **手撸**（≤200 行） | LangChain 太重；样例的 `headings_then_size` 策略简单可写 |
| Rerank | bge-reranker via Ollama | 跳过（Stage 1） | **跳过**（用 hybrid score 直接） | rerank 模型 Ollama 部署需额外工作；先把闭环跑通 |
| sandbox | Docker SDK | subprocess | **跳过**（Stage 1） | 唯一 tool 是 `kb.search`（read-only），不需要执行 |
| 持久化 session | 文件系统 | SQLite | **文件系统**（跟样例对齐） | 样例用 `sessions/<id>/...` 文件树；Stage 3 再决定 |

### 0.3 不确定（先做最小，留口子）

- Ollama 实际生成的 JSON 是否稳定（`format=json` 模式下）—— 不稳定时加 retry + JSON repair
- LanceDB 在 macOS 与 Linux 上行为差异 —— 仅在 Linux 容器测；macOS 走 docker-compose
- 中文 FTS5 分词 —— 默认 unicode61 + ngram；测过精确匹配用例后再考虑 jieba

---

## 1. Repo Layout

```
OpsPilot/
├── README.md                    (existing)
├── ARCHITECTURE.md              (existing)
├── CLAUDE.md                    (existing)
├── IMPLEMENTATION_STAGE_1.md    ← 本文
│
├── pyproject.toml               (新建 PR-1)
├── Makefile                     (新建 PR-1)
├── docker-compose.yml           (新建 PR-3, 跑 Ollama)
├── Dockerfile                   (新建 PR-8, opspilot CLI image)
├── .python-version              (3.12)
├── .env.example                 (新建 PR-1)
│
├── src/opspilot/
│   ├── __init__.py
│   ├── __main__.py              # `python -m opspilot`
│   ├── cli.py                   # Typer entry; routes to subcommands
│   ├── config.py                # 加载 ~/.opspilot/config.yaml + env vars
│   ├── errors.py                # 统一异常类
│   ├── ids.py                   # ULID / sha256[:8] 工具
│   ├── redaction.py             # PII 脱敏（基于 redaction-rules.yaml）
│   ├── schemas.py               # 加载所有 JSON schema + validate()
│   ├── timeutil.py              # RFC3339 UTC helpers
│   │
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py              # ProviderProtocol（Protocol/ABC）
│   │   ├── ollama.py            # Ollama 实现
│   │   ├── registry.py          # 加载 provider-registry.yaml → 实例化
│   │   └── types.py             # ChatRequest / ChatResponse / Message
│   │
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── ingestion.py         # discover → redact → chunk → embed → upsert
│   │   ├── chunker.py           # markdown headings_then_size strategy
│   │   ├── lance_store.py       # LanceDB wrapper（建表 + upsert + ann query）
│   │   ├── sqlite_store.py      # SQLite + FTS5 wrapper（按 sqlite-schema.sql 建表）
│   │   ├── retrieval.py         # kb.search hybrid（vector + bm25 + RRF）
│   │   └── types.py             # KbDocument / Chunk / RetrievalResponse
│   │
│   ├── session/
│   │   ├── __init__.py
│   │   ├── manager.py           # 生命周期：create/active/archive/purge
│   │   ├── trace.py             # trace.jsonl writer（保证 seq 单调 + valid JSON）
│   │   ├── artifact.py          # 写入 art_<sha8>.<ext> + sidecar yaml
│   │   ├── audit.py             # audit.log writer（仅 append）
│   │   └── types.py             # Session / TraceEvent / ArtifactRef
│   │
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── ticket_summary.py    # 唯一 playbook 的硬编码逻辑（Stage 1）
│   │   └── tools.py             # builtin tools: kb.search, artifact.write
│   │
│   └── harness/
│       ├── __init__.py
│       ├── runner.py            # 跑 1 个 fixture → 1 个 session → 评估
│       ├── reporter.py          # 写 results.jsonl + report.md
│       ├── types.py
│       └── evaluators/
│           ├── __init__.py
│           ├── base.py          # EvaluatorProtocol
│           ├── pii_check.py     # rule.pii_check
│           ├── regex.py         # rule.regex (must_contain / must_not_contain)
│           ├── json_schema.py   # rule.json_schema
│           ├── rag_recall.py    # rag.recall_at_k
│           ├── rag_precision.py # rag.precision_at_k
│           ├── rag_citation.py  # rag.citation_validity
│           └── judge_llm.py     # judge.llm（Stage 1 用同一 Ollama；非锁版本评判模型也 OK）
│
├── tests/
│   ├── conftest.py              # 加载 examples/ 作 fixtures（path-based）
│   ├── test_ids.py
│   ├── test_redaction.py
│   ├── test_schemas.py          # 跑全仓 examples/ 通过对应 schema
│   ├── test_chunker.py          # chunker 输出与 examples/scn_*_zh/kb/chunks.jsonl 对齐
│   ├── test_sqlite_store.py
│   ├── test_lance_store.py
│   ├── test_retrieval.py
│   ├── test_session.py
│   ├── test_evaluators.py       # 各 evaluator 用 results.jsonl 单条作为 oracle
│   └── golden/
│       └── test_zh_e2e.py       # 端到端跑 examples/scn_ticket_summary_zh/
│
├── docs/                        (existing dir, 加 dev guide)
│   └── stage1-dev.md            # 开发者快速开始（PR-1 写）
│
└── (existing dirs: prompts/, playbooks/, demos/, governance/, case-studies/,
                    providers/, memory/, session/, sandbox/, harness/, skills/, wiki/, examples/)
```

**关键不变量**：
- `src/opspilot/` 是唯一的运行代码目录；其他根目录都是 spec（不可被 import）
- `examples/` 既是文档也是测试 fixture（`tests/conftest.py` path-based 加载）
- spec 目录（`providers/`、`memory/` 等）放 schemas + templates；运行时通过 `schemas.py` 读取

---

## 2. 模块边界与 API 契约 / Module boundaries

### 2.1 `providers/` — LLM 抽象

```python
# src/opspilot/providers/base.py
class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None  # for role=tool

class SamplingParams(BaseModel):
    temperature: float = 0.2
    top_p: float = 0.9
    max_tokens: int = 2000
    seed: int | None = None
    stop: list[str] | None = None

class ChatResponse(BaseModel):
    content: str
    finish_reason: Literal["stop","length","tool_call","content_filter","error"]
    tool_calls: list[ToolCall] | None = None
    usage: Usage  # {input_tokens, output_tokens, cost_usd}

class ProviderProtocol(Protocol):
    """所有 provider 必须实现这个。"""
    provider_id: str   # 如 "ollama-local"
    kind: Literal["ollama","openai","anthropic", ...]

    def chat(
        self,
        messages: list[Message],
        *,
        model: str,                  # 不含版本（版本由 caller 校验）
        params: SamplingParams,
        tools: list[ToolDef] | None = None,
        timeout_ms: int = 90000,
    ) -> ChatResponse: ...

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]: ...

    def health_probe(self) -> bool: ...
```

```python
# src/opspilot/providers/ollama.py（Stage 1 唯一实现）
class OllamaProvider:
    """Calls Ollama via http://localhost:11434/v1 (OpenAI-compatible) for chat
       and /api/embeddings for embeddings. No auth (single-user)."""
    def chat(...): ...
    def embed(...): ...
```

**契约**：
- `model` 参数**不含**版本号（如 `qwen2.5:14b-instruct`）；版本来自 caller 的 `model_ref` 拆分
- `chat` 在 `format=json` 不稳定时由 caller 加 retry；provider 不重试业务级错误
- 失败用 `errors.ProviderError` 抛出，含 `error_code` (timeout/4xx/5xx)

### 2.2 `memory/` — 知识层

```python
# src/opspilot/memory/types.py
class KbDocument(BaseModel):  # ↔ memory/schemas/kb-document.schema.json
    id: str  # doc_<sha8>
    source_path: str
    classification: Literal["public","internal","confidential","restricted"]
    content_hash: str
    embedding_model: str
    ...

class Chunk(BaseModel):  # ↔ memory/schemas/kb-chunk.schema.json
    id: str  # chk_<sha8>
    document_id: str
    seq: int
    content: str | None
    line_start: int
    line_end: int
    char_start: int
    char_end: int
    heading_path: list[str]
    vector_id: str
    metadata: ChunkMeta

class RetrievalResponse(BaseModel):
    query_id: str  # q_<ULID>
    results: list[RetrievalHit]
    metadata: RetrievalMeta
```

```python
# src/opspilot/memory/retrieval.py
def kb_search(
    query: str,
    *,
    mode: Literal["vector","keyword","hybrid"] = "hybrid",
    scopes: list[str],
    top_k: int = 8,
    filters: dict | None = None,
    rerank: RerankConfig | None = None,
    sqlite: SqliteStore,
    lance: LanceStore,
    embedder: Callable[[str], list[float]],
) -> RetrievalResponse:
    """Hybrid:
       - vector branch: lance.search(embed(query), k=top_k_ann, filter=...)
       - keyword branch: sqlite.fts5_search(query, k=top_k_fts, filter=...)
       - fusion: RRF (k=60)
       - rerank (Stage 1: skip)
       - enrich citations from sqlite.v_chunks_with_doc view
    """
```

**契约**：
- `kb.search` 是**纯函数**（依赖注入 sqlite/lance/embedder）；便于测试
- 输出符合 `retrieval-query.schema.json#oneOf[1]`（运行时 validate）
- `RRF k=60` 是 spec 默认（与 SPEC.md §10）；Stage 1 不可调

### 2.3 `session/` — 任务层

```python
# src/opspilot/session/manager.py
class SessionManager:
    """Manages one session's filesystem layout under sessions/<sess_id>/"""
    def create(self, *, playbook: PlaybookRef, model: ModelSpec, owner: str,
               sensitivity: Sensitivity, retention: Retention) -> Session: ...
    def write_input(self, session: Session, name: str, payload: bytes) -> None: ...
    def append_trace(self, session: Session, event: TraceEvent) -> None: ...
    def write_artifact(self, session: Session, payload: bytes, ext: str) -> ArtifactRef: ...
    def append_audit(self, session: Session, line: AuditEntry) -> None: ...
    def archive(self, session: Session, reason: str) -> None: ...
```

**契约**：
- `append_trace` 保证 `seq` 单调；崩溃恢复时按文件最大 seq 续写
- `write_artifact` 计算 sha256 → `art_<sha8>.<ext>` + 写 sidecar yaml
- `append_audit` 是 append-only；不允许覆盖
- 所有写入前调 `redaction.scan(payload)`；hard-fail 抛 `RedactionError`

### 2.4 `orchestrator/` — Stage 1 唯一 playbook

```python
# src/opspilot/orchestrator/ticket_summary.py
def run_ticket_summary_zh(
    *,
    ticket_input: dict,              # 来自 fixture.input
    session: SessionManager,
    provider: ProviderProtocol,
    retrieval: Callable[..., RetrievalResponse],
    config: TicketSummaryConfig,
) -> ArtifactRef:
    """Hardcoded for Stage 1. Implements the same data flow as
       examples/scn_ticket_summary_zh/session/trace.jsonl (10 events):

       1. system: state_change → active
       2. prompt: system instruction
       3. prompt: user (ticket content)
       4. tool_call: kb.search
       5. tool_result: kb.search
       6. response: NL summary + footnote
       7. tool_call: artifact.write
       8. tool_result: artifact written
       9. user_action: accept (auto for Stage 1)
       10. system: state_change → archived

       Returns the final artifact ref (art_<sha8>).
    """
```

**契约**：
- 这是 Stage 1 **唯一**的 playbook 实现；通用 runner 留 Stage 3
- 函数纯可测；所有依赖注入
- 内部 prompt 模板存 `playbooks/pb_ticket_summary_zh/prompt.md`（Stage 1 新建）

### 2.5 `harness/` — 评估层

```python
# src/opspilot/harness/runner.py
def run_harness(
    config_path: Path,
    *,
    out_dir: Path,
    deps: HarnessDeps,           # 注入 provider / sqlite / lance / orchestrator
) -> HarnessReport:
    """Runs one fixture × one playbook × one model;
       writes results.jsonl matching harness/schemas/eval-result.schema.json"""

# src/opspilot/harness/evaluators/base.py
class EvaluatorProtocol(Protocol):
    id: str
    type: Literal["rule.pii_check","rule.regex",...,"judge.llm"]
    weight: float
    hard_fail: bool
    def evaluate(self, *, fixture: Fixture, output: ArtifactPayload,
                 retrieval: RetrievalResponse | None,
                 golden: Golden) -> EvaluatorResult: ...
```

**契约**：
- 每个 evaluator 是独立类，pytest 单测覆盖
- `evaluate()` 是纯函数（无 IO）；`judge.llm` 是例外（调 provider），但同样依赖注入
- weighted score 计算逻辑在 `runner.py`，不在 evaluator 内

---

## 3. 数据流 / End-to-end call chain

`opspilot run --playbook pb_ticket_summary_zh --input ticket.json` 的完整调用：

```
cli.run(playbook="pb_ticket_summary_zh", input=Path("ticket.json"))
  │
  ▼ config.load() → 读 ~/.opspilot/config.yaml + env vars
  │
  ▼ providers.registry.load("anthropic-claude") → OllamaProvider 实例（Stage 1 hardcode 改用 ollama-local）
  │
  ▼ memory.lance_store.LanceStore.open(<kb_path>)
  ▼ memory.sqlite_store.SqliteStore.open(<kb_path>)
  ▼ embedder = provider.embed (closure with model="nomic-embed-text")
  │
  ▼ session = SessionManager.create(playbook=..., model=..., owner=..., ...)
  │     └─ 写 sessions/<sess_id>/meta.yaml
  │     └─ append audit "system create"
  │     └─ append trace seq=0 system state_change=active
  │
  ▼ session.write_input("ticket.json", redact(load(input)))
  │     └─ append audit "system redact"
  │     └─ append trace seq=1 prompt(system)
  │     └─ append trace seq=2 prompt(user) with ticket content
  │
  ▼ orchestrator.run_ticket_summary_zh(...)
  │     ├─ Step A: build prompt with system + ticket
  │     ├─ Step B: provider.chat(messages, model=..., tools=[kb.search])
  │     │           → response with tool_calls=[kb.search(query="VPN 认证失败...")]
  │     ├─ Step C: append trace seq=3 tool_call(kb.search) action_id=act_<ULID>
  │     ├─ Step D: retrieval = kb_search(query=..., scopes=..., top_k=8, hybrid)
  │     ├─ Step E: append trace seq=4 tool_result(kb.search) status=ok
  │     ├─ Step F: feed tool_result back to provider.chat(messages + tool_result)
  │     │           → final response with NL summary
  │     ├─ Step G: append trace seq=5 response(content)
  │     ├─ Step H: extract structured JSON from response → write_artifact
  │     │           → artifact_id = art_<sha8>
  │     ├─ Step I: append trace seq=6 tool_call(artifact.write)
  │     ├─ Step J: append trace seq=7 tool_result(artifact.write) artifact_ids=[...]
  │     └─ return artifact_ref
  │
  ▼ session.append_trace(seq=8, user_action=accept)   # Stage 1 auto-accept
  ▼ session.archive(reason="user_action.accept")
  │     └─ append trace seq=9 system state_change=archived
  │
  ▼ print(f"Session archived: {session.id}\nArtifact: {artifact_ref.path}")
```

**强约束**：
- 任何步骤失败：trace 写入 `system event=error`；session 状态置 `aborted`；exit code != 0
- 所有 trace 事件必须通过 `schemas.validate("trace-event", event_dict)` 才能 append
- 所有 redaction warning 累计到 `audit.log` + 触发 trace `system event=redaction`

---

## 4. CLI 设计 / CLI

### 4.1 顶层命令

```
opspilot                                    # show help
opspilot --version
opspilot --help

opspilot init                               # 初始化 ~/.opspilot/{config.yaml,kb/,sessions/}
opspilot ingest <markdown_path> ...         # KB ingest
opspilot run --playbook <id> --input <json> # 跑一次任务
opspilot harness run --config <yaml> ...    # 跑评估
opspilot validate <file_or_dir>             # JSON schema 验证
opspilot inspect session <sess_id>          # 调试：打印 trace/audit
```

### 4.2 详细签名

```bash
# init
opspilot init [--home <path>]

# ingest（Stage 1 仅支持 markdown）
opspilot ingest <markdown_path>
  --namespace opspilot:public-kb               # 必填
  --classification {public,internal,confidential,restricted}  # 默认 internal
  --embedding-model ollama-local/nomic-embed-text@2024-02     # 默认
  --kb-name <name>                             # 默认 default
  --dry-run

# run
opspilot run
  --playbook <id>                              # 例 pb_ticket_summary_zh
  --input <json_path>                          # ticket fixture 形态
  --provider <provider_id>                     # 默认 ollama-local
  --model <model_ref>                          # 默认 ollama-local/qwen2.5:14b-instruct@2024-09
  --kb-name <name>                             # 默认 default
  --owner <user>                               # 默认 $USER
  --sensitivity {public,internal,confidential,restricted}     # 默认 internal
  --retention {low,medium,high,critical}       # 默认 medium

# harness run
opspilot harness run
  --config <yaml>                              # 例 examples/scn_ticket_summary_zh/harness/run-config.yaml
  --out <dir>                                  # 默认 /tmp/opspilot-harness/<run_id>/
  --provider-override <id>                     # 可选；用本地 ollama 跑 baseline

# validate
opspilot validate <file_or_dir>
  --schema-name <name>                         # 自动检测（按 $id）
  --recursive
```

### 4.3 退出码

| code | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 一般失败 |
| 2 | 输入校验失败（schema invalid） |
| 3 | 配置/凭证错误 |
| 4 | Provider 调用失败（重试耗尽） |
| 5 | Redaction hard-fail |
| 64 | harness 内部错误（与 spec 一致） |

---

## 5. 配置与 secrets / Config & secrets

### 5.1 `~/.opspilot/config.yaml`

```yaml
version: "1.0.0"
home: ~/.opspilot

provider_registry: governance/providers/registry.yaml   # 可选；缺省用内置

kb:
  default:
    storage:
      sqlite_path: ~/.opspilot/kb/default/meta.db
      lancedb_path: ~/.opspilot/kb/default/lancedb/
    namespace: "opspilot:public-kb"
    embedding:
      provider_id: "ollama-local"
      model: "nomic-embed-text"
      version: "2024-02"
      dim: 768

ollama:
  base_url: "http://localhost:11434"

logging:
  level: INFO
  audit_dir: ~/.opspilot/audit/
```

### 5.2 `.env.example`

```bash
# Stage 1 仅 Ollama（无密钥）；后续 stage 用：
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# OPENROUTER_API_KEY=...

OPSPILOT_HOME=$HOME/.opspilot
OPSPILOT_LOG_LEVEL=INFO
```

### 5.3 Secrets 加载

- 永远从 env 读；不允许 hardcode、不允许 yaml literal
- 启动时校验：`mcp-config.global_policy.block_secrets_in_env_literals` 等价检查（即使 Stage 1 没用 MCP，工具链先备好）

---

## 6. 测试策略 / Testing strategy

### 6.1 测试分层

| 层 | 范围 | 跑法 | 触发 |
|---|---|---|---|
| Unit | 单模块（chunker / redaction / ids 等）| pytest | `make test` |
| Schema | examples/ 下所有实例通过 schema | pytest（参数化）| `make validate` |
| Integration | 多模块组合（ingestion 全流程；retrieval 全流程） | pytest + LanceDB tmp dir | `make test-int` |
| Golden | 端到端跑 examples/scn_ticket_summary_zh | pytest（标 slow） | `make golden` |

### 6.2 Golden test 关键设计

```python
# tests/golden/test_zh_e2e.py
@pytest.mark.slow
def test_zh_e2e(tmp_kb, ollama_running):
    # 1. ingest 样例 KB
    ingest("examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md", namespace="opspilot:public-kb")

    # 2. run playbook with the fixture's input
    fixture = json.load(open("examples/scn_ticket_summary_zh/harness/fixture.json"))
    result = run(playbook="pb_ticket_summary_zh", input=fixture["input"])

    # 3. 校验 — 不是 bytes-exact
    assert validate(result.artifact_path, schema="ticket_summary_v1")

    artifact = json.load(open(result.artifact_path))
    assert "authentication failed" in str(artifact)
    assert "多名用户" in artifact["summary"]
    assert "VPN 网关" in str(artifact["next_actions"])
    assert artifact["scope"] == "multiple_users"
    assert artifact["severity_suggested"].startswith("P")
    assert len(artifact["next_actions"]) >= 3
    assert len(artifact["citations"]) >= 1

    # 4. citation 必须能解析回 KB
    cit = artifact["citations"][0]
    assert cit["chunk_id"].startswith("chk_")
    assert cit["document_id"] == "doc_88a277cf"
    # 行号匹配 KB
    chunk = sqlite.get_chunk(cit["chunk_id"])
    assert chunk.line_start == cit["line_start"]
    assert chunk.line_end == cit["line_end"]

    # 5. RAG 三件套
    assert eval_rag_recall_at_k(retrieval=result.retrieval, ground_truth=fixture["extensions"]["rag_ground_truth"]) == 1.0
    assert eval_rag_citation_validity(...) == 1.0
```

### 6.3 Schema 互一致性测试

```python
# tests/test_schemas.py — 跑全仓 examples/ 通过对应 schema
@pytest.mark.parametrize("path,schema_name", discover_examples())
def test_example_validates(path, schema_name):
    instance = load(path)
    schema = load_schema(schema_name)
    jsonschema.validate(instance, schema)
```

`discover_examples()` 扫描 `examples/` 下所有 .json/.yaml，按文件名约定推断 schema：
- `*meta*.yaml` → session.schema 或 kb-document.schema
- `*results*.jsonl` → eval-result.schema
- `chunks.jsonl` → kb-chunk.schema
- ...

### 6.4 跑测试的环境要求

- pytest fixture `ollama_running`：通过 `docker-compose up ollama` 启动并 health-check；CI 中跳过 golden 那层（标 `@pytest.mark.requires_ollama`）
- Linux 与 macOS 都跑前 3 层；golden 仅 Linux + Docker
- CI（GitHub Actions）：Ubuntu 22.04 + Docker + pre-pull `qwen2.5:14b-instruct` + `nomic-embed-text`

---

## 7. 依赖与 build / Build

### 7.1 `pyproject.toml`（关键段）

```toml
[project]
name = "opspilot"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "typer >= 0.12",
    "pydantic >= 2.7",
    "pyyaml >= 6.0",
    "jsonschema >= 4.22",
    "lancedb >= 0.7",
    "pyarrow >= 16",
    "httpx >= 0.27",
    "python-ulid >= 2.2",   # 用 python-ulid 而非 ulid-py（前者更活跃）
    "tiktoken >= 0.7",
    "rich >= 13",
]

[project.optional-dependencies]
dev = [
    "pytest >= 8",
    "pytest-cov",
    "pytest-asyncio",
    "ruff >= 0.5",
    "mypy >= 1.10",
    "types-pyyaml",
    "types-jsonschema",
]

[project.scripts]
opspilot = "opspilot.cli:app"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
python_version = "3.12"
strict = true
```

### 7.2 `Makefile`

```makefile
.PHONY: install dev test test-int golden lint validate harness clean ollama-pull

install:
	pip install -e ".[dev]"
	pre-commit install

ollama-pull:
	docker compose up -d ollama
	docker compose exec ollama ollama pull qwen2.5:14b-instruct
	docker compose exec ollama ollama pull nomic-embed-text

test:
	pytest tests/ -v -m "not slow and not requires_ollama"

test-int:
	pytest tests/ -v -m "not requires_ollama"

golden:
	pytest tests/golden/ -v -m "requires_ollama"

lint:
	ruff check src/ tests/
	mypy src/

validate:
	python -m opspilot validate examples/ --recursive

harness:
	python -m opspilot harness run \
	    --config examples/scn_ticket_summary_zh/harness/run-config.yaml \
	    --out /tmp/opspilot-harness/

clean:
	rm -rf ~/.opspilot/sessions/* ~/.opspilot/kb/*/lancedb/
	find . -name __pycache__ -exec rm -rf {} +
```

### 7.3 `docker-compose.yml`

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes:
      - ollama-data:/root/.ollama
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 10s

volumes:
  ollama-data:
```

### 7.4 `Dockerfile`（PR-8）

仅 PR-8 引入；Stage 1 主要在本机 venv 跑。

---

## 8. 增量交付计划 / Incremental delivery

8 个 PR，每个 ≤ ~600 行（含测试），每个有明确退出标准。

### PR-1 — Skeleton + schema tooling
- 建 `src/opspilot/{__init__,__main__,cli,config,errors,ids,timeutil,schemas}.py`
- `pyproject.toml` + `Makefile` + `.env.example` + `.python-version`
- `schemas.py`：加载所有 spec 目录下的 `*.schema.json`，提供 `validate(name, instance)`
- `cli.py`：仅 `init` 与 `validate` 子命令
- 测试：`tests/test_ids.py`、`tests/test_schemas.py`（参数化跑全仓 examples）
- **退出标准**：`make validate` 通过；`make test` 通过；`opspilot validate examples/` 全过

### PR-2 — Redaction + chunker
- `redaction.py`：实现 `redaction-rules.yaml` 中所有规则（regex + 占位符）
- `memory/chunker.py`：实现 `headings_then_size`
- 测试：`tests/test_redaction.py`（用样例 ticket 验证）；`tests/test_chunker.py`（chunker 输出与 `examples/scn_ticket_summary_zh/kb/chunks.jsonl` 字段相同）
- **退出标准**：chunker 跑 `sop_vpn_zh.md` 输出 3 个 chunk，line_start/line_end 与样例一致

### PR-3 — Ollama provider + docker-compose
- `providers/{base,ollama,registry,types}.py`
- `docker-compose.yml`
- `Makefile` 加 `ollama-pull`
- 测试：`tests/test_providers_ollama.py`（带 `requires_ollama` mark）
- **退出标准**：`make ollama-pull && pytest -m requires_ollama tests/test_providers_ollama.py` 通过；能 chat + embed

### PR-4 — Stores + retrieval
- `memory/{lance_store,sqlite_store,retrieval}.py`
- 应用 `memory/storage/sqlite-schema.sql` 建表
- 实现 hybrid search + RRF（k=60）
- 测试：`tests/test_sqlite_store.py`、`tests/test_lance_store.py`、`tests/test_retrieval.py`
- **退出标准**：把样例 `chunks.jsonl` 灌入两个 store；`kb_search("VPN 认证失败")` top-1 返回 `chk_0cf89826`

### PR-5 — Ingestion pipeline + `opspilot ingest`
- `memory/ingestion.py`：全流程（discover → redact → chunk → embed → upsert）
- CLI `ingest` 子命令
- 测试：跑 `examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md` → 与样例 `doc-meta.json` + `chunks.jsonl` 字段对齐
- **退出标准**：`opspilot ingest examples/.../sop_vpn_zh.md` 后 `kb_search` 仍命中样例 chunk

### PR-6 — Session manager + trace + artifact
- `session/{manager,trace,artifact,audit,types}.py`
- 测试：`tests/test_session.py`
- **退出标准**：能创建 session + 写 10 条 trace event（schema valid）+ 写 artifact + audit log；产出的 trace.jsonl 通过 `trace-event.schema.json`

### PR-7 — Orchestrator (ticket-summary playbook) + `opspilot run`
- `orchestrator/{ticket_summary,tools}.py`
- 新建 `playbooks/pb_ticket_summary_zh/prompt.md`
- CLI `run` 子命令
- 测试：用 mock provider（确定性返回）跑 unit；标 `requires_ollama` 的 integration 用真 Ollama
- **退出标准**：`opspilot run --playbook pb_ticket_summary_zh --input examples/.../inputs/ticket.json` 输出 artifact，artifact 通过 `ticket_summary_v1` schema_check

### PR-8 — Harness + 6 evaluators + golden test + Dockerfile
- `harness/{runner,reporter,types}.py` + 6 个 evaluator
- `Dockerfile`（多阶段构建：base + tests + runtime）
- `tests/golden/test_zh_e2e.py`
- **退出标准**：
  - `make harness` 跑通；results.jsonl 通过 `eval-result.schema.json`
  - `make golden` 通过：RAG recall=1.0、citation_validity=1.0、judge.llm ≥ 0.85、weighted ≥ 0.85

---

## 9. Stage 1 退出标准（修正版）/ Exit criteria

ARCHITECTURE.md §8 写的 "字节级一致" 修正为以下**结构等价**标准：

### 9.1 必达（all of）

- [ ] 所有 examples/ 实例通过对应 JSON schema 校验（`make validate`）
- [ ] `make test` + `make test-int` 全过（覆盖率 ≥ 70%）
- [ ] `make ollama-pull && make golden` 通过：
  - artifact 通过 `ticket_summary_v1` schema_check
  - `must_contain` 全命中（`authentication failed`、`多名用户`、`VPN 网关`）
  - `must_not_contain` 全不含（`[REDACTED:`、`T-XXXX 真实 ID`）
  - citation 行号与 KB chunk `line_start/line_end` 完全一致
  - `rag.recall_at_k` = 1.0（k=3）
  - `rag.precision_at_k` ≥ 0.5
  - `rag.citation_validity` = 1.0
  - `judge.llm` 评分 ≥ 0.85
  - 整体 `weighted_score` ≥ 0.85

### 9.2 软目标（best effort）

- 与 `examples/scn_ticket_summary_zh/session/artifacts/art_75fa2fb140c268a4.json` 的 `summary` 字段语义相似度 ≥ 0.80（embedding cosine）
- 端到端运行时间 ≤ 60s（本地 Ollama qwen2.5:14b）

### 9.3 不要求

- ❌ Bytes-exact 输出（不可达）
- ❌ artifact_id 与样例相同（hash 因内容微变会不同）
- ❌ 任何 wiki / skills / iteration / sandbox / 其他 5 provider 功能

---

## 10. Open questions（实施期回答）

- [ ] Ollama `format=json` 模式下的 token 输出稳定性——需在 PR-3 实测后决定是否加 JSON repair 层
- [ ] Chunker 在中文标题下的 token 计数——`tiktoken` 对中文不准；可能 PR-2 改为字符近似
- [ ] LanceDB 在 macOS 上的稳定性——若不稳定，golden 仅 Linux 跑；本地开发推 docker-compose
- [ ] FTS5 的中文 tokenizer：`unicode61` 在中文 KB 上召回低，可能 PR-4 加 ngram fallback
- [ ] `judge.llm` 在 Stage 1 用什么模型——同 Ollama 模型自评 vs 跳过？倾向：跳过 judge，Stage 1 仅跑 6 个非-judge evaluator
- [ ] Provider error 重试策略：默认 3 次指数退避还是直接失败 fast？倾向：fast-fail（dev 体验更好）

---

## 11. 与后续 Stage 的衔接 / Handoff to next stages

- **Stage 2** 加 skill 框架：复用 PR-3 的 ProviderProtocol；新增 `skills/` Python 模块；orchestrator 改为通用 runner（读 SKILL.md 而非 hardcode）
- **Stage 3** 加 wiki：复用 PR-4 的 stores；新增 `wiki/` Python 模块；ingest pipeline 在 PR-5 之上叠 wiki update
- **Stage 4** 加 iteration：复用 PR-8 的 harness runner；新增 `feedback/` 收集器；引入 lineage 文件维护

每个 PR 的代码必须**留扩展点**（不是过度设计；只是不卡死后续扩展）：
- `ProviderProtocol`：已为多 provider 留口
- `EvaluatorProtocol`：已为 7 类 evaluator 留口（Stage 1 实现 6 个）
- `SessionManager`：retention 字段已存，purge 实现留 Stage 4

---

## 12. 提交建议 / Commit suggestion

本文档作为 `IMPLEMENTATION_STAGE_1.md`，与 `ARCHITECTURE.md` 平级，**单独一个 commit**：

```bash
cd ~/Workspace/OpsPilot && \
git add IMPLEMENTATION_STAGE_1.md && \
git commit -m "docs: add Stage 1 implementation design

Translate ARCHITECTURE.md §8 Stage 1 into actionable design:
- Repo layout (src/opspilot/ Python package)
- Module boundaries with Protocol/typed signatures
  (providers / memory / session / orchestrator / harness)
- End-to-end call chain from CLI to artifact
- CLI command signatures with exit codes
- Config loading + secrets (.env)
- Testing strategy (unit / schema / integration / golden)
- 8-PR delivery plan, each ≤ 600 lines, with explicit exit criteria
- Stack: Python 3.12 + Typer + Pydantic + LanceDB + SQLite/FTS5 +
  httpx (Ollama) + jsonschema + pytest

Reflection on CLAUDE.md §1 (Think Before Coding):
ARCHITECTURE.md §8's 'bytes-exact output' exit criterion is
unreachable — LLMs aren't byte-stable even with seed locking.
Replaced with structural-equivalent: schema valid + RAG triplet
all pass + judge.llm ≥ 0.85.

Open questions called out in §10; to be resolved during PR-2..PR-8." && \
git push origin main
```

---

## 一句话收尾

**Stage 1 的全部价值 = 让 spec 真的能 build。** 8 个 PR，各 ≤ 600 行，每个 PR 的退出标准都是"跑得过 examples/ 的对应一段"。**第一行代码该写在 `src/opspilot/ids.py`——ULID 与 sha8 工具。**
