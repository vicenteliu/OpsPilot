# Memory & RAG — Detailed Spec

## 1. Three-tier semantics

| Tier | Scope | TTL | Backend | Namespace |
|---|---|---|---|---|
| short-term | within a single session | bound to session state | in-memory + summaries written back to trace | session_id |
| mid-term | project / workspace | project lifetime; can be expired manually | SQLite (with FTS5) + markdown | `<workspace>:<scope>` |
| long-term (KB) | knowledge base | long-term; versioned | markdown + LanceDB + SQLite meta | `<kb>:<scope>` |

## 2. Memory types (mid-tier)

Aligned with the memory model of agents such as Claude Code, for easy cross-tool migration:

| `type` | Purpose | Example |
|---|---|---|
| `user` | user role, preferences, knowledge | "User is a data scientist focused on observability" |
| `feedback` | user corrections/confirmations of the AI (incl. why) | "Do not pile timestamps into RCAs; list only the causal chain" |
| `project` | project status, decisions, deadlines, owners | "Finish the ITIL rollout pilot before Q2 starts; owner alice" |
| `reference` | pointers to external systems (not the facts themselves) | "Tickets live in the Jira INC project; alerts on Grafana dashboard xx" |

`type` is a hard constraint (schema enum), used for retrieval filtering and display grouping.

## 3. Mid-term record fields

The authoritative definition is `schemas/memory-record.schema.json`.

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | `mem_<sha8>` | ✓ | content-addressed |
| `type` | enum, see §2 | ✓ | |
| `scope` | string | ✓ | namespace, e.g. `opspilot:user` / `opspilot:project` |
| `title` | string | ✓ | ≤80 chars; used in the retrieval hit list |
| `body` | string | ✓ | markdown body; with **Why:** and **How to apply:** sections (mandatory for feedback/project) |
| `tags` | string[] | ✗ | free-form tags |
| `source` | object | ✓ | see §4 |
| `created_at` | RFC3339 | ✓ | |
| `updated_at` | RFC3339 | ✓ | |
| `valid_until` | RFC3339 \| null | ✗ | explicit expiry; read-only once expired |
| `confidence` | enum `low/medium/high` | ✓ | affects retrieval weighting |
| `redacted` | bool | ✓ | must be true before storage |

## 4. Source attribution

```yaml
source:
  origin: "session" | "user_input" | "ingest" | "system"
  session_id: "sess_..."        # when origin=session
  trace_seq: 42                  # when derived from a specific trace event
  document_id: "doc_..."         # when origin=ingest
  url: "https://..."             # when from an external source
```

## 5. KB document (long-term)

The authoritative definition is `schemas/kb-document.schema.json`.

```yaml
id: "doc_<sha8>"                 # sha8 of source_path + initial content_hash
source_path: "playbooks/sop_vpn.md"   # repo-relative path
source_url: null                  # original URL when imported from an external wiki
title: "VPN Troubleshooting SOP"
classification: "internal"        # public | internal | confidential | restricted
content_hash: "sha256:..."        # sha256 of the markdown body
version: "1.3.0"                  # semantic version (optional)
ingested_at: "2026-05-01T10:00:00Z"
last_modified: "2026-04-28T08:30:00Z"
language: "zh-CN"
tags: ["vpn", "sop", "L1"]
namespace: "opspilot:public-kb"
chunk_strategy: "headings_then_size"  # see §7
chunk_count: 12
embedding_model: "ollama/nomic-embed-text@2024-02"
embedding_dim: 768
redaction_passed: true
redaction_rules_version: "1.0.0"
```

## 6. Chunk metadata

The authoritative definition is `schemas/kb-chunk.schema.json`.

```yaml
id: "chk_<sha8>"
document_id: "doc_..."
seq: 0
content: "..."                    # redacted chunk text (or an artifact reference)
content_hash: "sha256:..."
char_start: 0                     # character offset in the markdown source
char_end: 1024
line_start: 1
line_end: 24
heading_path: ["VPN SOP", "Troubleshooting", "Authentication errors"]   # heading breadcrumb
embedding_model: "ollama/nomic-embed-text@2024-02"
vector_id: "<lancedb row id>"      # LanceDB primary-key reference
metadata:
  tags: ["vpn", "auth"]
  namespace: "opspilot:public-kb"
  classification: "internal"
```

