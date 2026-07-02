# OpsPilot Architecture — 开始开发前的整合视图

> **本文目的**：把 9 个 phase 累积的 spec 在一张图、6 条工作流、1 个能力矩阵里**一页讲完**。
> 适合作为"开始写脚本前的最后一份阅读材料"。所有细节回 7 个目录的 SPEC.md。

## TL;DR

OpsPilot = 7 个顶层目录组成的 **AI 代办闭环**：

- **Providers / Memory / Skills / Session / Sandbox / Harness / Wiki**

每个目录是一类 capability；6 条主线工作流把它们串起来；3 条反馈闭环让它"compounding"。

进开发之前的关键判断：
- 契约（schemas + templates）在 spec 阶段已收敛 → 当前最大风险**不是缺契约**，是首版实现选错"Stage 1 范围"导致难以收口
- 推荐 Stage 1 范围：**1 个 provider + 1 个 playbook + memory mid-term + session + harness 单 fixture**——能跑通"端到端 1 条工作流"即胜利，避免一上来就铺 6 条

---

## 1. 七目录鸟瞰 / 7-tier overview

```
                                 ┌─────────────────────────────────────┐
                                 │   playbooks/ + prompts/             │
                                 │   (人写的 SOP / 提示词；输入侧)       │
                                 └──────────┬──────────────────────────┘
                                            │
   ┌──────────────┐  model_ref      ┌───────▼────────┐  skill_ref     ┌──────────────┐
   │ providers/   │ ───────────────▶│   session/     │◀────────────── │  skills/     │
   │ 6 LLMs       │                 │   trace+audit  │                │ registry +   │
   │ Ollama/Open- │                 │                │                │ distill +    │
   │ Router/OAI/  │                 └───────┬────────┘                │ iteration +  │
   │ Anthropic/   │                         │                         │ tool/MCP     │
   │ Gemini/Grok  │              kb.search  │  artifact.write         │ bindings     │
   └──────────────┘                         │                         └──────────────┘
                                            ▼                                ▲
   ┌──────────────┐                ┌────────────────┐                        │
   │ memory/      │ ◀──── ingest ──│   sandbox/     │                        │
   │ 短/中/长期    │                │   隔离执行     │                        │
   │ trace+SQLite │                │   default deny │                        │
   │ +LanceDB+md  │                └────────────────┘                        │
   └──────┬───────┘                                                          │
          │ kb_document(kind=wiki_synthesis)                                  │
          ▼                                                                   │
   ┌──────────────┐                                                          │
   │  wiki/       │ ──── lint issues → feedback_signal(wiki_lint_issue) ─────┘
   │ 5 类 page    │                                                           │
   │ ingest +     │ ◀──── query→page (judge.llm ≥ 0.85) ──── session         │
   │ query→page + │
   │ lint         │                          ┌──────────────┐
   └──────────────┘                          │  harness/    │ ◀── runs against
                                             │ fixtures +   │     skills + sessions
                                             │ RAG evals +  │     + wiki
                                             │ regression   │
                                             │ gate         │
                                             └──────────────┘
                                                     │
                                                     ▼
                                          case-studies/  +
                                          memory.harvest →
                                          mid-term feedback signals
```

---

## 2. 功能架构 / Feature architecture

### 2.1 角色与职责

| 层 | 目录 | 一句话职责 | 核心 SPEC |
|---|---|---|---|
| 输入侧 | `playbooks/` `prompts/` | 人写的 SOP 与提示词（OpsPilot 的"使用说明"）| 已有 |
| 模型层 | `providers/` | LLM 抽象：endpoint / auth / capability / cost / retry | `providers/SPEC.md` |
| 知识层（被动）| `memory/` | 三层 memory：trace + SQLite/FTS5 + LanceDB；RAG | `memory/SPEC.md` |
| 知识层（主动）| `wiki/` | LLM 维护的累积合成；ingest / query→page / lint | `wiki/SPEC.md` |
| 任务层 | `session/` | trace + audit + artifact；合规打包 | `session/SPEC.md` |
| 执行层 | `sandbox/` | 隔离执行；default deny；多后端可选 | `sandbox/SPEC.md` |
| 能力层 | `skills/` | 注册 + 制作 + 蒸馏 + 迭代 + tool/MCP 绑定 | `skills/SPEC.md` + `ITERATION.md` |
| 质量层 | `harness/` | fixtures + 7 类 evaluator + 回归门 | `harness/SPEC.md` |
| 治理 | `governance/` | redaction / 保留 / 分级（cross-cutting）| 已有 |
| 案例 | `case-studies/` | 输出归档 | 已有 |
| 演示 | `demos/` `examples/` | 可运行 demo + 端到端契约样例 | examples 内 4 份 |

