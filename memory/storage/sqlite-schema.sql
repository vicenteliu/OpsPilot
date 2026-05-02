-- OpsPilot Memory · SQLite Schema
-- 适用：mid-term memory + KB 元数据/关键字索引（FTS5）
-- 版本：1.1.0
-- 信息日期：2026-05-01
-- 强约束：所有进入此 DB 的内容必须已脱敏（redacted=1）。
--
-- 变更日志 / Changelog:
--   1.1.0 (PR-4): FTS5 tokenizer unicode61 → trigram，对 CJK 友好；
--                 unicode61 把整段中文当一个 token，召回率太低
--                 (例：query "认证失败" 无法命中 "...认证失败基本指向..."
--                  这种嵌入式 substring；trigram 按 3-gram 切片可命中)。
--                 副作用：失去 porter 词干提取，对纯英文索引影响轻微，
--                 logs/技术词没有词干变化诉求。
--   1.0.0:        initial spec.
--
-- 推荐 PRAGMA：
--   PRAGMA journal_mode=WAL;
--   PRAGMA synchronous=NORMAL;
--   PRAGMA foreign_keys=ON;
--   PRAGMA temp_store=MEMORY;
--   PRAGMA mmap_size=268435456;   -- 256 MiB
--
-- 备份：在 schema 变更或大批量摄入前 sqlite3 .backup；保留 N 份快照。

------------------------------------------------------------
-- 1. SCHEMA META
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_meta (
  key         TEXT PRIMARY KEY,
  value       TEXT NOT NULL,
  updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

INSERT OR REPLACE INTO schema_meta(key, value) VALUES
  ('schema_version', '1.1.0'),
  ('created_at',     strftime('%Y-%m-%dT%H:%M:%fZ','now'));

------------------------------------------------------------
-- 2. MID-TERM MEMORY
------------------------------------------------------------
-- 与 schemas/memory-record.schema.json 等价
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

-- FTS5 全文索引（contentless 外部内容；BM25 默认）
-- tokenize='trigram': 对中英文混合内容均能命中 substring 查询
CREATE VIRTUAL TABLE IF NOT EXISTS memory_records_fts USING fts5 (
  title,
  body,
  tags,
  content='memory_records',
  content_rowid='rowid',
  tokenize='trigram'
);

-- FTS 与主表的同步触发器
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
-- 与 schemas/kb-document.schema.json 等价
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
  extensions_json          TEXT NOT NULL DEFAULT '{}'
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_source_path ON kb_documents(source_path);
CREATE INDEX        IF NOT EXISTS idx_doc_namespace   ON kb_documents(namespace);
CREATE INDEX        IF NOT EXISTS idx_doc_class       ON kb_documents(classification);
CREATE INDEX        IF NOT EXISTS idx_doc_lang        ON kb_documents(language);
CREATE INDEX        IF NOT EXISTS idx_doc_emb_model   ON kb_documents(embedding_model);

------------------------------------------------------------
-- 4. KB CHUNKS（元数据；向量本体在 LanceDB）
------------------------------------------------------------
-- 与 schemas/kb-chunk.schema.json 等价
CREATE TABLE IF NOT EXISTS kb_chunks (
  id                  TEXT PRIMARY KEY
                          CHECK (id GLOB 'chk_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
  document_id         TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
  seq                 INTEGER NOT NULL,
  content             TEXT,                         -- ≤8KiB；超过走 artifact
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
  vector_id           TEXT NOT NULL UNIQUE,         -- LanceDB 行主键
  namespace           TEXT NOT NULL,
  classification      TEXT NOT NULL CHECK (classification IN ('public','internal','confidential','restricted')),
  language            TEXT,
  tags_json           TEXT NOT NULL DEFAULT '[]',
  CHECK (char_end >= char_start),
  CHECK (line_end >= line_start),
  CHECK (
    (content IS NOT NULL AND content_artifact_id IS NULL)
    OR (content IS NULL AND content_artifact_id IS NOT NULL)
  )
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_chk_doc_seq    ON kb_chunks(document_id, seq);
CREATE INDEX        IF NOT EXISTS idx_chk_namespace  ON kb_chunks(namespace);
CREATE INDEX        IF NOT EXISTS idx_chk_class      ON kb_chunks(classification);
CREATE INDEX        IF NOT EXISTS idx_chk_emb_model  ON kb_chunks(embedding_model);

-- KB Chunk 的 FTS5 索引（用于 hybrid 检索的 keyword 路径）
-- tokenize='trigram': 对中英文混合内容均能命中 substring 查询
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
-- 5. INGEST RUNS（审计与可恢复）
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
-- 6. AUDIT LOG（与 session.audit.log 同语义）
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
-- 7. 视图：检索辅助 / Helper view for hybrid retrieval
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