## 7. Chunking strategies

Allowed `chunk_strategy` values (configured in `templates/ingestion.template.yaml`):

| Strategy | Suited for | Key parameters |
|---|---|---|
| `headings_then_size` | markdown / SOP (**recommended default**) | `target_size_tokens=512`, `max_size_tokens=1024`, `overlap_tokens=64` |
| `fixed_size` | plain text / log samples | `size_tokens=512`, `overlap_tokens=64` |
| `sentence_boundary` | long paragraphs, compliance documents | `max_size_tokens=512`, `overlap_sentences=2` |
| `code_aware` | code / configuration | split by language AST / top-level def blocks |
| `semantic` | experimental | cut where embedding similarity shifts sharply; expensive |

Hard constraints:
- Every strategy must preserve `heading_path` (the markdown heading hierarchy) so retrieval results can be located
- The token counter must match the downstream embedding model (to avoid over-long content being silently truncated)
- `overlap` must not be 0 (except fixed_size + short documents)

## 8. Embedding selection

Embedding calls go through the `providers/` abstraction layer (the provider must have `capabilities.embeddings: true`).

Recommended combinations (as of 2026-05-01; catalogs.md is authoritative):

| Use case | Recommended model_ref | dim | Notes |
|---|---|---|---|
| **Local / offline (default)** | `ollama-local/nomic-embed-text@2024-02` | 768 | good for Chinese and English; zero cost; self-hosted |
| Stronger Chinese | `ollama-local/bge-m3@2024-06` | 1024 | multilingual + long documents |
| Cloud, high quality | `openai-main/text-embedding-3-large@2024-01` | 3072 | requires egress; billed per token |
| Cloud, low cost | `openai-main/text-embedding-3-small@2024-01` | 1536 | a compromise |
| Gemini | `gemini-main/text-embedding-004@2024-04` | 768 | when aligned with the Gemini ecosystem |

**Hard constraints**:
- Once a KB namespace has picked an embedding model, **mixing in other models is not allowed** (vector spaces are not comparable)
- Upgrading the embedding model = creating a new namespace or fully rebuilding the index
- The `embedding_model` field must include a concrete version; `latest` is forbidden

## 9. Retrieval contract

The authoritative definition is `schemas/retrieval-query.schema.json`.

### 9.1 Request

```yaml
query: "How to troubleshoot VPN authentication failures"
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

### 9.2 Response

```yaml
query_id: "q_<ULID>"
results:
  - chunk_id: "chk_..."
    document_id: "doc_..."
    score: 0.87                   # normalized to [0,1]
    rank: 1
    content: "...excerpt..."
    citation:
      source_path: "playbooks/sop_vpn.md"
      line_start: 41
      line_end: 58
      heading_path: ["VPN SOP", "Troubleshooting", "Authentication errors"]
      anchor: "#troubleshooting-authentication-errors"   # optional markdown anchor
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

## 10. Retrieval modes

| mode | Engine | Suited for |
|---|---|---|
| `vector` | LanceDB ANN | semantic similarity, fuzzy queries |
| `keyword` | SQLite FTS5 (BM25) | exact nouns, error codes, commands |
| `hybrid` | both in parallel + fusion (default) | general use |

Fusion methods:
- **RRF** (Reciprocal Rank Fusion, **default**): `score = Σ 1 / (k + rank_i)`, k=60; robust to rank noise
- **weighted_sum**: weighted sum of normalized scores; weights need careful tuning

## 11. Rerank

| type | Description | Suited for |
|---|---|---|
| `none` | no reranking | simple queries, low cost |
| `cross_encoder` | cross-encoder reranker (e.g. bge-reranker-v2) | recommended default; runs locally; tens of ms |
| `llm` | LLM-as-rerank (small judge model) | complex semantics; higher cost and latency |

Hard constraints:
- rerank model versions must be pinned as well
- `top_k > top_n`: coarse-rank to k first, then rerank down to n
- `budget_usd` must be able to cover the rerank call

## 12. Ingestion pipeline

Stages (each stage must be re-entrant and recoverable):

