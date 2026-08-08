# Inference runtimes stay out of process

Status: accepted (2026-08-07)

OpsPilot reaches models over HTTP — the provider adapters built into the app
(`anthropic` / `openai` / `ollama`, ADR-0021) are clients, not runtimes.
Ollama is the local case: it runs as its own service and OpsPilot talks to it
over the network like any other provider. Nothing that performs inference is
linked into, vendored by, or compiled as part of an OpsPilot release artifact.

That has never been written down, so each new local-model idea re-opens the
question from scratch. The trigger this time was `audio.cpp` — a ggml-based
C++ audio inference framework (TTS/ASR/VAD/diarization) sitting in a sibling
repo — and the **Voice input** item parked in ROADMAP's _Later_ section.

## Decision

- **An inference runtime is never embedded in an OpsPilot release artifact.**
  OpsPilot talks to inference across a process boundary — an HTTP provider
  adapter today. This covers LLMs, embeddings, vision, rerankers, and audio
  alike.
- **`audio.cpp` is not an OpsPilot dependency**, now or as a planned one.
  Verified unreferenced: no submodule, no path dependency, no import, nothing
  in `pyproject.toml` / `uv.lock` / `Cargo.toml` / `web/package.json`.
- **Voice input stays in _Later_ with its engine undecided.** When it is
  built, the choice is between a provider transcription API and a local
  service reached over HTTP — not between "provider API" and "link a C++
  runtime in".
- **This is about inference, not about native code.** The `opspilot-core` /
  `opspilot-chunker` / `opspilot-tokenizer` crates are compiled into the
  release and stay that way; they are text-processing hot paths, not
  inference.

## Trade-off accepted

A process boundary costs latency, and it makes the local case a two-thing
install (OpsPilot + Ollama) rather than one binary. We accept that because
the alternative multiplies across both release paths: the docker compose
stack and the macOS `uv tool` install (ADR-0008) would each grow a CMake /
CUDA / Metal build chain per embedded runtime, per platform. ADR-0012 already
took this shape for a different reason — the Telegram channel runs as a
separate process calling the HTTP API rather than importing the orchestrator.

Revisit when a concrete requirement cannot be met across a process boundary —
hard-offline operation, or a latency budget that a local HTTP hop blows.
"We already have the code sitting right there" is not that requirement.

## Consequences

- Voice input, when built, adds a provider capability or an HTTP client — not
  a build-system change.
- The `audio_in` / `audio_out` flags in `docs/specs/providers/SPEC.md` stay as
  they are. Like the rest of the `capabilities` block they describe what a
  provider can do, not what OpsPilot uses; no flag in that block is read by
  code yet.
- `CONTEXT.md` gains no term — the glossary tracks what exists, and there is
  no audio concept in the code.
