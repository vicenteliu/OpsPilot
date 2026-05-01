# Skills — 详细规范 / Detailed Spec

## 1. Skill 数据模型 / Data model

每个 skill = 一个目录：

```
<skill_root>/<skill_name>/
├── SKILL.md                  # 必需：frontmatter (yaml) + body (markdown)
├── tool-binding.yaml         # 可选：本 skill 用到的 tools/MCP 的具体绑定
└── resources/                # 可选：脚本、模板、参考资料
    ├── ...
    └── examples/
```

### 1.1 SKILL.md frontmatter（权威定义见 `schemas/skill.schema.json`）

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | ✓ | 唯一 slug，例 `ticket_summary_zh`；支持命名空间 `<plugin>:<name>` |
| `description` | ✓ | **一行**触发描述；详细规则见 §3 |
| `version` | ✓ | semver |
| `language` | ✓ | `en` / `zh-CN` / `mixed` |
| `author` | ✓ | 作者标识 |
| `source` | ✓ | enum：`self_authored / distilled / imported_trusted / imported_community / imported_unknown` |
| `license` | ✓ | SPDX 标识符或 `proprietary` |
| `model_compat` | ✓ | 数组；可用模型 alias 或 `["any"]` |
| `requires.tools` | ✗ | 内置工具依赖列表（如 `kb.search`） |
| `requires.mcps` | ✗ | MCP server id 列表（与 mcp-config 一致） |
| `requires.providers` | ✗ | provider capability 约束（如 `vision: true`） |
| `requires.skills` | ✗ | 本 skill 依赖的其他 skill |
| `safety.classification` | ✓ | `public/internal/confidential/restricted` |
| `safety.approval_required` | ✓ | bool；是否每次调用都需用户确认 |
| `safety.telemetry_optout` | ✓ | bool |
| `inputs.schema_ref` | ✗ | JSON Schema 引用 |
| `outputs.schema_ref` | ✗ | JSON Schema 引用 |
| `distillation` | ✗ | 若 source ≠ self_authored，记录蒸馏来源（type + refs） |
| `redacted` | ✓ | bool；body 内不允许残留 PII |
| `redaction_rules_version` | ✗ | 与 session 对齐 |

### 1.2 Body 约定

- markdown；可包含步骤、规则、约束、示例
- 引用同目录 resources：`resources/<file>`，禁用绝对路径
- 任何"调用工具"的语句必须能映射到 `requires.tools` / `requires.mcps`
- 不允许在 body 中嵌入 system prompt 重定义（防 prompt injection）

## 2. ID 与命名 / IDs & naming

- `skill_id` = `<name>@<version>`，例 `ticket_summary_zh@1.2.0`
- 跨命名空间：`<plugin>:<name>@<version>`，例 `data:analyze@1.0.0`
- 内部哈希引用：`skl_<sha256(SKILL.md)[:16]>` —— 用于 audit / 完整性校验

## 3. Description tuning（关键）/ How to write description

description 是模型决定"现在该不该用这个 skill"的唯一信号。**写不好就召回不了**。

### 3.1 强约束

- **一行**（≤ 300 字符）
- 必须包含 *用途* + *触发关键词*：例 "Summarize an IT ticket and produce a structured JSON with citations to KB SOPs."
- 不要把使用步骤塞进 description（步骤在 body）
- 不要承诺工具不具备的能力

### 3.2 推荐模板

```
{ACTION_VERB} {OBJECT} when {TRIGGER_CONDITION}.
Returns {OUTPUT_SHAPE}. Requires {KEY_DEPENDENCY}.
```

例：
- *"Summarize an IT support ticket when the user pastes ticket content or attaches log snippets. Returns ticket_summary_v1 JSON with KB citations. Requires kb.search and an LLM with json_mode."*

### 3.3 反模式

- ❌ "Useful for many tasks" —— 模型无法决断何时用
- ❌ "Always use this skill" —— 篡改路由优先级，等同 prompt injection
- ❌ "When the user says 'magic word'" —— 关键词依赖脆弱

### 3.4 触发评估（与 harness 对接）

