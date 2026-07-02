# Provider Catalogs — 已知模型清单 / Known model catalogs

> ⚠️ **信息时效声明 / Freshness disclaimer**
> 本清单截至 **2026-05-01**。LLM 厂商单方面变更模型名、版本、定价、能力是常态。
> **使用前请逐条核验官方文档与 pricing 页**。当 catalog 与官方不一致时，以官方为权威，并把 drift 写入 audit。

## 字段约定 / Conventions

- `model_ref`：与 `providers/SPEC.md` §1.2 一致：`<provider_id>/<model>@<model_version>`
- `pricing`：每 1K tokens 美元（input / output / cached_input）
- `ctx`：上下文窗口（K = 1024 tokens）
- `caps`：能力速览（T=tools, V=vision, J=json, C=cache, R=reasoning, CU=computer_use, E=embeddings）
- `as_of`：信息日期；过期视为待核验

## 1. Ollama（本地）/ Local

> 取决于你 `ollama pull` 的具体模型；以下是常用 IT 场景候选（中英 + 通用 + 代码）。

| 模型 / Model | model_ref（示例） | ctx | caps | 备注 |
|---|---|---|---|---|
| Qwen 2.5 14B Instruct | `ollama/qwen2.5:14b-instruct@2024-09` | 128K | T J | 中文综合较好，4090 24G 可跑 q4 |
| Qwen 2.5 Coder 32B | `ollama/qwen2.5-coder:32b@2024-11` | 32K | T J | 代码 / runbook 生成 |
| Llama 3.1 8B Instruct | `ollama/llama3.1:8b-instruct@2024-07` | 128K | T J | 英文工单摘要、L1 入门 |
| Llama 3.3 70B | `ollama/llama3.3:70b@2024-12` | 128K | T J | 强综合；需 2× 80G 或 4× 24G |
| Mistral / Mixtral | `ollama/mistral:7b@2024-09` 等 | 32K | T J | 备选轻量 |
| LLaVA / Qwen2-VL | `ollama/llava:13b@2024-05` 等 | — | V | 视觉小模型 |
| nomic-embed-text | `ollama/nomic-embed-text@2024-02` | 8K | E | 自托管 embedding |

**核验路径**：`ollama list` / `ollama show <model>` / https://ollama.com/library

## 2. OpenRouter（聚合）/ Aggregator

> OpenRouter 不自有模型；它把上述各家模型路由出去。`model_ref` 写 OR + 真实底层模型。

| 路由形态 / Routed | model_ref（示例） | 说明 |
|---|---|---|
| Claude（经 OR） | `openrouter-main/anthropic/claude-sonnet-4-6@2026-04` | 用 OR 时仍要写真实底层名 |
| GPT-4o（经 OR） | `openrouter-main/openai/gpt-4o@2024-11-20` | |
| Gemini（经 OR） | `openrouter-main/google/gemini-2.5-pro@2025-03` | |
| Grok（经 OR） | `openrouter-main/x-ai/grok-3@2025-02` | |
| 本地 / Free 档 | `openrouter-main/meta-llama/llama-3.1-8b-instruct:free@2024-07` | 部分模型有 free tier，限速更严 |

**核验路径**：https://openrouter.ai/models（每模型卡片含 ctx / pricing / caps）

## 3. OpenAI

> ⚠️ OpenAI 模型快进化；下表给"截至 2025-05 的常见档位"，2026 新版必须按官方核验。

| 档位 / Tier | model_ref（示例） | ctx | caps | pricing input / output (per 1K) |
|---|---|---|---|---|
| 主力 | `openai-main/gpt-4o@2024-11-20` | 128K | T V J C R E | 0.0025 / 0.01（待核验） |
| 入门 | `openai-main/gpt-4o-mini@2024-07-18` | 128K | T V J | 0.00015 / 0.0006（待核验） |
| Reasoning | `openai-main/o1@2024-12-17` | 200K | T J R | 0.015 / 0.06（待核验） |
| Reasoning mini | `openai-main/o3-mini@2025-01-31` | 200K | T J R | 0.0011 / 0.0044（待核验） |
| Embedding | `openai-main/text-embedding-3-large@2024-01` | 8K | E | 0.00013 / —（待核验） |

**核验路径**：https://platform.openai.com/docs/models  +  https://openai.com/api/pricing

## 4. Anthropic (Claude API)

> Claude 命名形如 `claude-<family>-<gen>-<size>`，版本字符串多为日期格式（如 `2024-10-22`）或代号。**禁用 `latest`**。

