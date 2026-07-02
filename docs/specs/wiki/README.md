# Wiki — LLM 持续维护的累积式 synthesis 层 / Compounding Synthesis Layer

> **状态 / Status**：规范阶段（spec-only）。本目录定义 wiki 的数据模型、operations、约定与模板；不含运行实现。
> **Stage**：spec only — page schema, ops contracts, conventions, templates. No runtime here.

## TL;DR
传统 RAG 每次问答都从原始 chunk **重新合成**——LLM 不积累。Wiki 反过来：每次 ingest 一份新源，LLM **写进**一组互链的 markdown 页，**未来任何问答都站在已合成的肩膀上**。OpsPilot 的 wiki 层叠在 `memory/long-term`（KB）之上，与 `skills/` 协作，把"知识"从"被动检索源"升级为"持续累积的 synthesis"。

## 与 LLM Wiki idea 的对应 / Mapping to the original idea

| LLM Wiki 概念 | OpsPilot 对应 |
|---|---|
| Raw sources（不可变） | `memory/long-term` KB 中的 `kb-document`（markdown 源 + LanceDB 索引）|
| **Wiki**（LLM 维护的合成层） | **本目录** `wiki/`：page 类型、cross-link、index、log |
| Schema 文档 | `wiki/CONVENTIONS.md`（与项目根 `CLAUDE.md` 配合）|
| `index.md` | `wiki/index.md`（按主题/类别索引）|
| `log.md` | `wiki/log.md`（chronological，与 session/audit.log 同语义）|
| Ingest | `wiki/templates/ingest-recipe.template.yaml`（在 memory.ingestion 之上叠一层 wiki update）|
| Query | 复用 `memory/templates/retrieval.template.yaml`，**+ 把好答案回写为新 page**（`query-to-page-recipe`）|
| Lint | **OpsPilot 新增能力**：检测矛盾 / 过时 / 孤立页 / 缺概念 / 缺交叉引用 / data gap |
| qmd 搜索 | 复用 memory 的 SQLite/FTS5 + LanceDB hybrid |

## 与其他目录的关系 / How it fits

```
                 raw docs (markdown / pdf / html / wiki export)
                        │
                        ▼
              ┌──────────────────────┐
              │  memory/long-term    │  KB ingest pipeline:
              │   (raw + chunks +    │  redact → chunk → embed → upsert
              │    LanceDB + SQLite) │  (passive retrieval source)
              └─────────┬────────────┘
                        │ retrieval (kb.search)
                        ▼
   ┌─────────────────────────────────────────────────────────┐
   │  wiki/  (LLM-maintained compounding synthesis)           │
   │   ├── pages/         entity/concept/summary/comparison/  │
   │   │                  synthesis pages — interlinked       │
   │   ├── index.md       content catalog                     │
   │   └── log.md         chronological ledger                │
   └─────────────────────┬───────────────────────────────────┘
                         │  wiki page itself becomes a KB doc:
                         │  registered into memory/long-term
                         │  → searchable from kb.search
                         ▼
                   harness / sessions / skills
                         │
                         ▼  lint findings → feedback_signal (wiki_lint_issue)
                   skills/iteration trigger
```

**核心不变量**：wiki page 是 KB 的一类特殊文档（`kind: "wiki_synthesis"`），**会被回灌到 memory KB** 用于检索——但它的修改权属于 wiki 维护流程，不是普通 ingest。

## Page 类型（5 类）/ Page taxonomy

每个 page 必须声明 `kind`，五选一：

| kind | 用途 | 例 |
|---|---|---|
| `entity` | 单一对象（系统、工具、团队、人物、产品） | `pages/entity/vpn-gateway.md` |
| `concept` | 抽象概念或主题 | `pages/concept/ipsec-vs-ssl-vpn.md` |
| `summary` | 单一来源的摘要（直接对应 1 个 raw source） | `pages/summary/sop-vpn-2026-04-28.md` |
| `comparison` | 多对象/方案对比 | `pages/comparison/radius-vs-ldap-auth.md` |
| `synthesis` | 跨源综合（最有价值） | `pages/synthesis/vpn-incident-patterns-2026q1.md` |

详细 frontmatter / body 约定见 `SPEC.md` §3 与 `CONVENTIONS.md`。

## Operations / 三大操作

### 1. Ingest

```
new raw source ──▶ memory.ingestion (chunks + vectors)  ──▶ wiki.ingest
                                                              │
                                                              ▼
              [LLM] read → propose updates to ≤15 pages
                                  │
                                  ▼
              human review (default for self_authored / restricted)
                                  │
                                  ▼
              apply: write/update pages + index + log
```

详见 `templates/ingest-recipe.template.yaml`。

### 2. Query → Page（compounding）

LLM Wiki 强调的关键："好答案要回写成新 page"。OpsPilot 实现：