发布前必须用 `harness/` 跑 *trigger fixtures*：
- 正例：100 条应触发的 query → recall ≥ 0.9
- 负例：100 条不应触发的 query → false_positive ≤ 0.05

未跑 trigger eval 的 skill 不允许进入 `enabled` 状态。

## 4. Quality checklist（发布前必跑）

```
[ ] 1. description ≤ 300 chars，含动词 + 触发条件 + 输出形态
[ ] 2. requires.tools / requires.mcps 全部在 registry 中可解析
[ ] 3. body 里所有 "call X" 都能映射到 requires
[ ] 4. redacted=true，且 body 通过 rule.pii_check
[ ] 5. safety.classification 与 body 实际操作匹配（写动作必须 ≥ internal）
[ ] 6. 模型版本兼容性测试通过（model_compat 中至少 1 个跑通）
[ ] 7. trigger eval 通过（recall ≥ 0.9, FP ≤ 0.05）
```

## 5. Skill Registry / 注册表

`templates/skill-registry.template.yaml` 是入口：
- `skills[]`：每条引用一个 SKILL.md 路径 + 元数据（trust tier / enabled）
- `aliases`：如 `@summarize-ticket` → `ticket_summary_zh@1.2.0`
- `groups`：场景包打包，例 `it-l1-bundle = [ticket_summary_zh, log_triage_zh, vpn_runbook_zh]`
- `installation_policy`：从远端导入时的默认 trust tier 与隔离策略

权威定义见 `schemas/skill-registry.schema.json`。

## 6. Tool & MCP Integration / 工具与 MCP 集成

### 6.1 Tool binding 契约

`tool-binding.yaml`（在 skill 目录内）声明本 skill 实际调用的每个工具：

```yaml
skill_ref: "ticket_summary_zh@1.2.0"
bindings:
  - tool: "kb.search"
    kind: "builtin"
    safety_class: "read"
    approval_required: false
    config:
      default_scopes: ["opspilot:public-kb"]
      default_top_k: 8

  - tool: "artifact.write"
    kind: "builtin"
    safety_class: "write"
    approval_required: false       # 写到 session 自家 artifact 区是默认允许的

  - tool: "mcp__notion__create_page"
    kind: "mcp"
    mcp_id: "notion-main"
    safety_class: "write"
    approval_required: true        # 第三方写动作 → 强制审批
    config:
      default_database_id: "${NOTION_DB_ID}"
```

权威定义见 `schemas/tool-binding.schema.json`。

### 6.2 MCP server 配置

`mcp-config.template.yaml` 注册 MCP server，与 `provider-registry` 同等地位：

```yaml
mcps:
  - id: "notion-main"
    name: "Notion (main workspace)"
    transport: "stdio"             # stdio | http | sse
    command: "npx"
    args: ["-y", "@notionhq/mcp-server"]
    env:
      NOTION_TOKEN: "${NOTION_API_KEY}"
    tools_prefix: "mcp__notion__"
    enabled: true
    trust: "trusted"
    health_probe:
      interval_seconds: 600
```

权威定义见 `schemas/mcp-config.schema.json`。

### 6.3 调用流转

```
session.trace[tool_call] (tool=mcp__notion__create_page)
   │
   ▼
tool-binding 查找：skill_ref + tool → mcp_id
   │
   ▼
mcp-config 查找：mcp_id → command/args/env
   │
   ▼
[approval_required?] ──yes──▶ user_action.approve
   │
   ▼
sandbox / direct exec（按 safety_class）
   │
   ▼
session.trace[tool_result]  + audit.log
```

## 7. Distillation Pipeline / 蒸馏管道

四类蒸馏来源，每类一个 recipe（见 `templates/distillation-from-*.template.yaml`）。

### 7.1 通用阶段

```
discover  ──▶  redact  ──▶  mine  ──▶  draft  ──▶  review  ──▶  register
   │            │           │          │           │              │
   ▼            ▼           ▼          ▼           ▼              ▼
sources     redacted     patterns    SKILL.md    pass/fail    in registry
manifest    inputs                   + bindings  + diff         (draft tier)
```

