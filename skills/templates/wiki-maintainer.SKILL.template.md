---
# Wiki Maintainer skill — 把 wiki ingest / query→page / lint 三类操作打包为一个 OpsPilot skill
# 与 schemas/skill.schema.json 等价
# 这是把 wiki/ 目录下的 operations 接入 skills 框架的 example skill

name: "wiki-maintainer"
description: "Maintain the OpsPilot wiki: ingest new sources into structured pages, convert high-quality session answers into wiki pages, and run periodic lint to surface contradictions, stale claims, orphan pages, and missing concept pages. Trigger when user asks 'add this to wiki', 'lint the wiki', 'update wiki from this session', or on scheduled cron."
version: "1.0.0"
language: "mixed"

author: "vicente@example.com"
source: "self_authored"
license: "MIT"

model_compat:
  - "@chat-strong"
  - "anthropic-claude/claude-sonnet-4-6@2026-04"

requires:
  tools:
    - "kb.search"                   # 检索既有 wiki page + KB raw source
    - "kb.write"                    # 把 page 注册回 KB
    - "memory.add"                  # 在 mid-term memory 留下 maintenance 决策
    - "artifact.write"              # 写 page 文件 + lint patch
  mcps:
    - "fs-readonly"                 # 读 wiki 目录树（list_directory + read_file）
  providers:
    tools: true
    json_mode: true
    long_context_tokens: 100000     # wiki 全量扫需要长上下文
  skills: []

safety:
  classification: "internal"
  approval_required: true           # 默认每次 apply 都需用户 approve（保守）
  telemetry_optout: true
  pii_allowed: false

inputs:
  schema_ref: "wiki/schemas/wiki-page.schema.json"
  description: "Operation kind (ingest|query_to_page|lint) + specific input refs (doc_id / session_id / scan window)"
outputs:
  schema_ref: "wiki/schemas/lint-issue.schema.json"
  description: "For lint: issues list. For ingest/query_to_page: page diff manifest + register-back-to-KB plan."

redacted: true
redaction_rules_version: "1.0.0"

tags: ["wiki", "maintenance", "lint", "ingest"]
labels:
  team: "service-desk"
  routing_target_for: "wiki_lint_issue"

extensions:
  wiki_ops_supported:
    - "ingest"
    - "query_to_page"
    - "lint"
  recipes:
    ingest: "wiki/templates/ingest-recipe.template.yaml"
    query_to_page: "wiki/templates/query-to-page-recipe.template.yaml"
    lint: "wiki/templates/lint-recipe.template.yaml"
---

# Wiki Maintainer

## 触发条件 / When to use

满足以下任一时调用：

- 用户显式说"加进 wiki"、"扫一下 wiki"、"把这个 session 写进 wiki"
- session 结束 + judge.llm 评分 ≥ 0.85 + user_action.accept → 候选 query→page
- 周期 cron（默认每周一）→ 跑 lint
- 收到 `wiki_lint_issue` feedback signal（来自上次 lint）→ 启动 iteration 改进 wiki

## 操作 / Operations

按 `inputs.operation` 字段路由：

### `ingest`
1. 读取 `wiki/templates/ingest-recipe.template.yaml`
2. 用 `kb.search` 找受影响的既有 page（top_k=12，hybrid + rerank）
3. LLM 提议 page 变更 + 新建 page（≤15 页/单次）
4. 跑静态校验（schema / pii / no_prompt_injection / links_resolvable / no_orphan）
5. 按 classification + source_trust 矩阵决定 review 模式
6. apply：写文件 + 计算 page_id + 重建 outbound_links + update index + append log
7. 把 live page 注册回 memory KB（`kind: "wiki_synthesis"`）

### `query_to_page`
1. 从 session 抽 final response + KB chunks + user edits
2. 判定 page kind（synthesis / comparison / summary）
3. 生成草稿；防 duplicate（embedding 相似度 ≥0.90 → 改为 update 旧页）
4. 强制人工 review（safety floor）
5. 默认入 draft，approve 后才进 live + KB

### `lint`
1. 读取 `wiki/templates/lint-recipe.template.yaml`
2. 跑 10 类检查（contradiction / stale / orphan / missing_concept / missing_cross_ref / duplicate / broken_link / data_gap / redaction_warning / schema_invalid）
3. 每条 issue 写到 `wiki/_lint/issues.jsonl`
4. 转为 feedback_signal type=`wiki_lint_issue` 注入 skills iteration
5. **绝不自动 apply**

## 强约束 / Hard rules

- **Lint never applies**：只产 issues + candidate patches；apply 必须经 ingest / query_to_page 流程
- **PII 静态扫描**：每次 page 写入前必走 redaction；hard-fail 即拒绝
- **No prompt injection in body**：加载/写入时静态扫描注入模式
- **Single-concept-per-page**：发现 duplicate_concept → 报 issue 建议合并；不允许新建第二个同概念 page
- **Cross-link or orphan**：新建 page 必须有 ≥1 inbound 候选 link，否则进 lint orphan 队列
- **Approval default ON**：safety.approval_required=true；用户可在 tool-binding 中按操作类型分别松绑

## 失败处理 / Failure modes

- ingest 中 schema 校验失败 → 整批回滚，写 audit + 触发 wiki_lint_issue
- query_to_page 命中 duplicate → 自动转为"建议 update 旧页"，不新建
- lint 过预算 → 中断 + 报 partial result + 进 iteration 候选

## Resources

- `resources/page-style-guide.md` —— 写作风格指南（与 wiki/CONVENTIONS.md 同步）
- `resources/lint-rules-watchlist.yaml` —— 关键术语监视表（用于 missing_concept_page 检测）
