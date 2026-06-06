# 端到端样例：`scn_ticket_summary_zh`

> **作用 / Purpose**：把 `providers/` `memory/` `session/` `sandbox/` `harness/` 五个目录的契约**真的串起来**——一个完整的"工单摘要 + RAG 检索 + 评估"链路。
> 所有文件都是**真实示例数据**（不是模板），用于验证 schema 之间的字段引用是否闭合。

## 故事线 / Story

1. 用户在 service-desk 提交了一张工单（`session/inputs/ticket.json`）：**多名同事 VPN 认证失败**，附 vpn-client.log 片段
2. OpsPilot 创建 Session（`session/meta.yaml`），引用 playbook `pb_ticket_summary_zh@1.2.0`
3. 模型经 `kb.search` 工具调用，从 KB（`kb/sop_vpn_zh.md`）检索到"VPN 故障排查 / 认证错误"段（`retrieval/response.json`）
4. 模型生成结构化摘要（`session/artifacts/summary.structured.json`），含可追溯到 `source_path:line_range` 的 citation
5. Harness 跑评估（`harness/run-config.yaml` → `harness/results.jsonl`），含 3 类 RAG 评估器：`rag.recall_at_k` / `rag.precision_at_k` / `rag.citation_validity`，外加 `rule.json_schema` / `judge.llm`

## 数据流 / Data flow

```
[providers/]                     [memory/]
   provider-registry             KB (kb/sop_vpn_zh.md)
   anthropic-claude               │
       │                          │ ingestion (one-time)
       │ model_ref                ▼
       │                       chunks (kb/chunks.jsonl)
       │                       LanceDB(向量) + SQLite(meta+FTS)
       ▼                          │
   ┌────────────────────────────────────────────────┐
   │  session/meta.yaml                              │
   │  ┌──────────────────────────────────────────┐  │
   │  │ trace.jsonl                               │  │
   │  │  1. system: state_change → active         │  │
   │  │  2. prompt: system 指令                    │  │
   │  │  3. prompt: user 工单                      │  │
   │  │  4. tool_call: kb.search ──────────────▶  │  │ retrieval/request.json
   │  │  5. tool_result: chunks ◀──────────────   │  │ retrieval/response.json
   │  │  6. response: NL 摘要 + footnote          │  │
   │  │  7. tool_call: artifact.write ─────────▶  │  │ artifacts/art_d8135d82e59e9ad5.json
   │  │  8. tool_result: artifact written         │  │
   │  │  9. user_action: accept                   │  │
   │  │  10. system: state_change → archived      │  │
   │  └──────────────────────────────────────────┘  │
   └────────────────────────────────────────────────┘
                          │
                          ▼
              [harness/]
              run-config.yaml
                  │
                  ▼
              fixture.json (含 ground truth doc_ids)
                  +
              golden.json
                  +
              rubric.md
                  ↓
              evaluators 跑过：
                rule.json_schema       (结构合格)
                rule.pii_check         (无 PII 残留)
                rag.recall_at_k        (召回正确 doc_id)
                rag.precision_at_k     (chunk 相关性)
                rag.citation_validity  (citation 可定位)
                judge.llm              (LLM 评分)
                  ↓
              results.jsonl
```

## 这个样例**不**演示什么 / What this sample omits

- **sandbox 隔离执行**：ticket 摘要场景不需要执行命令；为保持端到端最小闭环，本样例无 sandbox action（如需，参考 `sandbox/templates/action-request.template.yaml`）
- **mid-term memory 收割**：不演示 session 归档后写入中期 memory 的过程（参考 `memory/templates/short-term-config.template.yaml#harvest_to_mid_term`）
- **多 provider 矩阵**：仅用一个 provider 跑（anthropic-claude）；harness 矩阵评估见 `harness/templates/eval-config.template.yaml`

## 阅读顺序 / Reading order

1. `README.md`（你正在看）
2. `checks.md` — 跨文件契约自检清单（哪个字段对应哪个 schema 的哪一行）
3. `kb/sop_vpn_zh.md` → `kb/doc-meta.json` → `kb/chunks.jsonl`：知识库侧
4. `session/inputs/ticket.json` → `session/meta.yaml` → `session/trace.jsonl` → `session/artifacts/...`：会话侧
5. `retrieval/request.json` → `retrieval/response.json`：检索侧
6. `harness/run-config.yaml` → `harness/fixture.json` + `harness/golden.json` → `harness/results.jsonl`：评估侧

## 闭合的本质 / Why this proves the spec is closed

如果以下三组引用任何一组**对不上**，说明 schema/template 有缺：

- `harness/fixture.json#expected_retrieval_doc_ids[]`
  ↔ `retrieval/response.json#results[].document_id`
  ↔ `kb/doc-meta.json#id`
- `session/trace.jsonl#tool_result.artifact_ids[]`
  ↔ `session/artifacts/<artifact_id>.json` 文件名
- `harness/results.jsonl#evaluators[rag.citation_validity].details.invalid_citations`
  ↔ `session/artifacts/art_d8135d82e59e9ad5.json#citations[].chunk_id`
  ↔ `kb/chunks.jsonl#id`

`checks.md` 把每条引用与对应 schema 的行号都列了出来，便于评审。
