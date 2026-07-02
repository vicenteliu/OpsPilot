# Wiki — 详细规范 / Detailed Spec

## 1. 设计原则 / Principles

1. **The wiki is the persistent compounding artifact**：每次 ingest 都让 wiki 更丰富，不是从零检索
2. **LLM owns writes, human owns curation**：LLM 写所有 page；人决定 ingest 什么、问什么、保留什么
3. **Cross-link is the value**：page 的价值在互链；orphan page 视为 lint issue
4. **One concept = one page**：同一概念多个 page 是反模式（lint 会建议合并）
5. **Provenance always**：每个 page 必须能追溯到 raw source（`derived_from`）
6. **Wiki feeds back to KB**：page 注册回 memory，新查询会命中 synthesis（而不只是 raw chunk）

## 2. ID 与命名 / IDs & naming

- `page_id` = `wpg_<sha8>`（sha8 of canonical frontmatter+body）—— 内容寻址
- `slug` = 文件名（无后缀），全局唯一；用于跨页 link `[[<slug>]]`
- 路径约定：`wiki/pages/<kind>/<slug>.md`，如 `wiki/pages/entity/vpn-gateway.md`
- 命名空间：通过 frontmatter `namespace` 字段（与 memory 一致），不通过路径分隔

## 3. Page 数据模型 / Page model

### 3.1 五类 page

| kind | 必填 frontmatter 字段 | body 必备段 |
|---|---|---|
| `entity` | aliases、related_entities、related_concepts | "What is it" / "Key facts" / "Related" |
| `concept` | parent_concepts、related_entities | "Definition" / "Why it matters" / "Examples" |
| `summary` | source_doc_id、source_uri、ingested_at | "TL;DR" / "Key claims" / "Implications for our wiki" |
| `comparison` | subjects[]（≥2）、criteria[] | "Subjects" / "Comparison table" / "Verdict / when to use which" |
| `synthesis` | sources[]（≥2 source_doc_ids）、thesis | "Thesis" / "Evidence" / "Counter-evidence" / "Gaps" |

### 3.2 通用 frontmatter（所有 kind 共有）

权威定义：`schemas/wiki-page.schema.json`。

| 字段 | 必填 | 说明 |
|---|---|---|
| `page_id` | ✓ | wpg_<sha8> |
| `slug` | ✓ | 全局唯一 |
| `kind` | ✓ | enum 见 §3.1 |
| `title` | ✓ | 人类可读标题 |
| `summary` | ✓ | 一句话；用于 index.md 与 hover preview |
| `namespace` | ✓ | 与 memory 一致，例 `opspilot:public-kb` |
| `classification` | ✓ | public/internal/confidential/restricted |
| `language` | ✓ | en/zh-CN/mixed |
| `version` | ✓ | semver（page 自身的修订版本）|
| `created_at` | ✓ | RFC3339 |
| `updated_at` | ✓ | RFC3339 |
| `tags` | ✗ | 自由标签 |
| `aliases` | ✗ | 别名（用于跨页 link 命中）|
| `derived_from` | ✓ | { sources: [{kind,ref,sha256}], parent_pages: [page_id] } |
| `outbound_links` | ✓ | [page_id] —— 索引时机器维护 |
| `inbound_link_count` | ✓ | int —— 由 lint 计算回填 |
| `redacted` | ✓ | 必须 true |
| `redaction_rules_version` | ✓ | 与 session 同步 |
| `lifecycle_state` | ✓ | draft / reviewed / live / stale / archived |
| `owner` | ✓ | 维护责任人 |
| `extensions` | ✗ | 厂商/工具自定义 |

### 3.3 Body 约定

- 写法见 `CONVENTIONS.md`
- 必含 `## Sources` 段，列出 derived_from 的人类可读引用 + 定位（`source_path:line_start-line_end`，与 memory citation 同 schema）
- 必含 `## Cross-links` 段或在正文中用 `[[<slug>]]`
- 严格脱敏；不允许 `[REDACTED:` 占位泄漏到正文

