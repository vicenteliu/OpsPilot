# End-to-end sample: `scn_ticket_summary_en`

> **Purpose**: Mirror of `scn_ticket_summary_zh` in English — exercise the same
> 5-tier contract (`providers/` + `memory/` + `session/` + `sandbox/` +
> `harness/`) on an English KB + ticket + rubric, to prove the spec is i18n-clean.
> All files here are **real instance data** (not templates).

## Story

1. A user files a service-desk ticket (`session/inputs/ticket.json`): **multiple
   teammates failing VPN authentication**, with a `vpn-client.log` snippet.
2. OpsPilot creates a Session (`session/meta.yaml`) referencing playbook
   `pb_ticket_summary_en@1.2.0`.
3. The model issues a `kb.search` tool call, retrieving the
   "VPN Troubleshooting / Authentication errors" section from the English KB
   (`kb/sop_vpn_en.md`) — see `retrieval/response.json`.
4. The model produces a structured summary (`session/artifacts/art_35bdeeb64e8242c9.json`)
   with citations traceable back to `source_path:line_range`.
5. Harness runs evaluators (`harness/run-config.yaml` → `harness/results.jsonl`)
   including the three RAG types: `rag.recall_at_k` / `rag.precision_at_k` /
   `rag.citation_validity`, plus `rule.json_schema` and `judge.llm`.

## Data flow

```
[providers/]                     [memory/]
   provider-registry             KB (kb/sop_vpn_en.md)
   anthropic-claude               │
       │                          │ ingestion (one-time)
       │ model_ref                ▼
       │                       chunks (kb/chunks.jsonl)
       │                       LanceDB(vectors) + SQLite(meta+FTS)
       ▼                          │
   ┌────────────────────────────────────────────────┐
   │  session/meta.yaml                              │
   │  ┌──────────────────────────────────────────┐  │
   │  │ trace.jsonl                               │  │
   │  │  1. system: state_change → active         │  │
   │  │  2. prompt: system instructions           │  │
   │  │  3. prompt: user (ticket)                 │  │
   │  │  4. tool_call: kb.search ──────────────▶  │  │ retrieval/request.json
   │  │  5. tool_result: chunks ◀──────────────   │  │ retrieval/response.json
   │  │  6. response: NL summary + footnote       │  │
   │  │  7. tool_call: artifact.write ─────────▶  │  │ artifacts/art_35bdeeb64e8242c9.json
   │  │  8. tool_result: artifact written         │  │
   │  │  9. user_action: accept                   │  │
   │  │ 10. system: state_change → archived       │  │
   │  └──────────────────────────────────────────┘  │
   └────────────────────────────────────────────────┘
                          │
                          ▼
              [harness/]
              run-config.yaml
                  │
                  ▼
              fixture.json (with ground truth doc_ids)
                  + golden.json + rubric.md
                  ↓
              evaluators run:
                rule.json_schema       (structure ok)
                rule.pii_check         (no PII leak)
                rag.recall_at_k        (correct doc_id retrieved)
                rag.precision_at_k     (chunk relevance)
                rag.citation_validity  (citations resolve)
                judge.llm              (LLM scoring)
                  ↓
              results.jsonl
```

## Reading order

1. `README.md` (this file)
2. `checks.md` — cross-file contract self-validation
3. `kb/sop_vpn_en.md` → `kb/doc-meta.json` → `kb/chunks.jsonl` (KB side)
4. `session/inputs/ticket.json` → `session/meta.yaml` → `session/trace.jsonl` →
   `session/artifacts/...` (Session side)
5. `retrieval/request.json` → `retrieval/response.json` (retrieval side)
6. `harness/run-config.yaml` → `harness/fixture.json` + `harness/golden.json` →
   `harness/results.jsonl` (evaluation side)

## Why this proves the spec is closed (i18n edition)

If any of these triplets fails to line up, the spec has a gap that must be
fixed in the schemas/templates:

- `harness/fixture.json#expected_retrieval_doc_ids[]`
  ↔ `retrieval/response.json#results[].document_id`
  ↔ `kb/doc-meta.json#id` (`doc_afe80531`)
- `session/trace.jsonl#tool_result.artifact_ids[]` (`art_35bdeeb64e8242c9`)
  ↔ filename of `session/artifacts/art_35bdeeb64e8242c9.json`
- `harness/results.jsonl#evaluators[rag.citation_validity].details.invalid_citations`
  ↔ `session/artifacts/art_35bdeeb64e8242c9.json#citations[].chunk_id`
  ↔ `kb/chunks.jsonl#id` (`chk_e3fe2afe`)

`checks.md` lists every cross-reference with the corresponding schema field.

## Relationship with `scn_ticket_summary_zh`

This sample is a **structural mirror** of `scn_ticket_summary_zh/`, with:
- Different namespace (`opspilot:public-kb-en` vs `opspilot:public-kb`)
- Different language (`en` vs `zh-CN`)
- Different IDs throughout (so neither sample collides with the other)
- Same 5-tier contract & schemas

Both samples should pass the same machine checks in `checks.md` after their
respective ID substitutions.
