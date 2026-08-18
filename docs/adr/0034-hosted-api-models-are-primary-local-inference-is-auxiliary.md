# Hosted API models are primary; local inference is auxiliary

Status: accepted (2026-08-18)

OpsPilot began on Ollama. Stage 1's golden test ran against a local model, the
Makefile still opens with `ollama-up` / `ollama-pull`, and `CONTEXT.md` said the
golden test "requires a live Ollama instance".

None of that has been true for a while. Every shipped playbook's primary model is
`anthropic/claude-haiku-4-5-20251001`; embeddings prefer OpenAI whenever
`OPENAI_API_KEY` is set and fall back to Ollama only in its absence; `make test`
already excludes the Ollama-marked tests. The decision had been made in practice,
model by model, and written down nowhere — which is how the help strings ended up
telling people to start a daemon they no longer need.

## Decision

**Hosted API models are the primary target. Local inference stays supported, as
an auxiliary.**

- New capability is designed against, and validated on, hosted API models.
  Development and testing use API keys.
- Local inference remains a first-class *fallback*: the `ollama-local` provider,
  the `golden-ollama` target, the `requires_ollama` test marker, and the
  Ollama embedding path all stay. Nothing is being removed.
- Ollama is still the only zero-key path, which is why it remains the embedding
  fallback and keeps a golden variant of its own.
- The **prefetch** retrieval mode exists because weak local models cannot drive a
  tool loop, and it stays for the same reason. This decision does not narrow the
  supported model range — it says which end of it new work is aimed at.

## Trade-off accepted

**Content leaves the building.** OpsPilot processes internal tickets, logs, and
runbooks, and the default path now sends them to a third-party API. That is the
real cost of this decision and the reason it needed writing down: a reader would
otherwise, and reasonably, assume an IT operations tool defaults to local
inference. Redaction runs before anything reaches a provider, and Ollama remains
available for anyone whose constraints forbid egress — but the default is egress,
and defaults are what most deployments run.

Also accepted: a paid dependency on a vendor, and a floor on cost per run that
local inference did not have.

The alternative — holding local-first — was rejected on capability. Structured
artifacts with valid citations from a weak local model were the reason
`prefetch` mode exists (ADR-0001); designing every new feature to that ceiling
would cap the product at what a 7B model can do.

## Consequences

- The Makefile help strings and `CONTEXT.md`'s **Golden test** entry stop
  claiming Ollama is required. What a golden run needs is the target chat
  provider's key plus *an* embedding provider.
- Supporting several hosted models is now load-bearing rather than a nicety, and
  it turns out not to have worked: `claude-sonnet-5` and `claude-opus-5` were
  offered in six playbooks' `extra_models` and returned HTTP 400 on every run,
  because sampling params were sent unconditionally (#172). Extended thinking is
  still broken against the same models (#170), and a provider rejection is still
  reported as a quality score (#171).
- ADR-0025 (no source-built inference runtimes) is unaffected and now reads as
  the other half of this one: local inference is supported, but not by compiling
  a runtime ourselves.
- ADR-0029's rule applies with more force. A vendor's documentation about its own
  model is still just documentation; what a model does on this fixture is a
  firsthand finding, and disagreements are settled by running it.