### 2.2 跨目录契约（核心 ID + 引用关系）

所有 ID 都是**内容寻址**（sha8）或**时间有序**（ULID）。

```
session(sess_<ULID>)
  │ model.provider_id ────────────▶ providers.registry.id
  │ trace.tool_call(action_id=act_<ULID>) ─▶ sandbox.action-request
  │ trace.tool_call(tool=kb.search) ──────▶ memory.kb.search
  │ trace.tool_call(tool=skill.invoke) ───▶ skills.registry.skill_ref
  │ trace.tool_result.artifact_ids ───────▶ session.artifacts/art_<sha8>.json
  │ user_action.accept + judge≥0.85 ──────▶ wiki.query→page candidate
  │ trace.user_action.* ──────────────────▶ skills.feedback_signal
  ▼
harness(run_<ULID>)
  │ fixture_id ────────────────────────────▶ harness.fixtures
  │ playbook_ref ──────────────────────────▶ playbooks/
  │ model_ref / judge_model_ref ───────────▶ providers.registry
  │ extensions.rag_ground_truth ───────────▶ memory.kb_chunks (chk_<sha8>)
  │ scores ────────────────────────────────▶ feedback_signal(harness_score)

memory.kb_document(doc_<sha8>)
  │ chunks (chk_<sha8>) ────────────────────▶ retrieval.response.results
  │ kind=wiki_synthesis (反向) ◀───────────── wiki page lifecycle=live

wiki.page(wpg_<sha8>)
  │ derived_from.sources[kind=kb_document].ref ─▶ memory.doc_id
  │ outbound_links[wpg_<sha8>] ─────────────────▶ wiki.page
  │ lint issue (lnt_<sha8>) ───▶ feedback_signal(wiki_lint_issue) ─▶ skills.iteration

skills.skill(<name>@<version>)
  │ requires.tools / .mcps ────────▶ tool-binding + mcp-config
  │ requires.providers (capability)▶ providers.capability matching
  │ tool-binding.kind=mcp ─────────▶ mcp-config.mcps[id]
  │ feedback_signal(fb_<ULID>) ────▶ iteration(itr_<ULID>) ─▶ variant(var_<sha8>)
  │ iteration.decision=promote ────▶ skills.lineage entry + new version
```

**禁用值（cross-cutting）**：所有 `version` / `model_ref` / `embedding_model` 字段都禁 `latest` / `auto` / `stable`。

### 2.3 能力矩阵 / Capability matrix

| 能力 / Capability | 主提供方 | 协作方 |
|---|---|---|
| LLM 调用 | providers | session（嵌 trace）|
| 工具调用（builtin） | session/sandbox | skills（声明 requires.tools）|
| 工具调用（MCP） | skills/mcp-config | session（透传到 trace）|
| 工具调用（sandbox shell/script） | sandbox | session + skills.tool-binding |
| 检索（RAG） | memory（kb.search）| session（tool_call） + wiki（ingest 阶段也用）|
| 知识 ingest（raw → KB） | memory.ingestion | governance（redaction） + providers（embedding）|
| 知识合成（KB → wiki page） | wiki.ingest | memory（KB 检索） + skills.wiki-maintainer |
| 评估 | harness | session.trace + memory（fixtures） |
| 蒸馏（traces / docs / skills → skill） | skills.distillation | session + memory + harness（trigger eval）|
| 迭代（feedback → variant → promote） | skills.iteration | harness（决策依据） + lineage |
| 持续维护（lint） | wiki.lint | skills.iteration（通过 wiki_lint_issue 信号）|
| 审计 / 合规 | session.audit + wiki.log | governance（policy）|
| 隔离 / 安全 | sandbox + skills.lifecycle-policy | governance |

---

## 3. 工作流架构 / Workflow architecture（6 条主线）

每条工作流 = 一个用户视角的 use case，跨多个目录。

### W1 · Source → Knowledge（摄入新源）

> **触发**：新 SOP / 工单导出 / wiki 文章被丢入仓库

