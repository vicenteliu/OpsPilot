# LanceDB Schema — Long-term KB Vector Store

> **Status**: spec only. This document describes the LanceDB table structure and index conventions; concrete table-creation / upgrade scripts are produced during implementation.
> **Version**: 1.0.0  ·  **As of**: 2026-05-01

## TL;DR
LanceDB stores only "vectors + the thin metadata required for retrieval"; **the authoritative metadata lives in SQLite** (the `kb_chunks` table). The two sides map one-to-one via `vector_id` ↔ `kb_chunks.vector_id`.

## Principles

1. **Thin columns**: LanceDB stores only the fields required on the retrieval path; details come from a SQLite join
2. **One dataset per KB**: path `${index_root}/lancedb/<kb_id>.lance/`, convenient for backup and rollback
3. **Optional table-per-namespace**: very large KBs can be split into separate tables to avoid index bloat
4. **Pin embedding model**: `embedding_model` and `dim` are recorded at table creation; switching = creating a new table (mixing vector spaces in one table is not allowed)
5. **Append-only ingestion + tombstone delete**: incremental writes; deletion goes through `delete_obsolete_chunks` to clean up stale vector_ids

## Primary table: `chunks`

| Column | Type (PyArrow / Lance) | Notes |
|---|---|---|
| `vector_id` | `string`, **primary key** | maps uniquely to SQLite `kb_chunks.vector_id`; reusing `chk_<sha8>` as vector_id is recommended |
| `embedding` | `fixed_size_list<float32>[<dim>]` | the vector itself; `dim` is pinned at table creation |
| `document_id` | `string` | `doc_<sha8>` |
| `chunk_id` | `string` | `chk_<sha8>` |
| `namespace` | `string` | e.g. `opspilot:public-kb` |
| `classification` | `string` | `public/internal/confidential/restricted` |
| `language` | `string` | `zh-CN/en/...` |
| `tags` | `list<string>` | used for filtering |
| `embedding_model` | `string` | `<provider_id>/<name>@<version>` |
| `created_at` | `timestamp[ms, tz=UTC]` | ingestion time (used for TTL / rebuild decisions) |

> **Not stored in LanceDB**: raw content, heading_path, line offsets, source_path — these live in SQLite.
> This keeps LanceDB files small and scan + ANN faster; backups are lighter too.

## Indices

### ANN vector index

```yaml
ann:
  type: "ivf_pq"            # ivf_pq (default) | hnsw (depending on LanceDB version support)
  metric: "cosine"          # cosine | l2 | dot
  num_partitions: 64        # rule of thumb by data size: N<100K→32, 100K-500K→64, 500K-2M→128
  num_sub_vectors: 96       # number of PQ sub-vectors; commonly 16/32/64/96
  refresh_after_upsert: false   # refresh only after bulk ingestion completes
```

**Rules of thumb**:
- IVF_PQ suits the 100K-10M range; fast to build, memory-friendly; query recall depends on nlist/nprobe
- HNSW suits < 1M high-QPS scenarios; slow to build but fast to query
- Below 50K rows ANN yields little benefit; brute-force can be used instead (LanceDB's default fallback)

### Scalar filter indices

LanceDB supports filtering on scalar columns. Building scalar indices on the following columns is recommended:

- `namespace`
- `classification`
- `language`
- `embedding_model`

(If the current LanceDB version does not support explicit scalar indices, rely on dataset metadata + columnar scans, and push filters ahead of the query.)

## On-disk layout

```
${index_root}/
├── lancedb/
│   └── <kb_id>.lance/                # LanceDB dataset
│       ├── _versions/                # Lance manifest (version control)
│       ├── data/*.lance              # columnar data files
│       └── _indices/<index_name>/    # ANN index files
├── snapshots/
│   └── <ts>-<kb_id>/                 # backup snapshots (rollback-capable)
└── manifest.jsonl                    # ingestion manifest (aligned with SQLite ingest_runs)
```

`.gitignore` must include: `*.lance/`, `lancedb/`, `snapshots/`.

## Incremental sync

```
ingest trigger ──▶ compare source_path + content_hash
                      │
        ┌─────────────┼──────────────┐
        ▼             ▼              ▼
     unchanged     changed        deleted
        │            │                │
       skip      delete by         delete by
                document_id      document_id
                + re-embed
                + upsert
```

LanceDB natively supports `delete by predicate`; bulk deletes go through a single transaction.

## Query path

```
Request (mode=hybrid)
  │
  ├─▶ embed(query)  ──▶  LanceDB.search(vector, k=top_k_ann, filter=…)
  │
  └─▶ FTS5 BM25 search ──▶ SQLite.kb_chunks_fts (k=top_k_fts)
        │
        ▼
  fusion (RRF / weighted)
        │
        ▼
  enrich via SQLite.v_chunks_with_doc  (fetch source_path / line_range / heading_path)
        │
        ▼
  optional rerank (cross_encoder / llm)
        │
        ▼
  Response (with citations)
```

## Versioning & upgrades

- **Adding schema fields**: compatible; new columns on old rows default to NULL/default values
- **Embedding model change**: **incompatible** (vector spaces are not comparable); a new table must be created, and the old one kept until the switchover completes
- **dim change**: tied to an embedding model change; handled the same way
- **metric change**: creating a new table is recommended; mixing metrics in one table is undefined behavior

Upgrade flow (suggested; recorded at spec stage):
1. Create `chunks_v2`, recording the new embedding_model
2. Fully re-ingest into `chunks_v2` (dry-run → compare recall → apply)
3. Switch traffic to v2
4. Keep `chunks_v1` for at least one rollback window (30 days recommended)
5. Once no rollback is needed → drop v1

## Backup & rollback

- **Snapshots**: before ingestion, tag the current manifest version with LanceDB's `version` API; or file-level cp -al
- **Retention**: keep the 5 most recent snapshots by default
- **Rollback command (implementation stage)**: `opspilot kb rollback --kb <id> --snapshot <ts>` — restores the LanceDB manifest + SQLite snapshot to the same point in time

## Performance notes

- Disable `refresh_after_upsert` during bulk upserts; refresh + optimize once at the end
- Schedule ANN rebuild windows off-peak (cron Sunday 05:00)
- Multiple namespaces sharing a table: use scalar filters; split into separate tables when very large
- Inline chunk text ≤ 8 KiB; anything larger goes to an artifact, avoiding SQLite row bloat

## Cross-store consistency

LanceDB and SQLite are **two separate stores** with no native distributed transaction. Handling:
- In the §upsert stage the ingestion pipeline writes "LanceDB first → then SQLite" or the reverse — pick one and stick to it
- Single-document failure → roll back both sides together (delete the new rows by vector_id / chunk_id)
- Run a consistency check at startup (`SELECT vector_id FROM kb_chunks` ↔ LanceDB scan); quarantine any mismatched entries

## Hard requirements

- Pin `embedding_model` and `dim` at table creation; no mixing within a table
- `vector_id` maps one-to-one between SQLite and LanceDB; no orphans allowed
- Chunks with `restricted` classification do not enter the vector store (keyword-only + restricted namespace)
- The LanceDB data directory stays out of git; markdown sources go in git
- Any schema change must record a new version in `schema_meta` (SQLite side)