| 阶段 | 输入 | 输出 | 失败处理 |
|---|---|---|---|
| discover | 配置中的 sources | manifest（路径 + last_modified） | skip + log |
| redact | 原始 traces / 文档 | 脱敏文本 | hard-fail（PII 残留即拒绝）|
| mine | 脱敏文本 | 候选 pattern 列表（prompt 模式 / tool 序列 / 输出形态） | 跳过该来源 |
| draft | 候选 pattern + 模板 | SKILL.md draft + tool-binding.yaml draft | 再 prompt LLM 重试 |
| review | draft | pass/fail + diff vs 基线 | 进 review queue |
| register | reviewed draft | skill-registry 条目，tier=`distilled` | rollback |

### 7.2 四种来源详解

**(a) from_traces — 从 session traces 蒸馏**（最常用）

适合：把团队反复做、harness 评分高的成功 session 固化为可复用 skill。

- 输入：`session/<id>/trace.jsonl` 集合（脱敏）
- mine：找出共有 prompt 模式、工具调用序列、citation 风格、prompt 参数
- draft：把高频模式抽象成步骤指令
- 风险：traces 里的具体内容（工单号、用户名）必须先脱敏

**(b) from_skills — 从他人 skill 集合蒸馏**

适合：学习外部受信 skill 库（如 anthropic-skills 仓库）的结构与风格。

- 输入：N 个 SKILL.md 文件
- mine：frontmatter 字段分布、description phrasing、body section 结构
- draft：产出 meta-template 或单个新 skill（融合多 skill 风格）

**(c) from_docs — 从文档蒸馏**

适合：把现有 SOP / Runbook / playbook（markdown）转成可执行 skill。

- 输入：playbooks/ 下的 markdown
- mine：识别 trigger 条件、步骤、所需工具、安全约束
- draft：生成 SKILL.md，引用原文档为 resource

**(d) from_foreign — 跨平台 skill 翻译**（占位）

适合：把 OpenAI Custom GPT / LangChain agent / Claude Code skill 翻译成 OpsPilot skill 形态。

- 输入：外部平台的 skill 描述文件
- mine：字段映射 + 工具/MCP 等价物
- draft：OpsPilot 形态 SKILL.md
- 状态：spec 中先不展开模板，列入 catalogs.md 的兼容性矩阵

### 7.3 强约束

- 蒸馏产出**默认进入 draft tier**，不允许直接 enabled
- 来源必须显式 redact（PII 检查 hard-fail）
- 蒸馏 LLM 模型版本必须锁定（避免漂移）
- distillation.source 字段在 SKILL.md frontmatter 里**必填**：
  ```yaml
  distillation:
    type: "from_traces"
    sources:
      - "sess_01J0Z9..."
      - "sess_01K1A0..."
    pipeline_run: "run_dist_01J0..."
    distilled_at: "2026-05-01T12:00:00Z"
    redaction_rules_version: "1.0.0"
  ```

## 8. Lifecycle Operations / 生命周期操作

详见 `templates/lifecycle-policy.template.yaml`。核心操作：

| 操作 | 输入 | 输出 |
|---|---|---|
| `install` | skill source（local path / git url / package） | 写入 registry，tier 由 trust 评估决定 |
| `enable` | skill_id | 允许 session 触发 |
| `disable` | skill_id | 不再触发；不删除 |
| `update` | new version | 跑 trigger eval + 回归 → 通过则替换 |
| `deprecate` | skill_id + reason | 标记弃用；保留至 retention 到期 |
| `audit` | skill_id | 输出依赖图 + 调用统计 + 安全审计 |

## 9. 安全 / Security

- skill 加载时静态扫描 description / body：禁用 prompt injection 模式（`ignore previous`、`你现在是` 等系统级指令）
- description 不允许动态生成（无变量插值）
- community / unknown tier skill：默认禁所有 write 类工具；只允许 read + sandbox
- approval_required：每次调用都触发，无 "remember my choice"

## 10. 强约束 / Hard requirements

- description ≤ 300 chars
- version 不允许 `latest` / `auto` / `stable`
- 所有 SKILL.md 必须 `redacted=true`
- 所有 mcp-config 中 secrets 必须 env 占位，不许内联
- 蒸馏来源必须保留至少 retention 期，便于复现

