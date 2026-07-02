-- OpsPilot Memory · SQLite Schema
-- Scope: mid-term memory + KB metadata/keyword index (FTS5)
-- Version: 1.2.0
-- As of: 2026-05-06
-- Hard requirement: all content entering this DB must already be redacted (redacted=1).
--
-- Changelog:
--   1.2.0 (IT-KB): added valid_from / source_authority to kb_documents;
--                  added valid_from / superseded_by to kb_chunks;
--                  added kb_conflicts (conflict queue) and kb_corrections (knowledge corrections) tables.
--   1.1.0 (PR-4): FTS5 tokenizer unicode61 → trigram, CJK-friendly.
--   1.0.0:        initial spec.
--
-- Recommended PRAGMAs:
--   PRAGMA journal_mode=WAL;
--   PRAGMA synchronous=NORMAL;
--   PRAGMA foreign_keys=ON;
--   PRAGMA temp_store=MEMORY;
--   PRAGMA mmap_size=268435456;   -- 256 MiB
--
-- Backup: run sqlite3 .backup before schema changes or bulk ingestion; retain N snapshots.

------------------------------------------------------------
-- 1. SCHEMA META
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_meta (
  key         TEXT PRIMARY KEY,
  value       TEXT NOT NULL,
  updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

INSERT OR REPLACE INTO schema_meta(key, value) VALUES
  ('schema_version', '1.2.0'),
  ('created_at',     strftime('%Y-%m-%dT%H:%M:%fZ','now'));

------------------------------------------------------------
-- 2. MID-TERM MEMORY
------------------------------------------------------------
-- Equivalent to schemas/memory-record.schema.json
CREATE TABLE IF NOT EXISTS memory_records (
  id                       TEXT PRIMARY KEY
                                CHECK (id GLOB 'mem_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  type                     TEXT NOT NULL CHECK (type IN ('user','feedback','project','reference')),
  scope                    TEXT NOT NULL,
  title                    TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 80),
  body                     TEXT NOT NULL,
  tags_json                TEXT NOT NULL DEFAULT '[]',
  source_origin            TEXT NOT NULL CHECK (source_origin IN ('session','user_input','ingest','system')),
  source_session_id        TEXT,
  source_trace_seq         INTEGER,
  source_document_id       TEXT,
  source_url               TEXT,
  created_at               TEXT NOT NULL,
  updated_at               TEXT NOT NULL,
  valid_until              TEXT,
  confidence               TEXT NOT NULL CHECK (confidence IN ('low','medium','high')),
  redacted                 INTEGER NOT NULL CHECK (redacted = 1),
  redaction_rules_version  TEXT,
  labels_json              TEXT NOT NULL DEFAULT '{}',
  extensions_json          TEXT NOT NULL DEFAULT '{}'
) STRICT;

CREATE INDEX IF NOT EXISTS idx_mem_type        ON memory_records(type);
CREATE INDEX IF NOT EXISTS idx_mem_scope       ON memory_records(scope);
CREATE INDEX IF NOT EXISTS idx_mem_updated     ON memory_records(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_mem_valid_until ON memory_records(valid_until);
CREATE INDEX IF NOT EXISTS idx_mem_session     ON memory_records(source_session_id);

-- FTS5 full-text index (external-content table; BM25 by default)
-- tokenize='trigram': matches substring queries on mixed Chinese/English content
CREATE VIRTUAL TABLE IF NOT EXISTS memory_records_fts USING fts5 (
  title,
  body,
  tags,
  content='memory_records',
  content_rowid='rowid',
  tokenize='trigram'
);

-- Triggers keeping FTS in sync with the main table
CREATE TRIGGER IF NOT EXISTS memory_records_ai AFTER INSERT ON memory_records BEGIN
  INSERT INTO memory_records_fts(rowid, title, body, tags)
  VALUES (new.rowid, new.title, new.body, new.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS memory_records_ad AFTER DELETE ON memory_records BEGIN
  INSERT INTO memory_records_fts(memory_records_fts, rowid, title, body, tags)
  VALUES ('delete', old.rowid, old.title, old.body, old.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS memory_records_au AFTER UPDATE ON memory_records BEGIN
  INSERT INTO memory_records_fts(memory_records_fts, rowid, title, body, tags)
  VALUES ('delete', old.rowid, old.title, old.body, old.tags_json);
  INSERT INTO memory_records_fts(rowid, title, body, tags)
  VALUES (new.rowid, new.title, new.body, new.tags_json);
END;

------------------------------------------------------------
-- 3. KB DOCUMENTS
------------------------------------------------------------
-- Equivalent to schemas/kb-document.schema.json
CREATE TABLE IF NOT EXISTS kb_documents (
  id                       TEXT PRIMARY KEY
                                CHECK (id GLOB 'doc_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  source_path              TEXT NOT NULL,
  source_url               TEXT,
  title                    TEXT NOT NULL,
  classification           TEXT NOT NULL CHECK (classification IN ('public','internal','confidential','restricted')),
  content_hash             TEXT NOT NULL CHECK (content_hash GLOB 'sha256:*'),
  version                  TEXT,
  ingested_at              TEXT NOT NULL,
  last_modified            TEXT,
  language                 TEXT NOT NULL,
  tags_json                TEXT NOT NULL DEFAULT '[]',
  namespace                TEXT NOT NULL,
  chunk_strategy           TEXT NOT NULL,
  chunk_count              INTEGER NOT NULL DEFAULT 0,
  embedding_model          TEXT NOT NULL,
  embedding_dim            INTEGER NOT NULL,
  redaction_passed         INTEGER NOT NULL CHECK (redaction_passed = 1),
  redaction_rules_version  TEXT,
  license                  TEXT,
  extensions_json          TEXT NOT NULL DEFAULT '{}',
  valid_from               TEXT,    -- effective date (ISO8601); NULL = unknown
  source_authority         TEXT NOT NULL DEFAULT 'internal'
                               CHECK (source_authority IN ('official','vendor','internal','unverified'))
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_source_path ON kb_documents(source_path);
CREATE INDEX        IF NOT EXISTS idx_doc_namespace   ON kb_documents(namespace);
CREATE INDEX        IF NOT EXISTS idx_doc_class       ON kb_documents(classification);
CREATE INDEX        IF NOT EXISTS idx_doc_lang        ON kb_documents(language);
CREATE INDEX        IF NOT EXISTS idx_doc_emb_model   ON kb_documents(embedding_model);
CREATE INDEX        IF NOT EXISTS idx_doc_valid_from  ON kb_documents(valid_from DESC);

------------------------------------------------------------
-- 4. KB CHUNKS (metadata; the vectors themselves live in LanceDB)
------------------------------------------------------------
-- Equivalent to schemas/kb-chunk.schema.json
CREATE TABLE IF NOT EXISTS kb_chunks (
  id                  TEXT PRIMARY KEY
                          CHECK (id GLOB 'chk_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  document_id         TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
  seq                 INTEGER NOT NULL,
  content             TEXT,                         -- ≤8KiB; larger content goes to an artifact
  content_artifact_id TEXT,
  content_hash        TEXT NOT NULL CHECK (content_hash GLOB 'sha256:*'),
  char_start          INTEGER NOT NULL,
  char_end            INTEGER NOT NULL,
  line_start          INTEGER NOT NULL,
  line_end            INTEGER NOT NULL,
  heading_path_json   TEXT NOT NULL DEFAULT '[]',
  anchor              TEXT,
  token_count         INTEGER,
  embedding_model     TEXT NOT NULL,
  vector_id           TEXT NOT NULL UNIQUE,         -- LanceDB row primary key
  namespace           TEXT NOT NULL,
  classification      TEXT NOT NULL CHECK (classification IN ('public','internal','confidential','restricted')),
  language            TEXT,
  tags_json           TEXT NOT NULL DEFAULT '[]',
  valid_from          TEXT,    -- inherited from document; ISO8601
  superseded_by       TEXT,    -- chunk_id of the newer chunk that replaces this
  CHECK (char_end >= char_start),
  CHECK (line_end >= line_start),
  CHECK (
    (content IS NOT NULL AND content_artifact_id IS NULL)
    OR (content IS NULL AND content_artifact_id IS NOT NULL)
  )
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_chk_doc_seq      ON kb_chunks(document_id, seq);
CREATE INDEX        IF NOT EXISTS idx_chk_namespace    ON kb_chunks(namespace);
CREATE INDEX        IF NOT EXISTS idx_chk_class        ON kb_chunks(classification);
CREATE INDEX        IF NOT EXISTS idx_chk_emb_model    ON kb_chunks(embedding_model);
CREATE INDEX        IF NOT EXISTS idx_chk_valid_from   ON kb_chunks(valid_from DESC);
CREATE INDEX        IF NOT EXISTS idx_chk_superseded   ON kb_chunks(superseded_by);

-- FTS5 index for KB chunks (keyword path of hybrid retrieval)
-- tokenize='trigram': matches substring queries on mixed Chinese/English content
CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunks_fts USING fts5 (
  content,
  heading_path,
  tags,
  content='kb_chunks',
  content_rowid='rowid',
  tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS kb_chunks_ai AFTER INSERT ON kb_chunks BEGIN
  INSERT INTO kb_chunks_fts(rowid, content, heading_path, tags)
  VALUES (new.rowid, COALESCE(new.content, ''), new.heading_path_json, new.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS kb_chunks_ad AFTER DELETE ON kb_chunks BEGIN
  INSERT INTO kb_chunks_fts(kb_chunks_fts, rowid, content, heading_path, tags)
  VALUES ('delete', old.rowid, COALESCE(old.content, ''), old.heading_path_json, old.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS kb_chunks_au AFTER UPDATE ON kb_chunks BEGIN
  INSERT INTO kb_chunks_fts(kb_chunks_fts, rowid, content, heading_path, tags)
  VALUES ('delete', old.rowid, COALESCE(old.content, ''), old.heading_path_json, old.tags_json);
  INSERT INTO kb_chunks_fts(rowid, content, heading_path, tags)
  VALUES (new.rowid, COALESCE(new.content, ''), new.heading_path_json, new.tags_json);
END;

------------------------------------------------------------
-- 5. KB CONFLICTS (knowledge-conflict queue)
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_conflicts (
  id              TEXT PRIMARY KEY
                      CHECK (id GLOB 'conf_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  chunk_a_id      TEXT NOT NULL REFERENCES kb_chunks(id) ON DELETE CASCADE,
  chunk_b_id      TEXT NOT NULL REFERENCES kb_chunks(id) ON DELETE CASCADE,
  doc_a_id        TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
  doc_b_id        TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
  conflict_type   TEXT NOT NULL CHECK (conflict_type IN (
                    'temporal_supersede',   -- one doc clearly newer; likely supersedes
                    'scope_overlap',        -- high similarity; may duplicate or conflict
                    'direct_contradiction'  -- heuristically detected opposing claims
                  )),
  similarity      REAL NOT NULL,            -- cosine similarity [0,1]
  status          TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open','a_wins','b_wins','merged','dismissed')),
  resolved_by     TEXT,
  resolved_at     TEXT,
  resolution_note TEXT,
  detected_at     TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_conf_status     ON kb_conflicts(status);
CREATE INDEX IF NOT EXISTS idx_conf_doc_a      ON kb_conflicts(doc_a_id);
CREATE INDEX IF NOT EXISTS idx_conf_doc_b      ON kb_conflicts(doc_b_id);
CREATE INDEX IF NOT EXISTS idx_conf_detected   ON kb_conflicts(detected_at DESC);

------------------------------------------------------------
-- 6. KB CORRECTIONS (knowledge-correction records)
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_corrections (
  id           TEXT PRIMARY KEY
                   CHECK (id GLOB 'corr_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  chunk_id     TEXT NOT NULL REFERENCES kb_chunks(id) ON DELETE CASCADE,
  corrected_by TEXT NOT NULL,
  reason       TEXT NOT NULL,
  old_content  TEXT NOT NULL,
  new_content  TEXT NOT NULL,
  created_at   TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_corr_chunk ON kb_corrections(chunk_id);

------------------------------------------------------------
-- 7. INGEST RUNS (audit & recoverability)
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_runs (
  id                   TEXT PRIMARY KEY,             -- ULID
  kb_id                TEXT NOT NULL,
  started_at           TEXT NOT NULL,
  finished_at          TEXT,
  status               TEXT NOT NULL CHECK (status IN ('running','succeeded','failed','aborted')),
  docs_total           INTEGER NOT NULL DEFAULT 0,
  docs_succeeded       INTEGER NOT NULL DEFAULT 0,
  docs_failed          INTEGER NOT NULL DEFAULT 0,
  chunks_total         INTEGER NOT NULL DEFAULT 0,
  tokens_embedded      INTEGER NOT NULL DEFAULT 0,
  cost_usd             REAL    NOT NULL DEFAULT 0,
  redaction_hits       INTEGER NOT NULL DEFAULT 0,
  redaction_hard_fails INTEGER NOT NULL DEFAULT 0,
  config_hash          TEXT,
  error_summary        TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_run_kb_started ON ingest_runs(kb_id, started_at DESC);

------------------------------------------------------------
-- 8. AUDIT LOG (same semantics as session.audit.log)
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          TEXT NOT NULL,
  actor       TEXT NOT NULL,
  action      TEXT NOT NULL,
  target      TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}'
) STRICT;

CREATE INDEX IF NOT EXISTS idx_audit_ts     ON audit_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log(target);

------------------------------------------------------------
-- 9. Helper view for hybrid retrieval
------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_chunks_with_doc AS
SELECT
  c.id              AS chunk_id,
  c.document_id     AS document_id,
  c.seq             AS seq,
  c.content         AS content,
  c.content_artifact_id AS content_artifact_id,
  c.heading_path_json   AS heading_path_json,
  c.line_start      AS line_start,
  c.line_end        AS line_end,
  c.namespace       AS namespace,
  c.classification  AS classification,
  c.embedding_model AS embedding_model,
  c.vector_id       AS vector_id,
  d.source_path     AS source_path,
  d.title           AS document_title,
  d.language        AS language,
  d.tags_json       AS doc_tags_json
FROM kb_chunks c
JOIN kb_documents d ON d.id = c.document_id;