## 4. Cross-links / 跨页引用

权威定义：`schemas/wiki-link.schema.json`。

```yaml
link_id: "wlk_<sha8>"
from_page: "wpg_..."
to_page: "wpg_..."
relation: "describes" | "contradicts" | "extends" | "supersedes" | "depends_on" | "compares" | "instance_of" | "see_also"
context_quote: "..."         # 简短摘录（≤120 chars，脱敏后）
created_at: "..."
created_by: "wiki-maintainer-skill@<version>"
```

约定：
- `[[<slug>]]` 在 body 中是规范写法；index 阶段解析为 wiki-link record
- `relation` 显式枚举；`see_also` 是默认（最弱关系）
- `contradicts` / `supersedes` 关系会自动产生 lint issue（候选 stale_claim）

## 5. 三类 Operations / Operations

### 5.1 Ingest

```
input: new raw source (already in memory KB as kb_document with doc_id)
        │
        ▼
[1] discover affected pages: kb.search + wiki.search → top-N existing pages
[2] propose page updates (LLM): patches per page，附 reason
[3] propose new pages: 若识别出新概念/实体/synthesis 机会
[4] redact + static check: PII / prompt-injection / orphan-creation check
[5] human review (mode by classification + trust):
       public/internal/self_authored → auto + audit
       confidential/restricted/community → human approve required
[6] apply patches: write pages + update index + append log
[7] register wiki updates back to memory KB:
       each updated page → kb_document(kind=wiki_synthesis, content_hash refresh)
       trigger memory.ingestion incremental sync
```

详细配置：`templates/ingest-recipe.template.yaml`。

### 5.2 Query → Page

不是所有 query 都要回写——回写有成本（占 KB 容量、需维护、可能引入冗余）。触发条件（任一即可）：

- session 结束时 user_action.accept 且 harness judge.llm 评分 ≥ 0.85
- session 内含 ≥ 2 次 kb.search（说明是综合性问题，回答有 synthesis 价值）
- 用户显式 pin（user_action 含 `pin_to_wiki`）

回写流程：
1. 取 session.trace 中的 final response 作为草稿
2. 抽取引用的 KB chunks → 转成 page 的 `derived_from.sources`
3. 选 page kind（默认 `synthesis`，特殊场景如对比类问题用 `comparison`）
4. 走 ingest recipe 的 review→apply 链路（不再单独走 distillation）

详细配置：`templates/query-to-page-recipe.template.yaml`。

### 5.3 Lint

输入：当前 wiki 全量；可选 + 最近 N 天的 ingest log + 最近 M 个 session。

输出：lint issues 列表（schema：`schemas/lint-issue.schema.json`）。

| issue_type | 检测方法（建议）| 默认严重度 |
|---|---|---|
| `contradiction` | 提取每页 "Key claims" → LLM 检查跨页一致性 | high |
| `stale_claim` | 新 raw source 与既有 page 声称的关键事实冲突 | high |
| `orphan` | inbound_link_count = 0（且不是 index/log）| medium |
| `missing_concept_page` | 跨页提及但无独立 page 的实体/概念，count ≥ N | medium |
| `missing_cross_ref` | 两页内容明显相关但无 link | low |
| `data_gap` | 用户多次问但 wiki/KB 都答不上 | medium |
| `duplicate_concept` | 多个 page 描述同一概念 | high |

每个 issue 必须可生成 `feedback_signal`（type=`wiki_lint_issue`）→ 注入 skills/iteration（详见 `feedback-signal.schema.json` 已新增条目）。

**Lint 不自动改页**——只产出 issues + 候选 patch。Apply 必须经人工或 wiki-maintainer skill 的 iteration 流程。

详细配置：`templates/lint-recipe.template.yaml`。

## 6. index.md / log.md

### index.md

按 kind + 主题分类组织。每条：
```
- [[<slug>]] — <one-line summary> · `<tag>` · classified <classification>
```

机器可解析（regex `^- \[\[(\S+)\]\] — (.+?) · `）。LLM 在每次 ingest 完成后追加 / 重排。

