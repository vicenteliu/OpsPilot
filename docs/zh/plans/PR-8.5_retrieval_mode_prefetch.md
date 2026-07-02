# PR-8.5 — `retrieval_mode: prefetch`：让弱 tool-call 模型也能跑通 ticket_summary

> **Status**: draft (awaiting review)
> **Tracker**: Issue B (gemma4:e4b 在 `make golden` 中从不调用 `kb_search` → 5/6 evaluator 归零)
> **Scope**: orchestrator + playbook spec + prompt 模板 + 1 个新增单测；不动 harness、不动 schemas/、不动 PR-1..PR-8 的退出契约
> **Estimated**: 1 commit / ≈ 200 LoC / ≤ 3h

---

## 1. 背景 & 问题

PR-8 收尾时在主机用真 Ollama (gemma4:e4b) 跑 `make golden`，结果：

| Evaluator | Score | 失败原因 |
|---|---|---|
| schema_check | 0.000 | `citations: [] should be non-empty`（业务 schema 拒绝空 citations） |
| must_contain | 0.667 | 缺关键词 `多名用户` |
| must_not_contain | 1.000 | — |
| rag.recall_at_k | 0.000 | `retrieved=[]` |
| rag.precision_at_k | 0.000 | `retrieved=[]` |
| rag.citation_validity | 0.000 | `artifact has no citations` |
| **weighted_score** | **0.233** | exit 2 |

trace.jsonl 显示：模型直接出最终 JSON，**一次 `kb_search` 都没调**。

**根因**：gemma4:e4b 这一档参数量的开源模型对 OpenAI-tools 协议（OpenAI tools / function-calling）的训练强度不够，往往无视 system prompt 里的 "调用 `kb_search`" 指令，直接进入终态。

## 2. 设计目标

1. **不放弃小模型**：保持 OpsPilot "本地小模型也能跑" 的产品定位（关键路径不依赖 14B+）。
2. **保留 tool-call 模式的兼容性**：强模型（GPT-4 / Claude / qwen3-72b）继续可以用 ReAct 风格自主检索。
3. **harness 评估口径不变**：`rag.recall_at_k` / `rag.precision_at_k` / `rag.citation_validity` 三件套继续基于同一份 trace.jsonl + artifact.citations 计算，无需打补丁。

## 3. 三选一回顾（之前提过）

| 路径 | 工作量 | 风险 | 选择？ |
|---|---|---|---|
| A 提示词加压 | 0.5h | 高（gemma4 训练就弱） | × |
| **B RAG-style prefetch（本提案）** | 2-3h | 低 | **√** |
| C 换强模型 | 0.5h | 低 | 与 B 不互斥，但牺牲产品定位，留作 escape hatch |

## 4. 设计：`retrieval.mode = tool | prefetch`

### 4.1 Playbook spec 改动 (`playbook.yaml`)

```yaml
# 新增 retrieval 块（向后兼容：缺省为 tool 即现状）
retrieval:
  mode: prefetch          # tool | prefetch
  prefetch:
    top_k: 5              # 缺省取 limits.max_kb_search_results
    query_fields:         # 从 ticket 哪些字段拼 query
      - subject
      - body
```

向 `PlaybookSpec` 加：

```python
@dataclass(frozen=True)
class PlaybookRetrievalPrefetch:
    top_k: int | None = None              # None = fall back to limits
    query_fields: list[str] = field(default_factory=lambda: ["subject", "body"])

@dataclass(frozen=True)
class PlaybookRetrieval:
    mode: Literal["tool", "prefetch"] = "tool"
    prefetch: PlaybookRetrievalPrefetch = field(default_factory=PlaybookRetrievalPrefetch)
```

`load_playbook` 解析时填默认值，老 playbook（没有 retrieval 块）自动得到 `mode=tool`。

### 4.2 Orchestrator 主流程改动 (`orchestrator/ticket_summary.py`)