```
session.user_action == "accept"  +  judge.llm score ≥ 0.85
                  │
                  ▼
   propose query_to_page conversion (recipe in template)
                  │
                  ▼
   draft synthesis page → review → register in wiki
                  │
                  ▼
   re-ingest into memory KB (kind=wiki_synthesis)
```

详见 `templates/query-to-page-recipe.template.yaml`。

### 3. Lint（OpsPilot 新增价值）

周期性扫描 wiki，输出结构化 lint issues：

| issue_type | 描述 |
|---|---|
| `contradiction` | 两页对同一事实的声明矛盾 |
| `stale_claim` | 旧页声称的内容被新 source supersede |
| `orphan` | 无入链的页面 |
| `missing_concept_page` | 被多次提及但没自己的 page 的概念 |
| `missing_cross_ref` | 应互链但没链 |
| `data_gap` | 可通过 web 检索补全的空白 |

每个 lint issue 转为 `feedback_signal` 中的 `wiki_lint_issue` 类型 → 触发 wiki-maintainer skill 的 iteration（与 skills/ITERATION.md 接通）。

详见 `templates/lint-recipe.template.yaml`。

## Index 与 Log

- `index.md`：内容索引；每条目格式 `- [[<page-slug>]] — <one-line summary> [tags]`
- `log.md`：append-only；每行格式 `## [YYYY-MM-DD] <op> | <subject>`，便于 `grep "^## \[" | tail -10`
- 两者由 LLM 自动维护，人工只读

详见 `templates/index.template.md` 与 `templates/log.template.md`。

## 安全与合规 / Safety & compliance

- **Redaction**：page 写入前必经 `session/templates/redaction-rules.template.yaml`；hard-fail PII 检查
- **Classification**：每个 page 必须声明 `classification`（与 KB 同分类体系）；`restricted` 类不得被 Query→Page 自动回写
- **Audit**：每次 page 创建/更新写入 `wiki/log.md` + 与 session/audit.log 同步
- **RBAC**：page 的 owner/collaborators 与 session 一致；`restricted` 类只能由 trusted skill 修改
- **Provenance**：page 必须记录 `derived_from`（raw source ids + 之前的 page versions）

## Wiki page 与 KB 的双向关系 / Bi-directional with memory KB

- Wiki page 在创建 / 更新后，**自动作为 kind=wiki_synthesis 的 KB doc 注册到 memory**——可被 `kb.search` 检索到
- 这意味着新的 query 也会命中 wiki 页（而不只是 raw source）——synthesis 越多，回答越站在历史合成的肩膀上 ✓
- KB ingest 的反向不存在：raw source 不会自动生成 wiki 页（必须经 ingest recipe + review）

## 反模式 / Anti-patterns

- ❌ 把 wiki page 当作通用文档目录（playbook / SOP 应放 `playbooks/`，wiki 是 LLM 累积的 synthesis）
- ❌ 在 page body 里嵌入 `<system_prompt>` / 试图改变 LLM 角色（与 skills 同样 forbidden）
- ❌ 让 wiki 直接指向 raw source 路径而不引用 KB doc_id（破坏 retention 与 redaction 约束）
- ❌ 同一概念建多个 page（lint 会发现并提议合并）
- ❌ Lint 自动 apply（lint 输出建议 / signals，不直接改页）

## 范围 / Scope

In scope（本目录）：
- Page 数据模型（kind / frontmatter / cross-link / lineage）
- 三类 operations 契约（ingest / query→page / lint）
- 与 memory / skills / session / harness 的接口
- Index + Log 约定

Out of scope：
- 具体 page 编辑器实现
- LLM agent runner 实现
- Obsidian 集成（建议但不强制）

## 目录结构

```
wiki/
├── README.md                                  # 本文件
├── SPEC.md                                    # 详细规范
├── CONVENTIONS.md                             # 编辑约定（schema 等价物）
├── schemas/
│   ├── wiki-page.schema.json
│   ├── wiki-link.schema.json
│   └── lint-issue.schema.json
└── templates/
    ├── entity-page.template.md
    ├── concept-page.template.md
    ├── summary-page.template.md
    ├── comparison-page.template.md
    ├── synthesis-page.template.md
    ├── index.template.md
    ├── log.template.md
    ├── ingest-recipe.template.yaml
    ├── query-to-page-recipe.template.yaml
    └── lint-recipe.template.yaml
```

## 开放问题 / Open questions

- [ ] Wiki page 升级时（用户改写 / lint apply）的 lineage：用 git history，还是单独 page-lineage YAML？
- [ ] `query-to-page` 的自动化阈值：判分多少才自动建议回写（vs 总让用户审）？默认建议 0.85
- [ ] 与 Obsidian Web Clipper / Marp / Dataview 的集成是否纳入官方推荐 stack？
- [ ] 多 wiki 实例（团队 / 项目 / 个人）如何共享 / 隔离 namespace？
