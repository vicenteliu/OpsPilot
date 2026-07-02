# Memory & RAG — Memory & Local KB

> **Status**: spec-only. This directory defines only the 3-tier memory abstraction, schemas, templates, and storage schemas; no runtime implementation here.

## TL;DR
Memory is the context-persistence layer for an AI working across sessions. OpsPilot splits it into three tiers — **short-term / mid-term / long-term** — each mapped to an appropriate storage backend (in-memory + SQLite + LanceDB). RAG (Retrieval-Augmented Generation) is the "fetch context" action on top of the long-term tier.

## Three-tier model

```
                ┌────────────────────────────────────────────────────────────────┐
                │                  Session (current invocation)                   │
                └───────────────────────┬────────────────────────────────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        │                               │                               │
        ▼                               ▼                               ▼
┌──────────────┐              ┌──────────────────┐           ┌──────────────────┐
│ short-term   │              │  mid-term        │           │  long-term (KB)  │
│ memory       │              │  memory          │           │  knowledge base  │
│              │              │                  │           │                  │
│ conversation │              │  cross-session   │           │  docs + vector   │
│ window +     │              │  project /       │           │  index           │
│ rolling      │              │  workspace       │           │  RAG retrieval   │
│ summary      │              │                  │           │                  │
├──────────────┤              ├──────────────────┤           ├──────────────────┤
│ TTL: session │              │ TTL: project     │           │ TTL: long-term   │
│ store: in-mem│              │ store: SQLite    │           │ store: md +      │
│ form: JSONL  │              │ form: markdown + │           │        LanceDB   │
│    + summary │              │       record     │           │ form: markdown + │
│              │              │                  │           │       chunks     │
└──────────────┘              └──────────────────┘           └──────────────────┘
```

## Responsibilities

### Short-term
- **What**: the current session's conversation window + rolling summaries of over-long content + a scratchpad workspace
- **Why**: context has a token ceiling; on overflow, content must be trimmed/summarized rather than naively truncated
- **Source**: reuses `session/trace.jsonl` directly (existing schema); no rebuild
- **Typical size**: a few KB to a few hundred KB
- **In git**: no; on session archival the summary flows into mid-term

### Mid-term
- **What**: cross-session project knowledge + user preferences + decision records + TODOs
- **Why**: avoids re-explaining project background every time; lets the AI act like an experienced colleague
- **Types** (aligned with Claude Code memory): `user / feedback / project / reference`
- **Storage**: SQLite (structured + FTS5 full-text search) + companion markdown sources (git-friendly)
- **Typical size**: a few hundred records, a few MB
- **In git**: project-level mid-term memory should be committed to git; personal preferences live in `~/.opspilot/memory/`

### Long-term (KB / Knowledge Base)
- **What**: company SOPs, runbooks, product docs, historical case summaries, wiki imports
- **Why**: the AI must ground ticket/incident answers in organization-private knowledge
- **Storage**:
  - **Source**: markdown files (git-managed, human-readable, auditable)
  - **Index**: LanceDB (vectors) + SQLite (metadata + FTS5 keyword)
- **Pipeline**: ingest → chunk → embed → upsert; incremental rebuilds anchored on `content_hash`
- **Typical size**: thousands to hundreds of thousands of chunks
- **In git**: markdown sources go in git; the LanceDB data directory is `.gitignore`d (built on demand)

## Data flow

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
                                 │  prompt  │ ──▶ cited chunks + summary into prompt
                                 └──────────┘