```
raw doc (markdown)
  │
  ▼ memory.ingestion (redact → chunk → embed → upsert)
kb_document(doc_<sha8>) + chunks(chk_<sha8>) + LanceDB vectors
  │
  ▼ wiki.ingest-recipe (≤15 pages/source)
LLM 提议 page 变更 → static checks → review → apply
  │
  ▼ wiki page lifecycle 进 live
register back to memory KB as kind=wiki_synthesis
  │
  ▼
后续 kb.search 同时命中 raw chunks + wiki synthesis  (compounding)
```

主用：`memory/` + `wiki/` + `governance/`（redaction）。

### W2 · Task Execution（执行一个任务）

> **触发**：用户提交工单 / 跑 playbook / 调用 skill

```
playbook + user input
  │
  ▼ session.create (provider_id, sensitivity, retention_class)
session(sess_<ULID>) + meta.yaml + audit.log
  │
  ▼ LLM 调用：providers + 模型选择
prompt → response with tool_calls
  │
  ├── tool_call: kb.search → memory.retrieval → tool_result
  ├── tool_call: skill.invoke → skills registry → tool_binding 路由
  │     ├── kind=builtin → 内置实现
  │     ├── kind=mcp → mcp-config server
  │     └── kind=sandbox → sandbox.action-request → dry-run → [approval] → apply
  └── tool_call: artifact.write → artifacts/art_<sha8>.json
  │
  ▼ user_action.accept / reject / edit / pin_to_wiki
  │
  ▼ session.archive
└── 候选触发：
      ├── wiki.query→page-recipe (若 judge ≥ 0.85)
      ├── memory.harvest_to_mid_term (若用户 pin 或 accept)
      └── skills.feedback_collector (user_action.* 转 feedback_signal)
```

主用：`providers/` + `session/` + `memory/` + `sandbox/` + `skills/` + `wiki/`（命中 7 个目录的最长链路）。

### W3 · Quality Gate（评估与回归）

> **触发**：CI（PR 改动 prompt/playbook/skill） / 周期 cron / 模型升级

```
harness/run-config.yaml 选择：
  scenarios + fixtures + playbook + model matrix + evaluators
  │
  ▼ 对每个 (fixture × playbook × model) 跑一次 session
  │
  ▼ 7 类 evaluator 跑过（含 RAG 三件套：recall_at_k / precision_at_k / citation_validity）
  │
  ▼ results.jsonl
  │
  ├── 阈值通过 → CI green
  ├── 回归门触发 (regression_delta < -0.03) → CI block + emit feedback_signal(harness_score)
  └── 报告归档到 case-studies/
```

主用：`harness/` + `providers/`（matrix） + `memory/`（fixture ground_truth） + `skills/`（被测）+ `case-studies/`。

### W4 · Skill Creation（蒸馏新技能）

> **触发**：人工启动 / 周期 / 累积成功 session 触发

```
distillation-recipe (4 类来源之一):
  ├── from_traces: 自家 archived sessions（filter by harness score ≥ 0.85）
  ├── from_skills: 他人 skill 集合
  ├── from_docs:   playbooks/ / SOP markdown
  └── from_foreign: OpenAI GPT / LangChain agent（spec 阶段占位）
  │
  ▼ pipeline: discover → redact → mine → draft → review → register
  │
  ▼ SKILL.md draft + tool-binding.yaml draft + trigger-fixtures.jsonl
  │
  ▼ static checks (PII / prompt-injection / tool resolvable / trigger eval)
  │
  ▼ review (auto_then_human or human)
  │
  ▼ register as trust=distilled, lifecycle=draft
       (不允许直接 enabled；必须经 promotion / iteration)
```

主用：`skills/distillation` + `memory/` + `harness/`（trigger eval） + `governance/`。

### W5 · Skill Evolution（迭代演化）

> **触发**：feedback signals 累积 / harness 回归 / 模型升级 / scheduled

```
6 类 trigger 之一触发 iteration:
  ├── regression_detected (harness.score 掉点)
  ├── feedback_signal (累积权重 ≥ 5.0)
  ├── distillation_candidate (新 pattern)
  ├── model_upgrade
  ├── scheduled (cron)
  └── manual
  │
  ▼ propose: hypothesis + proposed_changes (≤2 字段/单次)
  │
  ▼ vary: 1..M variants (var_<sha8>)
  │
  ▼ harness × variants（baseline + variants 矩阵）
  │
  ▼ decision (全部通过晋升门才 winning):
        ├── no regression on anchor fixtures
        ├── delta_weighted ≥ 0.01
        ├── cost_pct ≤ 10%
        ├── trigger eval 仍达标 (recall ≥0.9, FP ≤0.05)
        └── static checks 全过
  │
  ▼ apply: registry update + lineage 加条目 + 30d rollback window
```