### log.md

append-only。每条：
```
## [<RFC3339-date>] <op> | <subject>
- by: wiki-maintainer-skill@<version>
- session_id: sess_...
- pages_touched: 12 (3 created / 9 updated / 0 archived)
- lint_issues_emitted: 0
- notes: <optional>
```

机器解析（`grep "^## \[" log.md | tail -N`）—— 与 LLM Wiki 原 idea 直接对齐。

## 7. 与 memory KB 的回灌 / Bi-directional with KB

每个 wiki page 在 lifecycle_state 转入 `live` 时，**自动作为新 KB doc** 注册到 memory：

```yaml
kind: "wiki_synthesis"             # kb-document 新增 kind 字段（向后兼容；缺省视为 raw_source）
source_path: "wiki/pages/<kind>/<slug>.md"
namespace: <继承 page.namespace>
classification: <继承>
content_hash: <wiki page sha256>
embedding_model: <KB 默认>
chunk_strategy: "headings_then_size"
extensions:
  wiki:
    page_id: "wpg_..."
    page_kind: "<kind>"
    page_version: "<semver>"
```

`kb.search` 默认同时检索 raw 与 wiki_synthesis；可通过 filter 限制（如调试时只看 raw）。

## 8. 安全 / Security

- redaction：与 session 同流；禁止 `[REDACTED:` 残留
- prompt-injection：page body 加载时静态扫描（与 skills 同 patterns）
- 禁止：page body 嵌入 `system_prompt:` / `<|im_start|>system` 等
- approval：`confidential` / `restricted` / `community trust` 来源的 ingest 强制审批
- audit：page 创建/更新/归档/lint apply 全部写 log；与 session/audit.log 双写

## 9. Lifecycle / 状态机

```
draft → reviewed → live → stale → archived
                     ↑       │
                     └───────┘ (lint 触发 stale → 修订后回 live)
```

- `draft`：刚生成；不进 index；不向 KB 注册
- `reviewed`：通过自动检查；可被 owner approve 进 live
- `live`：在 index + KB 中可见；正常被检索
- `stale`：lint 标记为过时；仍可见但带 banner；触发 iteration 候选
- `archived`：归档；不在 index；仅 audit 可见

## 10. 强约束 / Hard requirements

- page_id = sha8 of frontmatter+body；变更必须 bump version + 重算 page_id（旧 id 进 lineage）
- redacted=true 是入库前置
- restricted classification 不得被 query_to_page 自动回写
- lint 不自动 apply
- 所有跨页 link 都通过 `[[<slug>]]`，不允许 raw 路径
- page body 不允许嵌入 system prompt / role override

## 11. 与其他目录的接口 / Interfaces

| 上游 | 给 wiki 的输入 |
|---|---|
| `memory/long-term` | raw KB doc（ingest 源）+ retrieval（被 wiki 引用）|
| `session/` | trace.user_action.accept + judge.llm 评分（query→page 触发源）|
| `playbooks/` | 可作为 ingest 源（视作 raw markdown）|
| `governance/` | redaction / classification / approval policies |

| 下游 | wiki 提供的产物 |
|---|---|
| `memory/long-term` | wiki page 注册回 KB（kind=wiki_synthesis）|
| `skills/` | wiki_lint_issue feedback_signal 进 iteration trigger |
| `harness/` | 可加 evaluator：`wiki.coverage`（覆盖率）/ `wiki.consistency`（一致性）|
| `case-studies/` | live page 可归档为 case study（不替代）|

## 12. 扩展点 / Extension points

- 新增 page kind：`schemas/wiki-page.schema.json` enum 扩展 + 对应模板
- 新增 link relation：`schemas/wiki-link.schema.json` enum 扩展
- 新增 lint issue type：`schemas/lint-issue.schema.json` enum + lint-recipe.template
- 与外部工具集成：Obsidian Web Clipper（ingest 入口）/ Marp（page→slide 输出）/ Dataview（用 frontmatter 跑动态查询）
