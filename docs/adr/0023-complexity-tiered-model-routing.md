# Complexity-tiered model routing (cheap vs thinking)

Status: accepted (2026-07-25)

The agentic Chat assistant should not pay thinking-model cost for a simple
question, nor answer a hard diagnosis with a cheap model. This ADR adds a
two-tier routing scheme and the provider support for "thinking" models.

## Decision

- **Two tiers: `cheap` and `thinking`**, each a `model_id` an admin
  designates from the (editable, ADR-0021) model list — stored as settings
  keys (`cheap_model_id`, `thinking_model_id`), the same mechanism as the
  team-default model. "Manually adding a model name" (a user ask) is exactly
  ADR-0021: add the thinking model to the list, then designate it here.
- **A cheap-model triage call decides complexity per user turn**, then
  routes to the tier. This mirrors the existing `classify_work_item`
  pattern (a cheap model classifies, then routing follows) — no new
  architectural shape.
- **A user "deep thinking" toggle overrides** the triage (force the thinking
  tier). Auto by default, manual when the User knows better; the override
  guards against mis-routing.
> **Correction (2026-08-18).** The parenthetical below names `budget_tokens` as
> Anthropic's mechanism. That is now true only of pre-4.6 models: Sonnet 5,
> Opus 5, Opus 4.7/4.8, and Fable 5 reject it — `400 — "thinking.type.enabled"
> is not supported` — and express depth as `effort` alongside
> `thinking: {"type": "adaptive"}`. The decision itself is unchanged and was
> right: *params-driven*, so the model config declares its shape and nothing is
> inferred from a model name. Both shapes are supported (#170).

- **Thinking support is added to providers, params-driven.** A "thinking
  model" is a model-list entry whose `params` enable it: Anthropic extended
  thinking (`thinking` / `budget_tokens`), OpenAI-family `reasoning_effort`,
  etc. The provider honors the param; nothing else designates a model as
  "thinking".

## Trade-off accepted

A triage call runs before the answer on each turn — a small, cheap-model
latency/cost tax in exchange for (a) cost savings when the answer routes to
the cheap tier and (b) quality when it routes to thinking. We chose
automatic routing (with a manual override) over a pure user toggle so the
common case needs no user decision. If only one tier is designated, routing
degrades to that single model.

## Consequences

- Routing lives in the chat agent; tier designation in the admin module.
- Thinking is net-new provider work (Anthropic/OpenAI-family first).
- A loaded **Skill** (ADR-0022) may hint the tier it needs (e.g. a complex
  diagnosis skill requests thinking).
