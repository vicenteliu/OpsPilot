# Skill Catalogs — 已知来源与跨平台兼容性 / Known Sources & Cross-platform Compatibility

> ⚠️ **信息时效**：截至 **2026-05-01**。Skill 平台与字段在快速演化；使用前请按官方文档核验。

## 1. 已知 Skill 来源 / Known sources

| 来源 / Source | 类型 | 默认信任 / Default trust | 备注 |
|---|---|---|---|
| 本地作者（OpsPilot 仓库内）| local | `self_authored` | 默认 trust |
| `anthropic-skills/`（pdf, docx, pptx, xlsx, skill-creator 等）| Anthropic 官方 | `imported_trusted`（人工审计后）| 单文件 SKILL.md 形态 |
| Claude Code plugins（含 skills + commands + MCP）| Anthropic 官方 + 社区 | 视作者源决定 | 含 plugin 命名空间 |
| 第三方公开 skill 仓库（GitHub）| 社区 | `imported_community` | **必须**走 community tier |
| 私有团队仓库 | 团队内部 | `imported_trusted` | 通过白名单识别 |
| 外部平台导出（OpenAI GPTs / LangChain agents 等）| 跨平台 | `imported_unknown` | 走 `from_foreign` 蒸馏；产物再升 tier |

## 2. 跨平台 skill 形态对比 / Cross-platform comparison

| 维度 | OpsPilot Skill | Anthropic Skill | Claude Code Plugin | OpenAI Custom GPT | LangChain Agent |
|---|---|---|---|---|---|
| 单元 | SKILL.md + resources | SKILL.md + resources | plugin.json + skills/ + commands/ + mcps/ | JSON config + Actions | Python class |
| 触发机制 | `description` (≤300 chars) | `description` | description / 显式调用 | system prompt + descriptions | tool-name match |
| 工具声明 | `requires.tools / .mcps` | 隐式（在 body 描述）| explicit MCP server config | OpenAPI Actions schema | `Tool` 子类 |
| 安全分级 | `safety.classification` 显式 | 暂无原生字段 | 视 plugin manifest | 平台审核 | 自实现 |
| 输出 schema | `outputs.schema_ref` 可选 | 无 | 无 | OpenAPI response schema | 自定义 |
| 蒸馏支持 | 原生（4 类来源）| 无 | skill-creator 工具支持单条 | 无 | LangSmith 抓 trace |
| 版本锁定 | semver + checksum | 无 | git ref | 平台维护 | pip 版本 |

字段映射（用于 `from_foreign` 蒸馏）：

```
OpenAI GPT.instructions       → SKILL.md.body
OpenAI GPT.name              → SKILL.md.frontmatter.name (slugified)
OpenAI GPT.description       → SKILL.md.frontmatter.description (truncate 300)
OpenAI GPT.actions[].schema  → SKILL.md.requires.tools (mapped) + tool-binding.yaml
OpenAI GPT.knowledge files   → SKILL.md.resources/

Claude Code skill SKILL.md   → 直接可读；扩展 frontmatter 字段即可
Claude Code commands/        → 当作 builtin tool 注册到 tool-binding.yaml
Claude Code mcps/            → 直接 import 到 mcp-config.yaml

LangChain Tool.name          → SKILL.md.frontmatter.name
LangChain Tool.description   → SKILL.md.frontmatter.description
LangChain Tool.run signature → tool-binding.yaml (kind=builtin or sandbox)
```

## 3. 已知 MCP server 推荐清单 / Recommended MCP servers

> 适合 IT 运维 / 工单 / 文档协作场景的常见 MCP，按本仓库 `mcp-config.template.yaml` 形态配置。

| MCP id 建议 | 用途 | 信任 | 关键约束 |
|---|---|---|---|
| `fs-readonly` | workspace 文件只读 | trusted | tools_allowlist 仅放行 read_file/list_directory |
| `git-readonly` | 读 git history、diff、blame | trusted | denylist push/force |
| `notion-main` | Notion 页面/数据库 | trusted | denylist delete_*；按需启用 |
| `slack-readonly` | 读 Slack 消息 | trusted（受合规约束）| compliance.pii_allowed=false |
| `jira-main` | 读写 Jira 工单 | trusted | denylist delete_issue / 清空 sprint |
| `gh-main` | GitHub repos / PRs / issues | trusted | denylist force-push / merge to main |
| `internal-search-http` | 内网检索服务 | trusted | data_residency 按本地合规 |
| `web-fetch-sandboxed` | 抓取公网内容 | community | 必须走 sandbox + 出网白名单 |

完整列表请参考 https://modelcontextprotocol.io/servers（信息日期 2026-05-01；使用前核验）。

## 4. 蒸馏来源选型矩阵 / Distillation source selection

| 你想要... | 推荐 distillation type | 推荐 LLM | 备注 |
|---|---|---|---|
| 把团队反复做的成功流程固化 | `from_traces` | hybrid（pattern_mining + Haiku） | 先脱敏，min_support=5 起步 |
| 学习行业 best-practice skill 风格 | `from_skills` | llm_distill (Sonnet) | 注意版权归属 |
| 把人写的 SOP / Runbook 转可执行 skill | `from_docs` | llm_distill (Sonnet) | 文档相对长，单价较高 |
| OpenAI GPTs / LangChain agent → OpsPilot | `from_foreign` | llm_distill (Sonnet) | spec 阶段未实现，列在 OQ |

## 5. 已知风险与缓解 / Known risks & mitigations

| 风险 | 缓解 |
|---|---|
| 蒸馏导致 traces PII 泄漏到 skill body | redact 阶段 hard-fail；二次 PII 扫描在 review 阶段 |
| description 被 prompt injection 篡改 | 加载时静态扫描注入模式（见 lifecycle-policy `static_checks`）|
| 第三方 skill 调用未声明的工具 | tool-binding `deny_on_unknown_tool: true` |
| MCP server 私钥泄漏 | env 占位 + `block_secrets_in_env_literals` |
| skill 升级引入回归 | `update.require_regression_eval: true`，掉 3% 阻断 |
| skill 之间循环依赖 | `requires.skills` 加载时做 DAG 校验 |

## 6. 维护约定 / Maintenance

- 该文档每 30 天复核一次（与 providers/catalogs.md 同周期）
- MCP 推荐清单与官方文档对齐，发现 deprecated 项标 `status: deprecated` 并给迁移路径
- 跨平台字段映射表如有变更，需同步更新 `from_foreign` 蒸馏 recipe