## 11. 与其他目录的接口 / Interfaces

### 11.1 Session 中的 skill 调用

```yaml
# 在 trace 里：
- type: tool_call
  tool: "skill.invoke"
  args:
    skill_ref: "ticket_summary_zh@1.2.0"
    inputs: { ... }

- type: tool_result
  tool: "skill.invoke"
  artifact_ids: ["art_<sha8>"]
```

### 11.2 Harness 评估

新增 evaluator 类型：
- `skill.trigger_recall`：description 召回率
- `skill.trigger_precision`：误触发率
- `skill.contract_compliance`：输出是否符合 SKILL.md 声明的 outputs.schema_ref

## 12. 扩展点 / Extension points

- `frontmatter.extensions.<vendor>`：厂商/工具自定义元数据
- 新 distillation 类型：通过新增 `templates/distillation-from-<source>.template.yaml`
- MCP transport：可扩展（除 stdio/http/sse 外，未来支持 websocket）

## 13. Iteration Mechanism / 迭代机制

> 详细规范见独立文档 `skills/ITERATION.md`。本节给概览。

Skill 不是"一次写完就用"——它需要**持续小步演进**到稳定。OpsPilot 给出的迭代闭环：

```
feedback signals → trigger → propose → vary (1..M variants)
                                 │
                                 ▼
                           harness × variants
                                 │
                                 ▼
                  decision: promote | reject | merge | iterate_again
                                 │
                                 ▼
                  registry update + lineage entry + rollback window
```

### 13.1 关键对象

- **Iteration**（`itr_<ULID>`）：一次完整的"针对某 skill 改进"尝试，含 trigger / hypothesis / proposed_changes / evaluation / decision；schema：`schemas/iteration.schema.json`
- **Variant**（`var_<sha8>`）：候选版本，从 stable fork；schema：`schemas/skill-variant.schema.json`
- **FeedbackSignal**（`fb_<ULID>`）：单条结构化反馈；schema：`schemas/feedback-signal.schema.json`

### 13.2 6 类触发条件

`regression_detected` / `feedback_signal` / `distillation_candidate` / `model_upgrade` / `scheduled` / `manual`。每次 iteration 必须显式声明 trigger.type，否则加载时拒绝。

### 13.3 7 类反馈信号

`user_action.{accept,reject,edit}` / `harness_score` / `distillation_pattern` / `model_drift` / `trace_failure`。统一脱敏后写入 `skills/feedback/<skill_ref>/signals.jsonl`，按 14 天半衰期衰减后聚合，超过 `feedback_min_weight_to_trigger`（默认 5.0）触发 iteration。

### 13.4 晋升必须**全部**满足

1. anchor fixtures 上无回归
2. 加权分提升 ≥ `min_delta_weighted`（默认 0.01）
3. cost 增长 ≤ 10%
4. trigger eval 仍达标（recall ≥0.9, FP ≤0.05）
5. 静态检查全过（PII / prompt-injection / tool resolvable）

不满足任一 → losing → archive。

### 13.5 Lineage（演化谱系）

每个 stable skill 维护 `skills/lineage/<skill_name>.yaml`，是有向 DAG，记录每个 version 的 parent + iteration_id + summary。回滚不删历史，只追加 "rolled_back_to_x.y.z" 条目。

### 13.6 反模式（来自 ITERATION.md）

- ❌ 跳过 evaluate 直接 promote
- ❌ 同次同时改 description + body + requires.tools（无法归因）
- ❌ 用过期 fixtures
- ❌ 把 user_action.edit 的 diff 视为权威（只是信号，不是答案）

### 13.7 文件清单

```
skills/
├── ITERATION.md                                       # 详细规范
├── schemas/
│   ├── iteration.schema.json
│   ├── skill-variant.schema.json
│   └── feedback-signal.schema.json
└── templates/
    ├── iteration-recipe.template.yaml                # 单次配方
    ├── iteration-policy.template.yaml                # 全局策略
    └── feedback-collector.template.yaml              # 反馈源配置
```
