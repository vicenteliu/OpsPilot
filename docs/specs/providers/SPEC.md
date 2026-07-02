# Providers — Detailed Spec

## 1. Abstraction contract

### 1.1 Unified call shape

Every provider invoked inside OpsPilot must map onto a unified "chat completion" shape:

```
ProviderCall {
  provider_id      : id from the registry
  model            : model name (without version; version goes in model_version)
  model_version    : pinned version (latest is not allowed)
  messages         : [{role, content, ...}]
  tools            : optional; unified format (see §4)
  params           : {temperature, top_p, max_tokens, seed, stop, ...}
  timeouts         : {connect_ms, read_ms, total_ms}
  budget_usd       : per-call budget cap
  capabilities_req : capabilities required for this call (used for routing validation)
}
```

Response shape:

```
ProviderResponse {
  provider_id      : provider actually hit (after routing)
  model_ref        : "<provider_id>/<model>@<model_version>"
  finish_reason    : stop | length | tool_call | content_filter | error
  content          : text or a list of tool calls
  usage            : {input_tokens, output_tokens, cached_tokens?, cost_usd}
  latency_ms       : {ttfb, total}
  raw              : vendor's raw payload (optional, referenced as an artifact)
}
```

### 1.2 Model ref format

**Hard requirement**: `<provider_id>/<model_name>@<model_version>`, e.g.:

```
ollama/qwen2.5:14b@2024-09
openrouter/anthropic/claude-sonnet-4-6@2026-04
openai/gpt-4o@2024-11-20
anthropic/claude-sonnet-4-6@2026-04
gemini/gemini-2.5-pro@2025-03
grok/grok-3@2025-02
```

- `provider_id` must appear in `provider-registry.template.yaml`
- `model_name` must match that provider's catalog
- `model_version`: `latest`, `auto`, and `stable` are forbidden; it must be a vendor's explicit version string or a date string
- When going through an aggregator gateway such as OpenRouter, the **real underlying model** must still be written out (for auditing): `openrouter/<vendor>/<model>@<ver>`

## 2. Required config fields

The authoritative definition is `schemas/provider-config.schema.json`. Core fields:

| Field | Required | Description |
|---|---|---|
| `id` | ✓ | provider instance id (the same vendor may register multiple instances, e.g. `ollama-gpu1` / `ollama-cpu`) |
| `kind` | ✓ | enum: `ollama` / `openrouter` / `openai` / `anthropic` / `gemini` / `grok` / `openai_compatible` |
| `display_name` | ✓ | human-readable name |
| `base_url` | ✓ | full URL (may be force-overridden by routing) |
| `auth` | ✓ | see §3 |
| `default_headers` | ✗ | vendor-required headers (e.g. `anthropic-version`) |
| `capabilities` | ✓ | see §4 |
| `limits` | ✓ | rate limit, context window, max_output |
| `cost` | ✓ | pricing model + monthly budget |
| `retry` | ✓ | retry policy |
| `compliance` | ✗ | data residency, telemetry, training-use opt-out |
| `enabled` | ✓ | bool; set to false when decommissioning instead of deleting |

## 3. Authentication

Allowed authentication types:

```yaml
auth:
  type: "api_key_header"          # see the table below
  env: "OPENAI_API_KEY"           # actual value is read from an environment variable, never committed
  header: "Authorization"
  prefix: "Bearer "
```

Supported `auth.type` values:

| type | Applicable vendors | Injection method |
|---|---|---|
| `none` | Ollama (default) | no auth header sent |
| `api_key_header` | OpenAI / OpenRouter / Grok / Ollama-served | `Authorization: Bearer <key>` |
| `api_key_custom_header` | Anthropic | `x-api-key: <key>` + `anthropic-version: <ver>` |
| `api_key_query` | Gemini (API key mode) | URL `?key=<key>` |
| `oauth2_service_account` | Vertex AI (Gemini enterprise mode) | short-lived token with automatic refresh |

**Hard requirements**:
- API keys always use `env:` placeholders; inlining via `value:` is not allowed
- `oauth2_service_account` must set `key_file_env` pointing to the credentials JSON path
- A provider must not read credential directories that don't belong to it, such as `~/.aws`, `~/.kube`, or `~/.ssh`

## 4. Capability declaration

`capabilities` is a set of bool flags plus numeric caps. It is compared against the `capabilities_req` a playbook declares.

