# LanceDB Schema — 长期 KB 向量存储 / Long-term Vector Store

> **状态 / Status**：spec only。本文档描述 LanceDB 表结构与索引约定；具体建表 / 升级脚本在实现阶段产出。
> **版本 / Version**：1.0.0  ·  **信息日期**：2026-05-01

## TL;DR
LanceDB 只存"向量 + 检索必需的薄元数据"；**权威元数据在 SQLite**（`kb_chunks` 表）。两侧通过 `vector_id` ↔ `kb_chunks.vector_id` 一一对应。

## 设计原则 / Principles

1. **薄列原则 / Thin columns**：LanceDB 只存检索路径必需字段；详情走 SQLite join
2. **每 KB 一个数据集 / One dataset per KB**：路径 `${index_root}/lancedb/<kb_id>.lance/`，便于备份与回滚
3. **每 namespace 一个表（可选）/ Optional table-per-namespace**：超大 KB 可拆表，避免索引膨胀
4. **embedding 模型锁定 / Pin embedding model**：表创建时记录 `embedding_model` 与 `dim`；切换 = 新建表（不允许同表混向量空间）
5. **append-only ingestion + tombstone delete**：增量写入；删除走 `delete_obsolete_chunks` 清理过期 vector_id

## 主表：`chunks` / Primary table

| 列 / Column | 类型（PyArrow / Lance） | 说明 |
|---|---|---|
| `vector_id` | `string`，**主键** | 与 SQLite `kb_chunks.vector_id` 唯一对应；建议 `chk_<sha8>` 复用为 vector_id |
| `embedding` | `fixed_size_list<float32>[<dim>]` | 向量本体；`dim` 在表创建时锁定 |
| `document_id` | `string` | `doc_<sha8>` |
| `chunk_id` | `string` | `chk_<sha8>` |
| `namespace` | `string` | 例 `opspilot:public-kb` |
| `classification` | `string` | `public/internal/confidential/restricted` |
| `language` | `string` | `zh-CN/en/...` |
| `tags` | `list<string>` | 用于过滤 |
| `embedding_model` | `string` | `<provider_id>/<name>@<version>` |
| `created_at` | `timestamp[ms, tz=UTC]` | 入库时间（用于 TTL / 重建判断） |

> **不放在 LanceDB**：原文 content、heading_path、line offsets、source_path —— 这些走 SQLite。
> 这样能让 LanceDB 文件保持小，scan + ANN 更快；备份也更轻。

## 索引 / Indices

### ANN 向量索引

```yaml
ann:
  type: "ivf_pq"            # ivf_pq（默认） | hnsw（按 LanceDB 版本支持情况）
  metric: "cosine"          # cosine | l2 | dot
  num_partitions: 64        # 数据量经验值：N<10万→32, 10万~50万→64, 50万~200万→128
  num_sub_vectors: 96       # PQ 子向量数；常见 16/32/64/96
  refresh_after_upsert: false   # 大批量摄入完再 refresh
```

**经验**：
- IVF_PQ 适合 100K~10M 量级；构建快、内存友好；查询召回与 nlist/nprobe 相关
- HNSW 适合 < 1M 高 QPS 场景；构建慢但查询快
- 数据 < 50K 时 ANN 收益不明显；可改用 brute-force（LanceDB 默认 fallback）

### 标量过滤索引 / Scalar filter indices

LanceDB 在标量列上支持过滤。建议为下列列建 scalar index：

- `namespace`
- `classification`
- `language`
- `embedding_model`

（若 LanceDB 当前版本不支持显式 scalar index，则依赖 dataset 元数据 + 列式 scan；查询时把过滤前置）

## 数据目录布局 / On-disk layout

```
${index_root}/
├── lancedb/
│   └── <kb_id>.lance/                # LanceDB dataset
│       ├── _versions/                # Lance manifest（版本控制）
│       ├── data/*.lance              # 列式数据文件
│       └── _indices/<index_name>/    # ANN 索引文件
├── snapshots/
│   └── <ts>-<kb_id>/                 # 备份快照（可回滚）
└── manifest.jsonl                    # 摄入 manifest（与 SQLite ingest_runs 对齐）
```

`.gitignore` 必含：`*.lance/`、`lancedb/`、`snapshots/`。

## 增量同步语义 / Incremental sync

```
ingest 触发 ──▶ 比较 source_path + content_hash
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

LanceDB 对 `delete by predicate` 有原生支持；批量删除走单事务。

## 查询路径 / Query path

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
  enrich via SQLite.v_chunks_with_doc  (拿 source_path / line_range / heading_path)
        │
        ▼
  optional rerank (cross_encoder / llm)
        │
        ▼
  Response (含 citation)
```

## 表的版本与升级 / Versioning & upgrades

- **schema 字段新增**：兼容；旧行的新列默认 NULL/默认值
- **embedding 模型变更**：**不兼容**（向量空间不可比）；必须新建表，旧表保留至切换完成
- **dim 变更**：与 embedding 模型变更绑定，处理方式同上
- **metric 变更**：建议新建表；同表混 metric 行为未定义

升级流程（建议，spec 阶段先记录）：
1. 新建 `chunks_v2`，记录新 embedding_model
2. 全量重摄入到 `chunks_v2`（dry-run → 比对召回 → apply）
3. 流量切到 v2
4. 保留 `chunks_v1` 至少一个回滚周期（建议 30 天）
5. 确认无回滚 → 删除 v1

## 备份与回滚 / Backup & rollback

- **快照**：摄入前用 LanceDB 的 `version` API 标记当前 manifest 版本；或文件级 cp -al
- **保留**：默认保留最近 5 次快照
- **回滚命令（实现阶段）**：`opspilot kb rollback --kb <id> --snapshot <ts>` —— 还原 LanceDB manifest + SQLite snapshot 到同一时间点

## 性能注意 / Performance notes

- 大批量 upsert 时关闭 `refresh_after_upsert`，最后统一 refresh + optimize
- ANN 重建窗口建议放在低峰（cron 周日 05:00）
- 多 namespace 共表：用 scalar filter；超大时拆表
- 单 chunk 文本 inline ≤ 8 KiB；超过走 artifact，避免 SQLite 行膨胀

## 与 SQLite 的事务一致性 / Cross-store consistency

LanceDB 与 SQLite 是**两套存储**，没有原生分布式事务。处理：
- ingestion pipeline 在 §upsert 阶段采用"先写 LanceDB → 再写 SQLite"或反向，统一选一
- 单文档失败 → 两边一起回滚（按 vector_id / chunk_id 删除新增）
- 启动时跑一致性检查（`SELECT vector_id FROM kb_chunks` ↔ LanceDB scan）；不一致条目隔离到 quarantine

## 强约束 / Hard requirements

- 表创建时锁定 `embedding_model` 与 `dim`；不允许同表混
- `vector_id` 在 SQLite 与 LanceDB 之间一一对应；不允许孤儿
- `restricted` 分类的 chunk 不入向量库（只走 keyword + 受限命名空间）
- LanceDB 数据目录不入 git；markdown 源入 git
- 任何 schema 变更必须在 `schema_meta`（SQLite 侧）记录新版本
