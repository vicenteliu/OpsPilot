# Providers — LLM Provider Abstraction

> **Status**: spec-only. This directory only defines provider config contracts, the registry, and model catalogs; no runtime implementation lives here.
> **Stage**: spec only — provider config contracts, registry, and model catalogs. No runtime here.

## TL;DR
Providers let the same OpsPilot Session/Playbook switch the underlying LLM **without any changes**. This directory defines 6 supported provider kinds:

| Provider | Type | Default endpoint | Main value |
|---|---|---|---|
| **Ollama** | Self-hosted / local | `http://localhost:11434` | Intranet / offline / data never leaves the network |
| **OpenRouter** | Aggregator gateway | `https://openrouter.ai/api/v1` | One key for hundreds of models; good for fallback |
| **OpenAI API** | Cloud | `https://api.openai.com/v1` | Tool calling / vision / structured output |
| **Anthropic (Claude API)** | Cloud | `https://api.anthropic.com/v1` | Long context / prompt caching / computer use |
| **Google Gemini API** | Cloud | `https://generativelanguage.googleapis.com/v1beta` | Multimodal / very long context / Vertex AI as alternative |
| **xAI Grok API** | Cloud | `https://api.x.ai/v1` | OpenAI-compatible / live search |

> ⚠️ **Information freshness**: endpoints, model names, and pricing change unilaterally at each vendor's discretion. Every concrete value in this repository carries an as-of date; **verify against the official docs before deploying**. See `catalogs.md`.

## Principles

1. **Default deny on cost**: every provider must set `monthly_budget_usd`; exceeding the threshold blocks by default rather than merely warning
2. **Secrets out-of-tree**: API keys always use `${ENV_VAR}` placeholders; actual values are injected by the secrets broker
3. **Pluggable**: upper layers (session / harness) reference only `provider_id` and are never coupled to a specific vendor
4. **Capability-aware routing**: playbooks declare required capabilities (tools/vision/long_ctx); the registry filters eligible providers by capability
5. **Audit-friendly**: every call must write "the provider config hash actually hit + the model version" back to the Session

## Selection decision tree

```
Must data stay on-network? ──▶ Yes ──▶ Ollama (local by default + self-hosted GPU)
        │
        No
        ▼
Want "one key for many vendors"? ──▶ Yes ──▶ OpenRouter (good for fallback chains)
        │
        No
        ▼
Capability first:
  ├─ Tool calling / structured output / complex agents  → OpenAI or Anthropic
  ├─ Long context / multimodal                          → Anthropic or Gemini
  ├─ Real-time information / web search                 → Grok (live search)
  └─ General-purpose / cost-sensitive                   → each vendor's entry tier (with a budget cap)
```

## Routing strategies

`provider-registry.template.yaml` supports four strategies; **pick exactly one**:

1. **fixed**: always use the specified provider — the default; easiest to audit
2. **fallback**: primary provider fails / hits rate limiting → automatically switch to the backup — suited to online ticket flows
3. **capability**: filter by the capabilities the playbook declares — suited to multiple playbooks sharing providers
4. **cost-aware**: among candidates that satisfy the capabilities, pick the lowest token unit price — suited to batch evaluation

> 💡 **Recommendation**: default to `fixed` on production paths; enable other strategies only for the harness and fallback chains. Stacking multiple strategies significantly hurts reproducibility.

## Gateway options (skip per-provider wiring)

If you don't want to write 6 provider configs, use one of these gateways:

| Gateway | Nature | Suited for |
|---|---|---|
| **OpenRouter** | Commercial aggregator | Individuals / small teams; built-in fallback |
| **LiteLLM proxy** | Open-source OpenAI-compatible proxy (self-hosted) | Intranet / shared across teams / cost auditing |
| **Portkey / Helicone** | Commercial observability gateways | When you need request logs and cost dashboards |

When going through a gateway, this repository's "6 provider configs" collapse into "1 OpenAI-compatible provider", but the `model` field must still explicitly record the real underlying model (for auditing).

## Hard nos

- ❌ Never commit real API keys to the repository (`.gitignore` already covers `.env`, but secrets must go through the broker)
- ❌ Never give the sandbox an LLM API key (the sandbox should not call LLMs directly; orchestration happens at the upper layer)
- ❌ Never allow provider configs to be modified at runtime by prompt content (prevents prompt-injection from rewriting routing)
- ❌ Never mix "self-hosted Ollama" and "sensitive data going to the cloud" in the same playbook (data-classification isolation)

## Contracts with other directories

| Upstream | Input to providers |
|---|---|
| `governance/` | budget caps, data-classification routing constraints, telemetry opt-out policy |
| `playbooks/` | required capabilities (declarative) |

| Downstream | Artifacts providers deliver |
|---|---|
| `session/` | model_ref (written to trace + meta) + provider_config_hash (written to audit) |
| `harness/` | model matrix (multiple providers run across fixtures) |

## Directory layout

```
providers/
├── README.md                         # This file
├── SPEC.md                           # Abstraction contract
├── catalogs.md                       # Known model catalogs (with verification dates)
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

## Open questions

- [ ] Should Vertex AI (Gemini's GCP channel) be a standalone provider, or a `gemini.deployment_mode` field?
- [ ] Does Azure OpenAI (deployment name + region) need its own template, or should it reuse OpenAI with `deployment_mode: azure`?
- [ ] Should local vLLM / TGI (OpenAI-compatible self-hosted) be merged into the ollama template or kept separate?
- [ ] How should the SPEC express the billing differences of prompt caching / context caching across vendors?
