# Wiki Conventions — 编辑约定 / Editing Conventions

> 这是 wiki 的"schema 文档"——告诉 LLM **如何写、如何链接、如何归档**。改动这里 = 改动 LLM 的行为。
> 与 LLM Wiki 原 idea 中的 CLAUDE.md / AGENTS.md 等价。

## 1. 写作原则 / Writing principles

- **Compounding over completeness**：宁可页面短而互链密，也不要单页面试图穷尽
- **Cite or stay silent**：每个 claim 都要有 `derived_from` 或不写
- **Disagreements stay**：发现矛盾时，**两边都保留**，并加 `relation: contradicts` 链接 + 标记 `lint_issue`；不要悄悄选边
- **Stale beats wrong**：信息过时优于改成错的；标 stale，等下次 ingest 再修订
- **One concept = one page**：发现重复，建议合并 + 给迁移路径
- **No hidden state**：所有结论的依据都在 `Sources` 段；不要藏在 LLM 的"印象"里

## 2. 标题与 slug / Titles & slugs

- 标题：人类可读，含必要限定词（如"VPN 故障排查 SOP（中文）"而非"VPN SOP"）
- slug：小写、连字符分隔、ASCII；中英混内容可用拼音或英文
- 全局唯一；冲突时用 `<topic>-<qualifier>`（如 `auth-radius` vs `auth-ldap`）

## 3. Frontmatter 写法 / Frontmatter

- 必填字段全填；缺一不可
- `summary`：一句话，≤120 字符；用作 index.md 条目与 hover preview
- `derived_from`：永远列全；空数组只在"纯 LLM 生成"页（极少见，需标注 `extensions.synthetic: true`）
- `outbound_links` 与 `inbound_link_count` **由机器维护**，作者不手填

## 4. Body 结构 / Body structure

每类 page 的必备段（见 SPEC.md §3.1）。所有 page 共有的尾部段：

```markdown
## Cross-links

- describes → [[<slug-a>]]: <为什么相关，1 句>
- contradicts → [[<slug-b>]]: <冲突点，1 句>
- see_also → [[<slug-c>]]

## Sources

1. [<doc title>](<source_path>:<line_start>-<line_end>) — <relevance, 1 句>
2. ...

## Changelog

- v1.0.0 (2026-04-01): initial; from doc_xxxx
- v1.1.0 (2026-04-15): added contradicting evidence from doc_yyyy
```

## 5. Link writing / 写链

- 体内：`[[<slug>]]` 或 `[[<slug>|<display text>]]`（后者用于上下文需要不同显示文本时）
- 不允许：相对路径（`../entity/foo.md`）—— 机器无法跨重组目录解析
- `Cross-links` 段必须显式分组按 `relation`

## 6. Tone / 语气

- 客观陈述事实 + 标明置信度
- 推论用"基于 XX，可能..."（cite 必备）
- 不允许使用模型第一人称（"I think"、"我认为"）—— wiki 是事实记录，不是 LLM 的意见簿

## 7. Redaction（强约束）/ Redaction

- page body 任何位置不允许 `[REDACTED:` 占位符泄漏（即使在引用块内）
- 替代写法：用通用描述（"被影响的客户端主机"），不写 placeholder
- 任何字段都要过 `session/templates/redaction-rules.template.yaml`

## 8. Lint 自检清单 / Pre-publish lint checklist

每次 page 写好（或 ingest 改完）前，自检：

```
[ ] 1. frontmatter 通过 wiki-page.schema.json
[ ] 2. Sources 段非空（synthetic 例外）
[ ] 3. 至少 1 条 Cross-links（除非孤儿是预期，如 index / log）
[ ] 4. 体内每个 [[<slug>]] 在 wiki 中能找到对应页（或加 lint stub）
[ ] 5. redacted=true 且通过 PII 静态扫描
[ ] 6. classification 与内容匹配（写动作必须 ≥ internal）
[ ] 7. version 已 bump（如果是更新）+ Changelog 加条
```

## 9. Ingest 写作流程（给 LLM）/ Ingest writing flow

LLM 在 ingest recipe 中按以下顺序操作：

1. **读 raw source**（已脱敏后版本）；列 5-10 个关键 claims
2. **kb.search + wiki.search** 找已存在的相关页（top-10）
3. 对每个 claim：
   - 与某既有页重合 → 在该页加证据强化（更新 Sources + Cross-links）
   - 与某既有页冲突 → 在两边各加 `contradicts` 链接 + 触发 lint signal
   - 全新概念 → 草拟 entity / concept page
4. 是否值得做 synthesis 页？（≥ 2 sources 共同支持一个 thesis）
5. 更新 index.md
6. append log.md
7. 把所有变更打包提交 review

**单次 ingest 触及 page 数上限**：默认 15（与 LLM Wiki 原 idea 对齐）；超出说明 ingest 范围太大，应拆分。

## 10. Query → Page 写作流程

1. 取 session.final_response 与 session.trace 中引用的 KB chunks
2. 选 page kind：
   - 多源对比 → `comparison`
   - 多源综合论点 → `synthesis`
   - 单源摘要 → `summary`（罕见；通常 ingest 阶段已生成）
3. 用模板填充
4. 必填 `derived_from.sources` 列出所有引用的 doc_id + chunk_id
5. 如果是 `synthesis`，必填 `thesis` 段（一句话核心论点）
6. 走 ingest 后半段：review → apply → 注册回 KB

## 11. Lint 输出写作流程

LLM 在 lint 阶段：

1. 扫 wiki：跑各类型检查（contradiction / stale / orphan / missing_concept 等）
2. 每个 issue 写一条结构化 record（见 schema）
3. **不要直接改页**——只输出 issues + 候选 patch
4. issues 进入 `feedback_signal`（type=`wiki_lint_issue`）→ 触发 iteration

## 12. 反模式（强制不允许） / Anti-patterns

- ❌ "见 [[<slug>]]" 但 slug 不存在 —— lint 时记为 broken_link
- ❌ 在 Sources 段引用未脱敏原文（含 PII）
- ❌ 让 page 互相循环依赖（A 仅靠 B 解释，B 仅靠 A 解释）
- ❌ 同一概念三个 page —— lint 必报 duplicate_concept
- ❌ 在 body 写 "We should..." / "Decisions:..." —— wiki 是事实，不是 ops
- ❌ 把 session.trace 直接粘进 page —— 应抽象为 fact / claim 后引用
- ❌ 使用 absolute 链接到 raw source 路径，绕过 KB doc_id —— 破坏 retention

## 13. 与 Obsidian 集成（可选）/ Obsidian (optional)

- `wiki/pages/` 直接作为 Obsidian vault 子目录
- frontmatter 完全兼容 Obsidian + Dataview
- `[[<slug>]]` 是原生 Obsidian wiki-link 语法
- 推荐插件：Dataview（按 frontmatter 跑查询）、Graph view（看 wiki 形态）
- 推荐工作流：LLM 在一侧改，Obsidian 在另一侧实时浏览（与 LLM Wiki 原 idea 对齐）

## 14. 维护节奏 / Cadence

- **每次 ingest 完成**：自动更新 index + log
- **每周一**（或 cron）：跑 lint，输出 issues
- **每月**：review lint 累积 + 跑 iteration（与 skills/iteration-policy.scheduled_review_cron 协同）
- **每季度**：review wiki 整体结构、归档不再相关的 stale page