主用：`skills/iteration` + `harness/` + `skills/feedback-collector`。

### W6 · Wiki Maintenance（维护合成层）

> **触发**：每次 ingest 完成的增量 lint / 周期全量 lint / 收到 wiki_lint_issue feedback

```
lint-recipe 跑 10 类检查:
  contradiction / stale_claim / orphan / missing_concept_page /
  missing_cross_ref / duplicate_concept / broken_link / data_gap /
  redaction_warning / schema_invalid
  │
  ▼ 输出 issues (lnt_<sha8>) + candidate patches
       (绝不 auto apply！)
  │
  ▼ 每个 issue 转 feedback_signal(type=wiki_lint_issue)
       weight by severity (low=0.5 → critical=5.0)
  │
  ▼ 路由到 skills/wiki-maintainer skill
  │
  ▼ 进 W5 (Skill Evolution) 流程：
       wiki-maintainer 自身被迭代改进
       lint apply 走 ingest 流程 (不绕过 review)
```

主用：`wiki/lint` + `skills/iteration` + `skills/wiki-maintainer`。

---

## 4. 跨工作流的反馈闭环 / Feedback loops

OpsPilot 的"compounding"价值来自三条闭环：

```
循环 A (knowledge compounding):
  W2 session → user_action.accept + 高分 → W1' wiki.query→page → 回灌 KB
       └────── 之后所有 W2 的 kb.search 命中更丰富 ───────────────┘

循环 B (skill self-improvement):
  W2 session → user_action / harness score → feedback_signal → W5 iteration
       └─────── 同 skill 持续小步演进 ─────────────────────┘

循环 C (wiki self-care):
  W6 lint → wiki_lint_issue → W5 iteration on wiki-maintainer
       └─── wiki-maintainer 越用越懂如何维护此 wiki ────┘
```

这三条闭环是 OpsPilot 区别于"一次性 RAG"的核心——**每个用户操作都让系统略微变好**。

---

## 5. 数据生命周期与保留 / Data lifecycle & retention

| 数据 | 默认 retention | 保留位置 | 过期处理 |
|---|---|---|---|
| session.trace.jsonl | 30d (medium) | `sessions/<sess_id>/` | soft purge（留 meta + audit）|
| session.artifacts | 同 session | 同上 | 同上 |
| session.audit.log | 365d | 同上 | 单独保留 |
| memory.mid-term records | 默认无过期 | SQLite + markdown | valid_until 显式过期则只读 |
| memory.long-term KB | 长期 | LanceDB + markdown | markdown 入 git；LanceDB 可重建 |
| wiki.page (live) | 长期 | wiki/pages/ | git 历史 |
| wiki.lint issues | append-only | wiki/_lint/ | 不删除，只标 lifecycle_state |
| skills.feedback_signals | 365d 审计 / 60d 聚合 | skills/feedback/ | 60d 后只保留 audit |
| skills.lineage | 永久 | skills/lineage/ | append-only DAG |
| skills.variants (losing) | 90d after archive | skills/repo/<name>/variants/ | 自动归档 |
| harness.results | 长期 | harness-data/runs/ | 报告归档到 case-studies/ |

`.gitignore` 已确保：LanceDB 数据 / mid-term DB / sessions / .env 不入 git；markdown 源全部入 git。

---

## 6. 强约束清单 / Cross-cutting hard rules

实现期必须落实的红线（从 7 个 SPEC.md 抽取）：

### 6.1 安全 / Security
1. PII 不入向量库 / SQLite / 蒸馏 pipeline / wiki page —— 加载/写入前 hard-fail PII 检查
2. `restricted` classification 不入向量库；不允许被 query→page 自动回写
3. community/unknown trust skill：强制 sandbox + 禁所有 write 类工具
4. MCP secrets：`${ENV_VAR}` 占位；literal secret 加载时拒绝
5. prompt-injection 静态扫描：skill body / wiki page body / description / mcp config 加载时跑

### 6.2 可重算 / Determinism
6. ID 含义：`sess/run/itr/fb_<ULID>` 时间有序；`art/chk/doc/wpg/var/lnt_<sha8>` 内容寻址
7. ULID 字母表：禁 I/L/O/U（Crockford Base32）
8. 版本锁定：`model_ref` / `embedding_model` / `judge_model_ref` / skill `version` / wiki page `version` 全禁 `latest`/`auto`/`stable`
9. iteration decision 必须由数据决定（recipe + signals + run results 给定 → outcome 应可重算）
10. content_hash：file-level sha256（与 `harness/schemas/fixture.schema.json` Fix 2 后语义一致）