```
discover ──▶ classify ──▶ redact ──▶ chunk ──▶ embed ──▶ upsert
   │           │            │         │         │          │
   ▼           ▼            ▼         ▼         ▼          ▼
 source     metadata     redacted  chunks   vectors    indices
 manifest    record      content                       updated
```

| Stage | Input | Output | Failure handling |
|---|---|---|---|
| discover | sources from config | source manifest (path + last_modified) | skip + log |
| classify | source | classification + tags | default internal |
| redact | original text | redacted text + hit records | hard-fail (residual PII blocks storage) |
| chunk | redacted text | chunk list (with heading_path) | skip the document + mark dirty |
| embed | chunk text | vectors | retry → mark pending |
| upsert | document + chunks + vectors | LanceDB + SQLite row updates | transaction rollback |

**Incremental sync**:
- anchored on `source_path` + `content_hash`
- `content_hash` unchanged → skip the whole document
- `content_hash` changed → delete old chunks (by document_id) + re-chunk/embed/upsert
- document deleted → cascade-delete all chunks under that doc

## 13. Short-term details

Short-term memory does not get its own tables; it **reuses `session/trace.jsonl`** plus a set of runtime policies.

Policies (in `short-term-config.template.yaml`):

```yaml
context_window:
  max_tokens: 100000              # aligned with the model's long_context_tokens
  reserve_for_response: 8000
  reserve_for_system: 4000

policy:
  on_overflow: "summarize_oldest"  # truncate | summarize_oldest | summarize_smart
  summarize_when_remaining_lt: 16000   # remaining-budget threshold that triggers summarization
  keep_pinned: true                # events with user_action=pin are excluded from trimming
  keep_last_n_user_turns: 4

summary:
  use_provider_alias: "@chat-fast" # summaries use the fast tier; decoupled from the main playbook provider
  template_ref: "prompts/summarize_session_zh.md"
  max_summary_tokens: 1024
  store_as_trace_event: "system"    # written back to trace (type=system, event=summary_marker)
```

## 14. Mid-term write & harvest

Write paths:
1. **Direct write**: user/playbook submits explicitly (`memory.add(...)`)
2. **Harvest**: on session archival, extract facts worth long-term retention from the trace

Harvest rules (suggested):
- explicitly marked `pin_to_memory` after `user_action=accept`
- the `payload_diff` carried by `user_action=edit` contains the word "remember"
- when session state moves `archived → finalize`, the summarizer emits candidates awaiting user confirmation

**Anti-patterns (don't do this)**:
- Don't put code patterns / file paths / project structure into memory (grep gets those)
- Don't put git history / who changed what into memory (`git log`/`git blame` are authoritative)
- Don't put debugging solutions into memory (the fix lives in the code; the commit message has the context)

Reference: aligned with the design of Claude Code's memory system, for cross-tool reuse.

## 15. Security & redaction

Hard constraints (hard-coded in schema / pipeline):
- Content entering SQLite / LanceDB must have `redacted=true`
- The ingestion pipeline must run redaction **before** chunking
- Use `session/templates/redaction-rules.template.yaml` as the minimum rule set
- Every rule hit is fully logged to `audit.log` (same format as session)
- `classification=restricted` documents do not enter the vector store by default; keyword-only + restricted namespace

## 16. Interfaces

### 16.1 Session (tool calls in trace)

Tools memory exposes to session:

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

The sandbox never accesses the SQLite/LanceDB data files directly; only the `kb.search` / `memory.search` tool calls are available.

### 16.3 Harness

When the harness evaluates a RAG playbook:
- fixtures include the list of document ids that should be retrieved, as ground truth
- evaluator types are extended: `rag.recall@k`, `rag.precision@k`, `rag.citation_validity`

### 16.4 Providers

- embedding: requires `capabilities.embeddings: true`
- rerank: optional LLM rerank goes through the `@judge` alias

## 17. Hard requirements

- markdown is the source; SQLite/LanceDB can be rebuilt
- all IDs are content-addressed (`mem_<sha8>` / `doc_<sha8>` / `chk_<sha8>`)
- the `embedding_model` field includes a concrete version; no mixing within a namespace
- `redacted=true` is a precondition for storage
- `classification=restricted` documents do not enter the vector store
- every retrieval result must carry a `citation` resolvable to `source_path:line_range`
- the LanceDB data directory goes in `.gitignore`; markdown sources go in git
