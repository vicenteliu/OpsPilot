# Providers — LLM 提供方抽象 / Provider Abstraction

> **状态 / Status**：规范阶段（spec-only）。本目录只定义 provider 配置契约、注册表与模型清单；不含运行实现。
> **Stage**：spec only — provider config contracts, registry, and model catalogs. No runtime here.

## TL;DR
Providers（提供方）= 让 OpsPilot 同一个 Session/Playbook 可以**无改动**地切换底层 LLM。本目录定义 6 类受支持的 provider：

| Provider | 类型 | 默认 endpoint | 主要价值 |
|---|---|---|---|
| **Ollama** | 自托管 / 本地 | `http://localhost:11434` | 内网 / 离线 / 数据不出网 |
| **OpenRouter** | 聚合网关 | `https://openrouter.ai/api/v1` | 一把 key 接百模；做降级 |
| **OpenAI API** | 云 | `https://api.openai.com/v1` | 工具调用 / vision / 结构化输出 |
| **Anthropic (Claude API)** | 云 | `https://api.anthropic.com/v1` | 长上下文 / prompt caching / computer use |
| **Google Gemini API** | 云 | `https://generativelanguage.googleapis.com/v1beta` | 多模态 / 超长上下文 / Vertex AI 备选 |
| **xAI Grok API** | 云 | `https://api.x.ai/v1` | OpenAI 兼容 / live search |

> ⚠️ **信息时效**：endpoint、模型名、定价由各厂商单方面变更。本仓库内所有具体值均标注信息日期；**部署前请核验官方文档**。详见 `catalogs.md`。

## 设计原则 / Principles

1. **Default deny on cost / 成本默认收紧**：每个 provider 必须配 `monthly_budget_usd`，超出阈值默认阻断而非告警
2. **Secrets out-of-tree / 密钥不入库**：API key 一律走 `${ENV_VAR}` 占位；具体值由 secrets broker 注入
3. **Pluggable / 可替换**：上层（session / harness）只引用 `provider_id`，不与具体厂商耦合
4. **Capability-aware routing / 按能力路由**：playbook 声明所需能力（tools/vision/long_ctx），registry 按能力筛选可用 provider
5. **Audit-friendly / 可审计**：每次调用必须把"实际命中的 provider 配置 hash + 模型版本"写回 Session

## 选型决策树 / Selection decision tree

```
是否要数据不出网？──▶ 是 ──▶ Ollama（默认本地 + 自托管 GPU）
        │
        否
        ▼
是否要"一把 key 接多家"？──▶ 是 ──▶ OpenRouter（适合做降级链）
        │
        否
        ▼
能力优先：
  ├─ 工具调用 / 结构化输出 / 复杂 agent  → OpenAI 或 Anthropic
  ├─ 长上下文 / 多模态                   → Anthropic 或 Gemini
  ├─ 实时信息 / 联网检索                 → Grok（live search）
  └─ 通用 / 成本敏感                     → 各家入门档（开 budget cap）
```

## Routing 策略 / Routing strategies

`provider-registry.template.yaml` 支持四种策略，**任选其一**：

1. **fixed**：每次都用指定 provider —— 默认；最易审计
2. **fallback**：主 provider 失败/限流 → 自动切备 —— 适合在线工单流
3. **capability**：按 playbook 声明的 capability 筛选 —— 适合多 playbook 共用
4. **cost-aware**：在满足 capability 的候选里挑 token 单价最低的 —— 适合批量评估

> 💡 **建议**：生产路径默认 `fixed`，仅在 harness 与降级链上启用其他策略。多策略叠加会显著增加复现难度。

## 网关选项（避免逐家接） / Gateway options (skip per-provider wiring)

如果不想写 6 份 provider 配置，可走以下网关：

| 网关 / Gateway | 性质 | 适合 |
|---|---|---|
| **OpenRouter** | 商业聚合 | 个人 / 小团队；天然降级 |
| **LiteLLM proxy** | 开源 OpenAI 兼容代理（自托管） | 内网 / 多团队共用 / 成本审计 |
| **Portkey / Helicone** | 商业可观测网关 | 需要请求日志、成本仪表板 |

走网关时，本仓库的"6 个 provider 配置"压缩为"1 个 OpenAI 兼容 provider"，但 `model` 字段仍要明确标注真实底层模型（用于审计）。

## 安全红线 / Hard nos

- ❌ 不在仓库提交真实 API key（`.gitignore` 已含 `.env`，但 secrets 务必走 broker）
- ❌ 不为 sandbox 提供 LLM API key（sandbox 内不应直接调 LLM；调度由上层完成）
- ❌ 不允许 provider 配置在运行时被 prompt 内容修改（防 prompt-injection 改路由）
- ❌ 不让"自托管 Ollama" 与"敏感数据出云"在同一 playbook 中混跑（数据分级隔离）

## 与其他目录的契约 / Contracts

| 上游 | 给 providers 的输入 |
|---|---|
| `governance/` | budget cap、数据分级路由约束、telemetry 关闭策略 |
| `playbooks/` | 所需 capability（声明式） |

| 下游 | providers 提供的产物 |
|---|---|
| `session/` | model_ref（写入 trace + meta）+ provider_config_hash（写入 audit） |
| `harness/` | 模型矩阵（多 provider 跨 fixture 跑） |

## 目录结构 / Directory layout

```
providers/
├── README.md                         # 本文件
├── SPEC.md                           # 抽象契约
├── catalogs.md                       # 已知模型清单（带核验日期）
├── schemas/
│   └── provider-config.schema.json
└── templates/
    ├── provider-registry.template.yaml
    ├── ollama.config.template.yaml
    ├── openrouter.config.template.yaml
    ├── openai.config.template.yaml
    ├── anthropic.config.template.yaml
    ├── gemini.config.template.yaml
    └── grok.config.template.yaml
```

## 开放问题 / Open questions

- [ ] Vertex AI（Gemini 的 GCP 通道）是否独立成 provider，还是作为 gemini.deployment_mode 字段？
- [ ] Azure OpenAI（部署名 + region）是否需要单独 template，还是 OpenAI 复用 + `deployment_mode: azure`？
- [ ] 本地 vLLM / TGI（OpenAI 兼容自托管）是否合并到 ollama 模板还是独立？
- [ ] Prompt caching / context caching 在不同厂商下计费差异如何在 SPEC 中表达？
