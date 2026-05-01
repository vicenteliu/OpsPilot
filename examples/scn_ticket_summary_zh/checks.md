# 契约自检清单 / Contract Self-validation Checklist

> 这份清单把样例里的**每个跨文件引用**都标了出来，配合 schema 行号便于评审。
> 任意一行对不上 = spec 还没真正闭合，需要修订 schema 或 template。

## A. ID 一致性 / Cross-file ID equality

| ID | 出现处 1 | 出现处 2 | 出现处 3 |
|---|---|---|---|
| `sess_01J0Z9ZQXK7M6P3F0XK5K7C5K0` | `session/meta.yaml#id` | `session/trace.jsonl[*].session_id` | `session/audit.log#col4` |
| `doc_88a277cf` | `kb/sop_vpn_zh.md#frontmatter.id` | `kb/doc-meta.json#id` | `kb/chunks.jsonl[*].document_id` + `retrieval/response.json#results[*].document_id` + `harness/fixture.json#extensions.rag_ground_truth.must_retrieve_doc_ids` + `session/artifacts/art_75fa2fb140c268a4.json#citations[0].document_id` |
| `chk_0cf89826` | `kb/chunks.jsonl[1].id` | `retrieval/response.json#results[0].chunk_id` | `harness/fixture.json#extensions.rag_ground_truth.must_retrieve_chunk_ids[0]` + `session/artifacts/art_75fa2fb140c268a4.json#citations[0].chunk_id` + `harness/results.jsonl#evaluators[ev_rag_*].details.*chunk_ids*` |
| `chk_ea5a0261` | `kb/chunks.jsonl[0].id` | `retrieval/response.json#results[1].chunk_id` | `harness/fixture.json#extensions.rag_ground_truth.should_retrieve_chunk_ids[0]` |
| `chk_0f674194` | `kb/chunks.jsonl[2].id` | `retrieval/response.json#results[2].chunk_id` | (no ground-truth ref) |
| `art_75fa2fb140c268a4` | `session/artifacts/art_75fa2fb140c268a4.json` (canonical 文件名) | `session/artifacts/art_75fa2fb140c268a4.meta.yaml#artifact_id` | `session/trace.jsonl[seq=7].artifact_ids[0]` + `session/audit.log` + `harness/results.jsonl#output.artifact_id` |
| `act_01J0Z9ZQXK7M6P3F0XK5K7C5KA` | `session/trace.jsonl[seq=3].action_id` | `session/trace.jsonl[seq=4].action_id` | `session/audit.log` |
| `act_01J0Z9ZQXK7M6P3F0XK5K7C5KB` | `session/trace.jsonl[seq=6].action_id` | `session/trace.jsonl[seq=7].action_id` + `session/artifacts/art_75fa2fb140c268a4.meta.yaml#produced_by.action_id` | `session/audit.log` |
| `fix_a1b2c3d4` | `harness/fixture.json#id` | `harness/golden.json#fixture_id` | `harness/results.jsonl#fixture_id` + `session/meta.yaml#labels.fixture_id` |
| `run_01J0Z9ZQXK7M6P3F0XK5K7C5RR` | `harness/run-config.yaml#run.id` | `harness/results.jsonl#run_id` | — |
| `q_01J0Z9ZQXK7M6P3F0XK5K7C5K1` | `retrieval/response.json#query_id` | (`kb.search` 内部生成) | — |

## B. 跨目录 schema 引用 / Cross-directory schema references

| 实例文件 | 必须满足的 schema | 关键校验点 |
|---|---|---|
| `kb/doc-meta.json` | `memory/schemas/kb-document.schema.json` | required: id/source_path/title/classification/content_hash/ingested_at/language/namespace/chunk_strategy/embedding_model/embedding_dim/redaction_passed |
| `kb/chunks.jsonl[*]` | `memory/schemas/kb-chunk.schema.json` | required: id/document_id/seq/content_hash/char_*/line_*/embedding_model/vector_id；content 与 content_artifact_id 互斥；line_end ≥ line_start ✓ |
| `retrieval/request.json` | `memory/schemas/retrieval-query.schema.json#oneOf[0]` | kind=request；scopes 至少 1 项；mode=hybrid 时 hybrid 段必填 |
| `retrieval/response.json` | `memory/schemas/retrieval-query.schema.json#oneOf[1]` | kind=response；results[].score ∈ [0,1]；citation 必填（return_citations=true 时）|
| `session/meta.yaml` | `session/schemas/session.schema.json` | model.provider_id 必须在 registry；model.version 不为 latest/auto/stable ✓ |
| `session/trace.jsonl[*]` | `session/schemas/trace-event.schema.json` | type→属性 oneOf 分支；type=tool_call.action_id 命名空间 act_<ULID> ✓ |
| `session/artifacts/art_75fa2fb140c268a4.json` | `harness/golden.json#schema_check` (ticket_summary_v1) | required_keys 全有；scope ∈ enum；next_actions ≥3；citations ≥1；severity 匹配 ^P[0-4]$ |
| `harness/fixture.json` | `harness/schemas/fixture.schema.json` | redacted=true；scenario_id pattern；source.type ∈ enum |
| `harness/results.jsonl` | `harness/schemas/eval-result.schema.json` | run_id/fixture_id/playbook_ref/model_ref；evaluators ≥1；scores.weighted ∈ [0,1]；judge_model_ref 锁版本 |