```yaml
capabilities:
  streaming: true
  tools: true                       # function calling / tool use
  vision: true
  audio_in: false
  audio_out: false
  json_mode: true                   # structured output
  prompt_caching: false             # supported by Anthropic and some models
  long_context_tokens: 200000
  max_output_tokens: 8192
  reasoning_mode: false             # OpenAI o1/o3, Gemini thinking, etc.
  computer_use: false               # only some Anthropic models
  embeddings: false                 # whether this provider also offers embeddings
```

Declaration principles:
- **Conservative**: capability fields reflect what is **actually available in the current catalog**, not "theoretically supported"
- **Fallback-safe**: a provider with `tools=false` must not be routed to a playbook declaring `tools_req=true`
- **No cross-declaration**: one provider config instance represents exactly one access mode (never both local and cloud)

## 5. Limits

```yaml
limits:
  context_window_tokens: 200000
  max_output_tokens: 8192
  rpm: 60                            # requests per minute
  tpm: 200000                        # tokens per minute
  concurrent: 8                      # max concurrent requests (client side throttle)
```

OpsPilot applies a client-side token bucket; the vendor's real rate limits are authoritative (handle 429s per the `retry` policy).

## 6. Cost & budget

```yaml
cost:
  pricing:
    input_per_1k_usd: 0.0           # as-of date + source must be recorded in catalogs.md
    output_per_1k_usd: 0.0
    cached_input_per_1k_usd: null    # optional; discounted prompt-cache price
    pricing_as_of: "2026-05-01"
  monthly_budget_usd: 50             # hard monthly budget
  per_call_budget_usd: 0.5           # per-call cap (block when exceeded)
  on_budget_exceeded: "block"        # block | warn | downgrade
  downgrade_to: null                 # provider_id; used when on_budget_exceeded=downgrade
```

## 7. Retry & timeouts

```yaml
retry:
  max_attempts: 3
  initial_backoff_ms: 500
  max_backoff_ms: 8000
  jitter: "full"                     # full | none
  retry_on:
    - "http_429"
    - "http_500"
    - "http_502"
    - "http_503"
    - "http_504"
    - "timeout_read"
  give_up_on:
    - "http_400"
    - "http_401"
    - "http_403"
    - "http_404"
    - "http_413"                     # context overflow is not retried
timeouts:
  connect_ms: 5000
  read_ms: 60000
  total_ms: 90000
```

**Idempotency reminder**: tool_call and sandbox execution are separated — provider retries only retry model generation, never sandbox actions.

## 8. Compliance

```yaml
compliance:
  data_residency: "unspecified"      # us | eu | apac | unspecified
  telemetry_optout: true             # whether to require opting out of vendor training use / log retention
  zero_data_retention: false         # whether the vendor commits to zero data retention (per contract)
  pii_allowed: false                 # whether this provider may process PII (decided by governance)
  red_lines:
    - "Never send unredacted PII"
    - "Never send internal codenames"
```

A provider with `pii_allowed=false` must not receive Sessions carrying redaction warnings during routing (leak prevention).

## 9. Registry semantics

`provider-registry.template.yaml` is the top-level entry point:
- `providers[]`: registered provider instances
- `default_provider`: used when no routing is declared
- `routing`: strategy and rule set
- `aliases`: model shorthand → `model_ref` (lets playbooks reference `@chat-strong` instead of a concrete model)

Strategy precedence (high → low):
```
session.model_override
  > playbook.preferred_provider
    > registry.routing rule
      > registry.default_provider
```

## 10. Field mapping to Session / Harness

| Session (meta.yaml) | Providers |
|---|---|
| `model.vendor` | the provider_id's kind |
| `model.name` | model_name |
| `model.version` | model_version |
| `extensions.provider_config_hash` | sha256 of the provider config actually hit (for auditing) |

| Harness (eval-config) | Providers |
|---|---|
| `models[]` | always `<provider_id>/<model>@<version>` |
| evaluator `judge.llm.judge_model` | same as above; the judge provider should differ from the provider under test |

## 11. Hard requirements

- Any provider instance must pass "health check + one minimal prompt call" before it counts as enabled
- API keys always come from environment variables; committing a config file containing a key is treated as a security incident
- `model_version` must not be `latest`/`auto`/`stable`
- If any of pricing/limits/capabilities disagrees with `catalogs.md`, the catalog is authoritative and the drift is flagged in the audit
- Self-hosted (Ollama / vLLM) deployments must not point base_url at a public domain (prevents misuse)

## 12. Extensions

- `extensions.<vendor>` — vendor-specific features (e.g. Anthropic's `cache_control`, Gemini's `safety_settings`)
- Adding a new provider type: integrate via the compatibility layer with `kind: "openai_compatible"` (vLLM, TGI, LiteLLM proxy, local OpenRouter)