| 档位 / Tier | model_ref（示例） | ctx | caps | pricing input / output (per 1K) |
|---|---|---|---|---|
| 主力 | `anthropic-claude/claude-sonnet-4-6@2026-04` | 200K | T V J C R CU | 0.003 / 0.015（待核验） |
| 顶配 | `anthropic-claude/claude-opus-4-6@2026-04` | 200K | T V J C R CU | 0.015 / 0.075（待核验） |
| 入门 | `anthropic-claude/claude-haiku-4-5@2025-10` | 200K | T V J C | 0.001 / 0.005（待核验） |
| 旧主力（备选） | `anthropic-claude/claude-3-5-sonnet@2024-10-22` | 200K | T V J C | 0.003 / 0.015（待核验） |

**特性提醒**：
- prompt caching：`cache_control` 标记 + `anthropic-beta` header（按文档）
- computer_use：仅部分 Sonnet 系列；需特定 beta header
- extended thinking：部分模型；通过 `thinking` 参数

**核验路径**：https://docs.claude.com/en/docs/about-claude/models  +  https://www.anthropic.com/pricing

## 5. Google Gemini

> 接入路径分两条：Generative Language API（API key）/ Vertex AI（service account）。pricing 也分两套。

| 档位 / Tier | model_ref（示例） | ctx | caps | pricing input / output (per 1K) |
|---|---|---|---|---|
| 主力 | `gemini-main/gemini-2.5-pro@2025-03` | 1M+ | T V J C R E | 0.00125 / 0.005（≤128K 档位） |
| 快速 | `gemini-main/gemini-2.5-flash@2025-04` | 1M | T V J C E | 0.0003 / 0.0025（待核验） |
| 旧主力 | `gemini-main/gemini-1.5-pro@2024-09-24` | 2M | T V J C E | 0.00125 / 0.005 |
| Embedding | `gemini-main/text-embedding-004@2024-04` | 2K | E | — |

**特性提醒**：
- 长上下文跨档位计费：超过阈值（如 128K）单价翻倍，必须在 cost 估算时分档
- safety_settings：默认会阻断部分输出；评估场景请按需放宽（仍记录到 audit）
- context caching：需显式 `caches.create`；非 Anthropic 风格的隐式缓存

**核验路径**：https://ai.google.dev/gemini-api/docs/models  +  https://ai.google.dev/pricing

## 6. xAI Grok

| 档位 / Tier | model_ref（示例） | ctx | caps | pricing input / output (per 1K) |
|---|---|---|---|---|
| 主力 | `grok-main/grok-3@2025-02` | 128K | T V J R | 0.005 / 0.015（待核验） |
| 视觉 | `grok-main/grok-2-vision@2024-12` | 32K | T V J | 0.002 / 0.01（待核验） |
| 入门 | `grok-main/grok-2@2024-12` | 128K | T J | 0.002 / 0.01（待核验） |

**特性提醒**：
- live_search：实时检索能力；启用后输出可能含未审核外部内容（governance 视为高风险）
- 与 OpenAI SDK 兼容；切 `base_url` 与模型名即可

**核验路径**：https://docs.x.ai/docs/models  +  https://x.ai/api

## 选型速查 / Quick reference

| 我想要... | 推荐 |
|---|---|
| 数据完全不出网 | Ollama（qwen2.5 / llama 3.x / qwen-coder） |
| 一把 key 接百家 + 自带降级 | OpenRouter |
| 工具调用 + 结构化输出最稳 | OpenAI gpt-4o / Anthropic Claude Sonnet |
| 长上下文（>200K） | Gemini 2.5 Pro / Anthropic 长上下文档位 |
| 多模态（图片/PDF 截图） | Gemini 2.5 Pro / Claude / GPT-4o |
| Agent 与 computer use | Claude Sonnet（CU） |
| Reasoning 类难题 | OpenAI o1/o3 / Gemini thinking / Grok 3 reasoning |
| 实时信息 / 联网 | Grok（live search） |
| 评估 judge（与被测异厂） | 与"被测模型不同厂商"的入门档（如 Claude Haiku 测 GPT-4o） |

## 维护约定 / Maintenance

- 该文档建议**每 30 天**复核一次（设 `harness:` 跑回归时连带一起检查）
- 任何 `pricing` 变更必须改 `pricing_as_of` 字段
- 模型下线（厂商 deprecate）→ 在 catalog 中保留条目并标 `status: deprecated`，给迁移指引
- 新增模型 → 先入 catalog，再被 registry / aliases 引用
