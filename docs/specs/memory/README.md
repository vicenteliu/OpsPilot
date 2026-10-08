# KB & RAG — Local Knowledge Base

> **Status**: spec-only. This directory defines the KB's schemas, templates and storage schemas; the implementation is `src/opspilot/kb/`, which executes `storage/sqlite-schema.sql` as it stands.
>
> **Not Memory.** The directory keeps its old name (see "memory" in `CONTEXT.md`) but holds no Memory spec. The three-tier memory model it used to describe (short-term / mid-term / long-term) was removed on 2026-08-18 (#179). **Memory** is `opspilot/memory/` (ADR-0031, revised by ADR-0035). The short-term tier's context policy is not memory and moved to `docs/specs/session/templates/context-budget.template.yaml`.

## TL;DR
The KB holds the documents OpsPilot answers from, chunked and indexed in SQLite (metadata + FTS5 keyword index) and LanceDB (vectors). RAG (Retrieval-Augmented Generation) is the "fetch context" action on top of it.

## What the KB is

- **What**: SOPs, runbooks, product docs. ADR-0038 makes the SSC handbook the KB's single source and the KB a build artifact; that build is not written yet, and `ingest` takes whatever paths it is given
- **Why**: the AI must ground ticket/incident answers in organization-private knowledge
- **Storage**:
  - **Source**: markdown, or any format `markitdown` converts to it (PDF, DOCX, …); the KB keeps the redacted markdown, in chunks, not the file
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

1. **Markdown is the source**: human-readable, git-diff friendly; documents, chunks and vectors are derived and a re-ingest rebuilds them. Conflict resolutions and corrections are not: they record a human decision, and a re-ingest keeps them (#194)
2. **No PII in vectors**: ingestion must run `session/templates/redaction-rules.template.yaml` first, with a hard-fail PII check
3. **Pin embedding model**: an embedding model upgrade = full index rebuild; version changes must be triggered explicitly
4. **Hybrid retrieval by default**: vector (semantic) + BM25 (keyword) + metadata filter (structural); pure vector search easily misses keywords
5. **Citation mandatory**: every retrieval result must map back to `source_path:line_start-line_end`; citation markers are injected into the prompt
6. **Incremental sync**: anchored on `content_hash`; only changed content is re-chunked/re-embedded
7. **Namespaces**: scope-level (team/product/sensitivity) isolation, strictly enforced at retrieval time

## Scope

In scope:
- KB data model: documents, chunks, conflicts and corrections
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
│   ├── kb-document.schema.json            # long-term KB document
│   ├── kb-chunk.schema.json               # chunk + vector ref
│   └── retrieval-query.schema.json        # retrieval request/response
├── templates/
│   ├── kb-document.template.md            # long-term: sample KB document
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

## Contracts with other directories

| Upstream | Input to memory |
|---|---|
| `providers/` | embedding model (must have `capabilities.embeddings: true`) + pinned version |
| `session/templates/` | redaction rules (`redaction-rules.template.yaml`), applied at ingest |
| `playbooks/` | declared retrieval needs (scopes, top_k, filters) |
| `session/` | `tool_call: kb.search` in trace triggers retrieval |

| Downstream | What memory provides |
|---|---|
| `session/` | retrieval results as `tool_result`; cited chunks written into the prompt |
| `harness/` | KB-aware fixtures (including known sources that should be retrieved) |

## Hard nos

- ❌ Never ingest unredacted documents into the KB (even in a private deployment)
- ❌ Never commit the LanceDB data directory to git (`.gitignore` must include `*.lance/` `data/lancedb/`)
- ❌ Never let commands inside the sandbox read the SQLite files directly (they must go through the retrieval API)
- ❌ Never use `latest` for embeddings (consistent with providers)
- ❌ Never relax namespace filtering in multi-tenant scenarios (prevents cross-tenant retrieval)

## Open questions

- [ ] Should running multiple embedding models in parallel (bge for Chinese / text-embedding-3 for English) be part of the default config?
- [ ] Should Graph RAG / knowledge graph get its own `memory/graph/` layer?