### 6.3 治理 / Governance
11. 时间戳一律 RFC3339 + UTC；编码一律 UTF-8（无 BOM）
12. lint 永远不 auto apply（wiki / iteration 都遵守）
13. 高危动作必走 approval gate（sandbox 高危关键词 / community skill / restricted page 修改）
14. 每个 trace event / wiki op / skill state change 都写入 audit
15. 跨工作流的 ID 引用必须能在校验脚本中 round-trip（见各 e2e 样例的 checks.md §F）

### 6.4 演进 / Evolution
16. iteration 单次最多改 2 字段；`description + requires.tools` 禁同改
17. variant 必须经 evaluation 才能 promote（不允许跳 evaluate 直接 promote）
18. wiki single-concept-per-page；duplicate 必报 lint
19. KB embedding 模型升级 = 全量重建 namespace（向量空间不可比）
20. iterate_again chain ≤ 3 次；超过自动转 manual_intervention

---

## 7. 端到端样例索引 / Existing e2e samples

已有 4 份契约自验证样例（实施期作为黄金标准对照）：

| 样例 | 验证什么 | 关键 ID |
|---|---|---|
| `examples/scn_ticket_summary_zh/` | 5 目录契约（session+memory+sandbox+harness+providers）i18n=zh | doc_88a277cf, art_75fa2fb140c268a4 |
| `examples/scn_ticket_summary_en/` | 同上 i18n=en；证明 spec 语言无关 | doc_afe80531, art_84cc55e02c54c4ce |
| `examples/itr_ticket_summary_zh_v1_3_0/` | iteration 全链路（feedback → propose → eval → promote）| itr_01K2B0BRYN8P8R5H2YJ7M9E7N0, var_9930d615 (winning) |
| （未做）`examples/wiki_ingest_zh/` | wiki ingest + query→page + lint 全链路 | TBD |

每份都有 `checks.md` 列出跨文件引用真值表与机器校验伪代码。**实现期的目标 = 让 Python CLI 跑出与样例完全一致的输出**。

---

## 8. 实现优先级建议 / Build-order recommendation

不要一上来就铺 7 个目录。按"最小闭环"分阶段：

### Stage 1 — 单条工作流端到端（1-2 周）

**目标**：跑通 `examples/scn_ticket_summary_zh/`，输出与样例完全一致。

- **必做**：
  - providers/ 接 1 个：Ollama 本地（无 API key 风险）
  - memory/long-term：LanceDB + SQLite/FTS5 + 1 份 KB 文档（用样例的 sop_vpn_zh.md）
  - session/：trace + audit + artifact 文件读写
  - 1 个 playbook：`pb_ticket_summary_zh@1.2.0`（裸 prompt，不走 skills 框架）
  - harness/：跑 1 个 fixture 出 results.jsonl
- **跳过**：
  - sandbox / skills / wiki / iteration / 其他 5 个 provider
- **退出标准**：CLI `opspilot run --playbook pb_ticket_summary_zh --ticket sample.json` 输出与 `examples/scn_ticket_summary_zh/session/artifacts/art_75fa2fb140c268a4.json` 字节级一致（除 ts 字段）

### Stage 2 — 闭合"质量门" + 引入 skill（1-2 周）

**目标**：用 skill 框架跑 Stage 1 同一个 playbook + harness regression gate。

- 加 skills/registry + 1 个 SKILL.md (`ticket_summary_zh@1.2.0`)
- 加 sandbox L1（docker default）但**只用于 read-only kb.search**
- harness：CI 跑 fixture，回归门接 GitHub Actions
- 第二个 provider：Anthropic Claude（验证 model_ref 切换）
- 退出标准：`make harness` 跑通 + zh 与 en 两份 fixture 都过

### Stage 3 — 引入 compounding 能力（2-3 周）

**目标**：让系统**累积**——session 高分回答能进 wiki，新查询命中合成。

- wiki/：实现 ingest 与 query→page（lint 留到 Stage 4）
- memory.harvest_to_mid_term
- skills.distillation from_traces（传入 archived sessions → 产 skill draft）
- 退出标准：跑 5 个 session 后，第 6 个 session 的 kb.search 命中至少 1 个 wiki page

### Stage 4 — 自我改进（2-4 周）

**目标**：feedback signals 真的能驱动 skill 与 wiki 进化。

