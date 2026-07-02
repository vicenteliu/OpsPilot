# Provider Catalogs — Known model catalogs

> ⚠️ **Freshness disclaimer**
> This catalog is current as of **2026-05-01**. LLM vendors routinely change model names, versions, pricing, and capabilities unilaterally.
> **Verify every entry against the official docs and pricing pages before use**. When the catalog disagrees with the official source, the official source is authoritative; record the drift in the audit.

## Conventions

- `model_ref`: same as `providers/SPEC.md` §1.2: `<provider_id>/<model>@<model_version>`
- `pricing`: USD per 1K tokens (input / output / cached_input)
- `ctx`: context window (K = 1024 tokens)
- `caps`: capability shorthand (T=tools, V=vision, J=json, C=cache, R=reasoning, CU=computer_use, E=embeddings)
- `as_of`: information date; expired entries are considered pending verification

## 1. Ollama (local)

> Depends on the specific models you `ollama pull`; below are common candidates for IT scenarios (Chinese/English + general-purpose + code).

| Model | model_ref (example) | ctx | caps | Notes |
|---|---|---|---|---|
| Qwen 2.5 14B Instruct | `ollama/qwen2.5:14b-instruct@2024-09` | 128K | T J | Strong general Chinese; runs q4 on a 4090 24G |
| Qwen 2.5 Coder 32B | `ollama/qwen2.5-coder:32b@2024-11` | 32K | T J | Code / runbook generation |
| Llama 3.1 8B Instruct | `ollama/llama3.1:8b-instruct@2024-07` | 128K | T J | English ticket summaries, L1 entry level |
| Llama 3.3 70B | `ollama/llama3.3:70b@2024-12` | 128K | T J | Strong all-rounder; needs 2× 80G or 4× 24G |
| Mistral / Mixtral | `ollama/mistral:7b@2024-09` etc. | 32K | T J | Lightweight alternative |
| LLaVA / Qwen2-VL | `ollama/llava:13b@2024-05` etc. | — | V | Small vision models |
| nomic-embed-text | `ollama/nomic-embed-text@2024-02` | 8K | E | Self-hosted embeddings |

**Verification path**: `ollama list` / `ollama show <model>` / https://ollama.com/library

## 2. OpenRouter (aggregator)

> OpenRouter owns no models; it routes to the vendors above. Write `model_ref` as OR + the real underlying model.

| Routed | model_ref (example) | Notes |
|---|---|---|
| Claude (via OR) | `openrouter-main/anthropic/claude-sonnet-4-6@2026-04` | Even through OR, write the real underlying name |
| GPT-4o (via OR) | `openrouter-main/openai/gpt-4o@2024-11-20` | |
| Gemini (via OR) | `openrouter-main/google/gemini-2.5-pro@2025-03` | |
| Grok (via OR) | `openrouter-main/x-ai/grok-3@2025-02` | |
| Local / free tier | `openrouter-main/meta-llama/llama-3.1-8b-instruct:free@2024-07` | Some models have a free tier with stricter rate limiting |

**Verification path**: https://openrouter.ai/models (each model card includes ctx / pricing / caps)

## 3. OpenAI

> ⚠️ OpenAI models evolve fast; the table below lists "common tiers as of 2025-05"; 2026 releases must be verified against the official docs.

| Tier | model_ref (example) | ctx | caps | pricing input / output (per 1K) |
|---|---|---|---|---|
| Flagship | `openai-main/gpt-4o@2024-11-20` | 128K | T V J C R E | 0.0025 / 0.01 (pending verification) |
| Entry | `openai-main/gpt-4o-mini@2024-07-18` | 128K | T V J | 0.00015 / 0.0006 (pending verification) |
| Reasoning | `openai-main/o1@2024-12-17` | 200K | T J R | 0.015 / 0.06 (pending verification) |
| Reasoning mini | `openai-main/o3-mini@2025-01-31` | 200K | T J R | 0.0011 / 0.0044 (pending verification) |
| Embedding | `openai-main/text-embedding-3-large@2024-01` | 8K | E | 0.00013 / — (pending verification) |

**Verification path**: https://platform.openai.com/docs/models  +  https://openai.com/api/pricing

## 4. Anthropic (Claude API)

> Claude names follow `claude-<family>-<gen>-<size>`; version strings are usually date-formatted (e.g. `2024-10-22`) or codenames. **`latest` is forbidden**.