```
当前流程：
    create session → write prompts → chat loop {tool_call → tool_result} → parse JSON → validate

改造后：
    create session → write prompts
    if pb.retrieval.mode == "prefetch":
        query = "\n".join(ticket[f] for f in pb.retrieval.prefetch.query_fields)
        hits  = kb_search(query, top_k=…)
        write trace tool_call(actor="system", tool="kb_search", args={query, top_k}, action_id=None)
        write trace tool_result(actor="tool:kb", tool="kb_search", status="ok", stdout_ref=rendered)
        system_prompt = pb.system_prompt + "\n\n## 已预检索 KB\n\n" + render_hits(hits)
                                          + "\n\n请直接基于以上 chunks 引用，**不要调用任何工具**。"
        tools_for_chat = []
        max_turns = 1
    else:
        system_prompt = pb.system_prompt
        tools_for_chat = [tool_def]
        max_turns = pb.limits.max_turns

    chat loop（共用）→ parse JSON → validate
```

关键点：

- **prefetch 模式仍写 `tool_call` + `tool_result` 两条 trace 事件**，使得 `harness/runner.py::_retrieved_chunks()` 不需任何改动就能从 trace.jsonl 收齐 chunk_ids（recall/precision evaluator 自动续命）。
- **render_hits()** 把 `chunk_id / source_path / line_start / line_end / heading_path / content` 全部摊平到 system prompt，这样 model 能直接 copy chunk_id 进 `citations[]`。
- **prefetch 路径仍受 redactor 保护**（输入 ticket 已脱敏；KB chunks 走 ingestion 时也已 redact 过，无新增泄密面）。

### 4.3 Prompt 调整 (`playbooks/pb_ticket_summary_zh/prompt.md`)

不新建文件、不分支 prompt——orchestrator 在 prefetch 模式下**追加**一个 prefetch addendum，prompt.md 主体保持不动（仍兼容 tool 模式）。

prompt.md 改一处：步骤 2 "**检索 KB**" 旁加一行："*若 system 已附 KB chunks，则跳过此步，直接引用。*"

### 4.4 Playbook 版本 bump

`pb_ticket_summary_zh`: **1.2.0 → 1.3.0**，唯一 spec 改动 = 加 `retrieval.mode: prefetch` 块。
保留 escape hatch：用户可在自己的 playbook 里改回 `mode: tool`。

## 5. 不改的东西（surgical change）

- `harness/` 整个目录不动（`_retrieved_chunks` / `_build_kb_lookup` 复用）
- `schemas/` 不动（trace-event / eval-result / ticket_summary_v1 都已支持现有字段）
- `providers/` 不动（chat tools=[] 已支持）
- `memory/retrieval.py::kb_search()` 不动（直接调函数，跟 tool handler 走同一条路径）
- exit-code 契约不动（0 pass / 2 weighted / 3 schema invalid / 1 error）

## 6. 测试策略

### 6.1 单元测试（`tests/test_orchestrator.py` 新增 2 例）

- `test_run_ticket_summary_prefetch_happy_path`：
  - playbook fixture 配 `retrieval.mode=prefetch`
  - 模拟 provider：单次 chat 直接返回 schema-valid JSON（含 1 条 citation 引用 prefetch 拿到的 chunk_id）
  - 断言 trace.jsonl 含一条 `tool_call(actor=system, tool=kb_search)` + `tool_result(status=ok)`
  - 断言 `RunResult.schema_valid is True` + artifact 落盘
- `test_run_ticket_summary_prefetch_query_fallback`：
  - ticket 缺 body 字段时 query 回退到 subject only
  - 断言不抛异常 + tool_result 仍写入

### 6.2 现有测试不退回

- `tests/test_orchestrator.py` 现 12 例（tool 模式）全保留
- `tests/test_harness.py` 19 例不变（runner 入口不改）
- 全 `make ci` 期望仍 302+ green

### 6.3 主机真 Ollama 验证（人工）

`make golden` 期望从 `weighted=0.233 / exit 2` → `weighted ≥ 0.85 / exit 0`。
若 still fail，trace.jsonl 第一条 tool_result 已含完整 chunks，可直接定位是 prompt 解析问题还是 model 行为问题。

## 7. 验收标准（exit gate）