```

## Principles

1. **Markdown is the source**: human-readable, git-diff friendly; SQLite/LanceDB are derived indices and can be rebuilt
2. **No PII in vectors**: ingestion must run `session/templates/redaction-rules.template.yaml` first, with a hard-fail PII check
3. **Pin embedding model**: an embedding model upgrade = full index rebuild; version changes must be triggered explicitly
4. **Hybrid retrieval by default**: vector (semantic) + BM25 (keyword) + metadata filter (structural); pure vector search easily misses keywords
5. **Citation mandatory**: every retrieval result must map back to `source_path:line_start-line_end`; citation markers are injected into the prompt
6. **Incremental sync**: anchored on `content_hash`; only changed content is re-chunked/re-embedded
7. **Namespaces**: scope-level (team/product/sensitivity) isolation, strictly enforced at retrieval time

## Scope

In scope:
- Data model and lifecycle of the three memory tiers
- RAG ingestion + retrieval pipeline contracts
- SQLite + LanceDB schemas and naming conventions
- Interfaces with providers / session / sandbox / harness

Out of scope (not in this directory for now):
- Concrete ingestion implementation (Python pipeline)
- Concrete retrieval client SDK
- UI search interface
- Graph RAG / Knowledge Graph (to be considered later)

## Directory layout

```
memory/
├── README.md                              # this file
├── SPEC.md                                # detailed spec (incl. RAG pipeline)
├── schemas/
│   ├── memory-record.schema.json          # mid-term memory record
│   ├── kb-document.schema.json            # long-term KB document
│   ├── kb-chunk.schema.json               # chunk + vector ref
│   └── retrieval-query.schema.json        # retrieval request/response
├── templates/
│   ├── memory-record.template.md          # mid-term: markdown + frontmatter
│   ├── kb-document.template.md            # long-term: sample KB document
│   ├── short-term-config.template.yaml    # short-term: window/summary policy
│   ├── mid-term-config.template.yaml      # mid-term: SQLite/namespaces
│   ├── kb-config.template.yaml            # long-term: KB paths and namespaces
│   ├── ingestion.template.yaml            # ingestion pipeline
│   └── retrieval.template.yaml            # retrieval/reranking config
└── storage/
    ├── sqlite-schema.sql                  # SQLite DDL (incl. FTS5)
    └── lancedb-schema.md                  # LanceDB tables and indices
```

## Why these stacks

| Component | Chosen | Not chosen | Rationale |
|---|---|---|---|
| Long-term vector store | **LanceDB** | Chroma / Weaviate / Qdrant / pgvector | embedded (no server process) + columnar (PyArrow) + incremental updates + git-friendly file layout |
| Metadata / keyword | **SQLite + FTS5** | Postgres / Elastic | embedded, zero ops; FTS5 has built-in BM25; file-based just like LanceDB |
| Source format | **Markdown + frontmatter** | JSON / DB-only | human-readable, git-diff friendly, cross-tool compatible (Obsidian / Foam / Logseq) |
| Short-term | reuse session/trace | building a separate layer | avoids a duplicate schema; trace already has redaction and retention |

## Contracts with other directories

| Upstream | Input to memory |
|---|---|
| `providers/` | embedding model (must have `capabilities.embeddings: true`) + pinned version |
| `governance/` | data classification + redaction rules + retention policy |
| `playbooks/` | declared retrieval needs (scopes, top_k, filters) |
| `session/` | writes the session summary into mid-term on archival; `tool_call: kb.search` in trace triggers retrieval |

| Downstream | What memory provides |
|---|---|
| `session/` | retrieval results as `tool_result`; cited chunks written into the prompt |
| `harness/` | KB-aware fixtures (including known sources that should be retrieved) |
| `case-studies/` | cross-session knowledge distillation |

## Hard nos

- ❌ Never ingest unredacted documents into the KB (even in a private deployment)
- ❌ Never commit the LanceDB data directory to git (`.gitignore` must include `*.lance/` `data/lancedb/`)
- ❌ Never let commands inside the sandbox read the SQLite files directly (they must go through the retrieval API)
- ❌ Never use `latest` for embeddings (consistent with providers)
- ❌ Never relax namespace filtering in multi-tenant scenarios (prevents cross-tenant retrieval)

## Open questions

- [ ] Who decides when short-term summarization triggers: the session engine, the playbook, or the model itself?
- [ ] Does mid-term "auto-harvest" (session archive → mid-term) need LLM extraction, or are rules enough?
- [ ] Should running multiple embedding models in parallel (bge for Chinese / text-embedding-3 for English) be part of the default config?
- [ ] Should Graph RAG / knowledge graph get its own `memory/graph/` layer?