| Tier | model_ref (example) | ctx | caps | pricing input / output (per 1K) |
|---|---|---|---|---|
| Flagship | `anthropic-claude/claude-sonnet-4-6@2026-04` | 200K | T V J C R CU | 0.003 / 0.015 (pending verification) |
| Top tier | `anthropic-claude/claude-opus-4-6@2026-04` | 200K | T V J C R CU | 0.015 / 0.075 (pending verification) |
| Entry | `anthropic-claude/claude-haiku-4-5@2025-10` | 200K | T V J C | 0.001 / 0.005 (pending verification) |
| Previous flagship (alternative) | `anthropic-claude/claude-3-5-sonnet@2024-10-22` | 200K | T V J C | 0.003 / 0.015 (pending verification) |

**Feature notes**:
- prompt caching: `cache_control` markers + `anthropic-beta` header (per docs)
- computer_use: only some Sonnet-series models; requires a specific beta header
- extended thinking: some models; via the `thinking` parameter

**Verification path**: https://docs.claude.com/en/docs/about-claude/models  +  https://www.anthropic.com/pricing

## 5. Google Gemini

> Two access paths: Generative Language API (API key) / Vertex AI (service account). Pricing also differs between the two.

| Tier | model_ref (example) | ctx | caps | pricing input / output (per 1K) |
|---|---|---|---|---|
| Flagship | `gemini-main/gemini-2.5-pro@2025-03` | 1M+ | T V J C R E | 0.00125 / 0.005 (≤128K tier) |
| Fast | `gemini-main/gemini-2.5-flash@2025-04` | 1M | T V J C E | 0.0003 / 0.0025 (pending verification) |
| Previous flagship | `gemini-main/gemini-1.5-pro@2024-09-24` | 2M | T V J C E | 0.00125 / 0.005 |
| Embedding | `gemini-main/text-embedding-004@2024-04` | 2K | E | — |

**Feature notes**:
- Tiered long-context billing: above a threshold (e.g. 128K) the unit price doubles; cost estimates must account for the tiers
- safety_settings: blocks some output by default; relax as needed for evaluation scenarios (still record in the audit)
- context caching: requires an explicit `caches.create`; not the Anthropic-style implicit cache

**Verification path**: https://ai.google.dev/gemini-api/docs/models  +  https://ai.google.dev/pricing

## 6. xAI Grok

| Tier | model_ref (example) | ctx | caps | pricing input / output (per 1K) |
|---|---|---|---|---|
| Flagship | `grok-main/grok-3@2025-02` | 128K | T V J R | 0.005 / 0.015 (pending verification) |
| Vision | `grok-main/grok-2-vision@2024-12` | 32K | T V J | 0.002 / 0.01 (pending verification) |
| Entry | `grok-main/grok-2@2024-12` | 128K | T J | 0.002 / 0.01 (pending verification) |

**Feature notes**:
- live_search: real-time search capability; when enabled, output may contain unreviewed external content (governance treats this as high risk)
- OpenAI SDK compatible; just switch `base_url` and the model name

**Verification path**: https://docs.x.ai/docs/models  +  https://x.ai/api

## Quick reference

| I want... | Recommendation |
|---|---|
| Data never leaves the network | Ollama (qwen2.5 / llama 3.x / qwen-coder) |
| One key for many vendors + built-in fallback | OpenRouter |
| Most reliable tool calling + structured output | OpenAI gpt-4o / Anthropic Claude Sonnet |
| Long context (>200K) | Gemini 2.5 Pro / Anthropic long-context tiers |
| Multimodal (images / PDF screenshots) | Gemini 2.5 Pro / Claude / GPT-4o |
| Agents and computer use | Claude Sonnet (CU) |
| Hard reasoning problems | OpenAI o1/o3 / Gemini thinking / Grok 3 reasoning |
| Real-time information / web access | Grok (live search) |
| Evaluation judge (different vendor from the model under test) | An entry-tier model from a different vendor than the one under test (e.g. Claude Haiku judging GPT-4o) |

## Maintenance

- Review this document **every 30 days** (check it alongside `harness:` regression runs)
- Any `pricing` change must update the `pricing_as_of` field
- Model retirement (vendor deprecation) → keep the entry in the catalog, mark it `status: deprecated`, and provide migration guidance
- New models → enter the catalog first, then get referenced by the registry / aliases
