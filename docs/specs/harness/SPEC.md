# Harness — 详细规范 / Detailed Spec

## 1. 对象模型 / Object model

```
Scenario（场景，例：ticket-summary、log-triage、runbook-gen）
  ├── Fixture[]   ── 输入快照（JSON），脱敏
  ├── Golden[]    ── 期望输出（JSON）；可空（适用于 rubric-only）
  ├── Rubric      ── 评分标准（markdown）；给 LLM-judge / 人工复核用
  └── EvaluatorCfg[] — 评估器配置

Run = (Scenario, Playbook[ver], Model[matrix], EvaluatorCfg[])
  → Result[]（每条对应一个 fixture × playbook × model）
  → Report（聚合：pass rate / cost / latency / regression delta）
```

## 2. ID 与命名约定 / IDs & naming

- `scenario_id` ：`scn_<slug>`，例 `scn_ticket_summary_zh`
- `fixture_id` ：`fix_<sha8>`（内容寻址），例 `fix_a1b2c3d4`
- `golden_id` ：`gold_<fix_sha8>`（与 fixture 配对）
- `playbook_ref` ：`<playbook_id>@<version>`
- `model_ref` ：`<provider_id>/<name>@<version>`，例 `anthropic-claude/claude-sonnet-4-6@2026-04`；详见 `providers/SPEC.md` §1.2。也可写 alias（如 `@chat-strong`），由 registry 解析后落库。
- `run_id` ：`run_<ULID>`

## 3. 评估器分类 / Evaluator types

| 类型 | 输入 | 判定 | 适用 |
|---|---|---|---|
| `rule.regex` | 输出文本 | 正则匹配/不匹配 | 关键字段必含、禁词 |
| `rule.json_schema` | 输出 JSON | schema 校验 | 结构化输出 |
| `rule.pii_check` | 输出文本 | 检测残留 PII | 合规底线 |
| `semantic.embedding` | 输出 vs golden | 余弦相似度阈值 | 语义近似 |
| `judge.llm` | 输出 + rubric | LLM 打分（带 judge 模型版本锁定） | 难以规则化的质量评估 |
| `sandbox.exec` | 输出（脚本） | 在 sandbox 跑 → exit_code/期望文件 | Runbook/脚本类输出 |
| `rag.recall_at_k` | retrieval 结果 vs ground truth document_ids | 命中数 / k | RAG 召回评估（见 `memory/`） |
| `rag.precision_at_k` | retrieval 结果 vs ground truth | 相关数 / k | RAG 精确评估 |
| `rag.citation_validity` | 输出含 citation | 引用是否能定位到 source_path:line_range | 杜绝"伪引用" |
| `human.review` | 输出 | 人工标注（外部录入） | 抽样质检 |

每种 evaluator 的配置 schema 见 `eval-config.template.yaml` 的 `evaluators:` 段。

### 3.1 LLM-judge 锁版本

为避免 judge 漂移：
- judge 模型必须指定具体版本（不允许 `latest`）
- judge prompt 必须 hash 锁定，写入 Result
- 建议 judge 与被评估模型为不同厂商，降低同向偏差

## 4. 指标 / Metrics

| 指标 | 定义 | 用途 |
|---|---|---|
| `pass_rate` | 通过 fixture 数 / 总 fixture 数 | 总体质量 |
| `regression_delta` | 当前 - baseline pass rate | 回归门 |
| `cost_per_run` | sum(token cost) / fixtures | 成本对比 |
| `latency_p50/p95` | 端到端延迟分位 | 性能 |
| `evaluator_breakdown` | 各 evaluator 的命中率 | 定位失败类型 |
| `flakiness` | 同 fixture/model 多次重跑的方差 | 稳定性 |

## 5. 数据集版本 / Dataset versioning

- Fixture / Golden / Rubric 三类资产必须有 `version`（semver）与 `content_hash`（sha256）
- 改动需走 PR，CR 时显示 baseline diff
- 大文件（>1 MiB）走 LFS 或 DVC；小文件直接入 Git

## 6. CI 集成模式 / CI integration

```
on PR:
  → discover changed prompts/playbooks/fixtures
  → run harness on affected scenarios
  → enforce thresholds（pass_rate、regression_delta）
  → upload report.{md,html} as artifact
on schedule (nightly):
  → full matrix run
  → diff vs last green
  → notify on regression
```

退出码约定：
- `0`：所有阈值通过
- `1`：有 fixture 失败但未触发回归门
- `2`：触发回归门（merge blocker）
- `64`：harness 内部错误

## 7. Result 与 Report / Output contracts

- 单条结果：`schemas/eval-result.schema.json`
- 一次 Run 的 `results.jsonl` ：每行一条 result
- 报告：
  - `report.md` ：人类可读摘要 + 失败用例样本
  - `report.html` ：可选，带趋势图
  - `report.json` ：机器可读，符合 schema（待补）

## 8. 与外部 eval 框架的适配 / Adapter pattern

本仓库定义中立契约。具体执行可委托给：
- **promptfoo**（轻量 CLI，YAML 配置；适合个人/小团队）
- **OpenAI Evals**（更系统的 framework）
- **Inspect AI**（Anthropic 出品，更适合 agent/工具调用评估）

适配层职责（待实现，不在本目录）：
1. 读取 `eval-config.template.yaml` 风格配置
2. 翻译为目标框架的原生格式
3. 把目标框架的输出转回 `eval-result.schema.json`

## 9. Fixture 来源建议 / Fixture sourcing

合法来源（按优先级）：
1. **Session 脱敏后的 trace.jsonl** —— 最贴近真实
2. **手工构造的边界用例** —— 覆盖 corner cases
3. **公开数据集**（带许可声明）—— 用于跨团队对比
4. **合成数据**（LLM 生成）—— 仅用于压力测试，不用于回归 baseline

红线：
- ❌ 未脱敏的工单/日志/客户对话直接入库
- ❌ 含真实 PII / 凭证 / 内部域名 / IP

## 10. 强约束 / Hard requirements

- Fixture 必须脱敏，且通过 `rule.pii_check` 自检
- Golden 与 Rubric 至少存在其一（不允许 fixture 无任何评判依据）
- 任何 evaluator 都必须可重跑（确定性）或显式标注 `nondeterministic: true`
- Run 结果必须包含模型版本、judge 模型版本、prompt hash、playbook 版本、fixture 版本——一项都不能缺