## C. RAG 三件套自检 / RAG evaluator triplet

| Evaluator | 输入引用 | 计算 | 结果 |
|---|---|---|---|
| `ev_rag_recall_at_k`（k=3）| ground_truth = `harness/fixture.json#extensions.rag_ground_truth.must_retrieve_doc_ids` = `["doc_88a277cf"]`<br>retrieved top-3 doc_ids = `retrieval/response.json#results[0..2].document_id` = `["doc_88a277cf"]`×3 | matched / expected = 1/1 | **1.0 ✓** |
| `ev_rag_precision_at_k`（k=3）| relevant = must + should = `["chk_0cf89826", "chk_ea5a0261"]`<br>retrieved top-3 chunks = `[chk_0cf89826, chk_ea5a0261, chk_0f674194]` | 命中 2/3 | **0.667 ✓**（无下限阈值，pass）|
| `ev_rag_citation_validity` | 摘要 citations[0] → chunk_id `chk_0cf89826`, line 37–46 ↔ `kb/chunks.jsonl#chk_0cf89826.line_start=37/line_end=46` | 1/1 valid | **1.0 ✓** |

## D. 端到端数据流验证 / End-to-end flow

```
fixture.json#input
    │ (与 session/inputs/ticket.json 字段相同)
    ▼
session/meta.yaml#playbook + model_ref
    │ (model_ref → providers/templates/anthropic.config.template.yaml)
    ▼
trace.jsonl[seq=3] tool_call kb.search args
    │ (与 retrieval/request.json 字段相同)
    ▼
retrieval/response.json#results[0..2]
    │ (chunk_id ∈ kb/chunks.jsonl[*].id)
    │ (citation.line_start/end == kb/chunks.jsonl[*].line_start/end)
    ▼
trace.jsonl[seq=5] response (NL summary with [^kb-1] footnote)
    │ + trace.jsonl[seq=6,7] artifact.write
    ▼
session/artifacts/art_75fa2fb140c268a4.json
    │ (citations[0].chunk_id == retrieval response 命中)
    │ (citations[0].line_start/end == kb/chunks.jsonl#chk_0cf89826.line_start/end)
    ▼
harness/run-config.yaml + fixture/golden/rubric
    │
    ▼
harness/results.jsonl (8 evaluators, weighted=0.968, pass=true)
    │
    ▼
case-studies/e2e-samples/ (报告归档目标)
```

## E. 已知"沙箱遗留"清理项 / Sandbox leftovers to tidy

样例创建过程中沙箱不能 `unlink` 共享挂载下的文件，留下了几个开发期副本。提交后请在 host 删除：

```bash
cd ~/Workspace/OpsPilot/examples/scn_ticket_summary_zh/session/artifacts && \
rm -f summary.structured.json \
      art_d3bf317bf67a4293.json art_d3bf317bf67a4293.meta.yaml \
      art_56d3a0e44dd6d022.json art_56d3a0e44dd6d022.meta.yaml
```

只保留 canonical：
- `art_75fa2fb140c268a4.json`
- `art_75fa2fb140c268a4.meta.yaml`

> 历史背景：Fix 1（合规审计）重算了 zh 样例的 doc_id 与 artifact 哈希，artifact 改名 d3bf...→56d3...→75fa...。沙箱 FUSE 不能 unlink，所以这几次 rename 的副本都需要在 host 清理。

## F. 校验脚本（可机器跑）/ Machine-runnable checks

> spec 阶段不附运行实现；以下伪代码记录"实现期需要做的检查"。

```python
# 1. 所有 ID 用法集合相等
assert ids_in("session/trace.jsonl") ⊇ ids_in("session/audit.log")
assert chunk_ids_in("retrieval/response.json") ⊆ chunk_ids_in("kb/chunks.jsonl")
assert artifact_id_in("trace.jsonl") == filename_stem_of("session/artifacts/art_*.json") == sidecar.artifact_id

# 2. 每个 schema 引用都能解析
for f, schema in mapping.items():
    jsonschema.validate(load(f), load(schema))

# 3. citation 行号匹配
for cit in artifact.citations:
    chunk = chunks_by_id[cit.chunk_id]
    assert chunk.line_start == cit.line_start
    assert chunk.line_end   == cit.line_end
    assert chunk.document.source_path == cit.source_path

# 4. RAG evaluator 输入到输出的可重算性
recall = recompute_recall_at_k(fixture.ground_truth, response.top_k_docs)
assert isclose(recall, results.evaluators["ev_rag_recall_at_k"].score)

# 5. 模型引用锁版本
assert not any(ref.endswith(("@latest", "@auto", "@stable"))
               for ref in collect_model_refs())
```