- skills.iteration（跑通 `examples/itr_ticket_summary_zh_v1_3_0/` 一致输出）
- wiki.lint + wiki_lint_issue → iteration 路由
- skills.feedback-collector 全 7 类 signal
- 退出标准：能产出一份 lineage.yaml，至少 1 个 promoted iteration

### Stage 5 — 接生产（视需求）

- 剩余 4 个 provider（OpenRouter / OpenAI / Gemini / Grok）
- sandbox L2/L3（gVisor / Firecracker / Remote VM）
- MCP 集成（fs-readonly / git-readonly / Notion 等）
- query→page 自动化策略落地

---

## 9. 用什么栈？/ Tech stack（推荐）

```
runtime              : Python 3.12（或 Go，但 Python 生态更熟，与 LLM SDK 一致）
LLM provider SDKs    : litellm（统一抽象） 或 直接 Anthropic SDK + Ollama HTTP
vector DB            : LanceDB
keyword/meta DB      : SQLite + FTS5
schema validation    : jsonschema
orchestration        : Python asyncio（不引入 langchain/langgraph，过重）
sandbox              : Docker SDK for Python (L1)；L2+ 留 stub
MCP client           : mcp Python SDK（官方）
CLI                  : Typer / Click
testing              : pytest + jsonschema-based fixture
container            : docker-compose（dev）→ k8s（生产时再说）
```

避免：langchain（抽象太重）、autogen（与本架构冲突）、自建 agent runner（用 spec 直接驱动）。

---

## 10. 提交建议 / Commit suggestion

本文档作为新的根级文档，建议作为**第 5 个 commit**追加（在前面 4 个 commit 之后）：

```bash
# 在你跑完前面 4 个 commit 之后：
cd ~/Workspace/OpsPilot && \
git add ARCHITECTURE.md && \
git commit -m "docs: add ARCHITECTURE.md as build-time integration view

Single-page integration of 7-tier spec for the implementation phase:
- 7 directories' roles + cross-cutting contracts
- 6 main workflows (Source→Knowledge / Task / QA / Skill creation /
  Skill evolution / Wiki maintenance)
- 3 feedback loops (the 'compounding' value)
- 20 cross-cutting hard rules pulled from SPECs
- 5-stage build-order recommendation (start with Ollama + memory +
  session + 1 playbook + harness; expand outward)
- Recommended stack: Python 3.12 + litellm + LanceDB + SQLite/FTS5
  + Docker SDK + Typer

This is intended as the last reading material before writing code." && \
git push origin main
```

---

## 附：术语速查 / Glossary

| 术语 | 定义 |
|---|---|
| `model_ref` | `<provider_id>/<name>@<version>`，禁 latest |
| `kb_document` | memory.long-term 的一份 raw 或 wiki_synthesis 文档 |
| `chunk` | kb_document 的分块；既存 SQLite 元数据，也存 LanceDB 向量 |
| `session` | 一次 AI 任务的完整打包（trace + artifacts + audit）|
| `trace event` | session.jsonl 的一行；7 类（prompt/response/tool_call/tool_result/redaction/user_action/system）|
| `artifact` | session 内产物文件，文件名 = `art_<sha256[:16]>.<ext>` |
| `skill` | 可重用的"做某类活"的 SKILL.md 包；触发由 description 决定 |
| `variant` | skill 的候选版本（still in iteration），var_<sha8> |
| `iteration` | 一次完整的"改一版 skill"流程，itr_<ULID> |
| `feedback_signal` | 7 类来源信号；累积权重触发 iteration |
| `wiki page` | LLM 维护的合成 markdown，5 类 kind，wpg_<sha8> |
| `lint issue` | wiki 健康检查输出，10 类，lnt_<sha8>，**不自动 apply** |
| `redaction` | PII / 内部代号 / 密钥脱敏；所有入库前置 |
| `trust tier` | skill 信任 5 级；决定调用权限矩阵 |
| `lifecycle_state` | session/skill/page/variant 的状态机 |
| `harness fixture` | 评估输入快照（必脱敏）；含 rag_ground_truth |
| `rag.recall_at_k` / `precision_at_k` / `citation_validity` | RAG 三件套 evaluator |

---

## 一句话收尾

**Spec 阶段已完成，下一步是把 Stage 1 的"一条端到端工作流"跑通——目标是和 `examples/scn_ticket_summary_zh/` 的样例数据字节级一致。** 这是从 spec 到实现的"自我验证"。