- [ ] `make ci` 全绿（lint + typecheck + 304+ tests + validate）
- [ ] `pb_ticket_summary_zh@1.3.0` playbook.yaml 含 `retrieval.mode: prefetch` 且 schema 验证通过
- [ ] `tests/test_orchestrator.py` 新增 2 例 prefetch 用例，旧 12 例不回归
- [ ] 主机 `make golden` 在 gemma4:e4b 下 `weighted_score ≥ 0.85`
  - 若 < 0.85 但 ≥ 0.6（部分 evaluator pass），允许下钻细节后单独修
- [ ] commit 控制在 `playbook.yaml + prompt.md + 3 个 .py 文件 + 1 个 test 文件`，diff ≤ 250 行

## 8. 决策点（请你拍板）

| # | 议题 | 选项 | 默认建议 |
|---|---|---|---|
| **D1** | 默认值 | 老 playbook 没写 `retrieval` 块时，回退到 `tool` 还是 `prefetch`？ | **tool**（向后兼容；新 playbook 显式写 prefetch） |
| **D2** | 1.2.0 是否保留 | 删 / 保留作为 reference | **bump 到 1.3.0**（不保留 1.2.0 文件，git history 即可） |
| **D3** | prompt 拼接位置 | system 前 / system 后 | **system 后**（system_prompt + chunks，让 system 指令优先） |
| **D4** | 渲染格式 | YAML / JSON / Markdown | **Markdown**（带 `### chunk_id: chk_xxx` 三级标题，最贴近 model 训练分布） |
| **D5** | hits 命中数 | 取 `limits.max_kb_search_results` 还是新独立字段 | **复用 limits.max_kb_search_results**（避免 spec 增重） |
| **D6** | 失败 fallback | prefetch 0 hit 时是否切回 tool 模式 | **不切**（写空 chunks 列表 + warning trace 事件，让 model 自行 graceful degrade）|
| **D7** | trace actor | tool_call 用 `system` / `system:prefetch` / `model:assistant` | **system**（已是合法字符串，无需动 schema 描述） |
| **D8** | en playbook | 是否同步 `pb_ticket_summary_en` | **不在本 PR 做**（en 还未建 playbook；PR-9 时一并加） |
| **D9** | iteration 例 | `examples/itr_ticket_summary_zh_v1_3_0` 是否更新 | **更新 lineage 元数据**（指向 1.3.0），不改 fixture/golden |

## 9. 实施步骤（提议执行顺序）

1. `orchestrator/types.py` — 加 `PlaybookRetrieval{Prefetch}` + `load_playbook` 解析新块
2. `orchestrator/ticket_summary.py` — 抽 `_run_prefetch(...)` helper，主流程分支
3. `playbooks/pb_ticket_summary_zh/playbook.yaml` — bump 1.2.0 → 1.3.0 + 加 retrieval 块
4. `playbooks/pb_ticket_summary_zh/prompt.md` — 步骤 2 加一句 "若 system 已附 chunks 则跳过"
5. `tests/test_orchestrator.py` — 加 2 例 prefetch 测试
6. `make ci` 全绿 → 主机 `make golden` 验证
7. commit `feat(orchestrator): retrieval_mode=prefetch (PR-8.5; closes Issue B)`

## 10. 已识别风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| prefetch query 命中错 chunk（subject + body 拼出来太宽） | 中 | recall@k=0 | D6 写 warning + 后续可加 LLM-rerank |
| chunks 内容塞爆 ctx window | 低 | model 失败 / 截断 | top_k=5 × 平均 ~300 tokens ≈ 1.5k；gemma4:e4b 8k ctx 安全 |
| 模型仍不照 chunks 引用，编造 chunk_id | 中 | citation_validity=0 | citation_validity evaluator 已查 KB lookup，会捕获 |
| 强模型场景 prefetch 反成枷锁（限制了多轮思考） | 低 | weighted 略降 | mode=tool 仍可用，强模型显式选 tool |

---

**待你 review 并对 D1-D9 拍板，我就开工。** 首选默认全采纳即可。
