# No source-built inference runtimes

Status: accepted (2026-08-07)

The trigger was `audio.cpp` — a ggml-based C++ audio inference framework
(TTS/ASR/VAD/diarization) sitting in a sibling repo — and the **Voice input**
item parked in ROADMAP's _Later_ section. The answer is that OpsPilot does not
adopt it, but the reason is not "OpsPilot runs no inference locally". It
already does, in-process, every time it converts a non-markdown file:
`markitdown[pdf]` pulls in `magika`, a neural file-type classifier, which
pulls in `onnxruntime`.

So the line this ADR draws is not between local and remote inference. It is
between a runtime OpsPilot can *install* and a runtime OpsPilot would have to
*build*.

## Decision

- **An inference runtime enters the dependency tree only if it installs as a
  prebuilt wheel on every supported platform, or runs as a separate service
  reached over HTTP.** A runtime that requires OpsPilot to own a source build
  does not enter.
- **Two already qualify, and they set the precedent.** `onnxruntime` arrives
  via `markitdown[pdf]` → `magika` as prebuilt per-platform wheels — no build
  chain in either release path. Ollama is a local model reached over HTTP like
  any other provider adapter (`anthropic` / `openai` / `ollama`, ADR-0021).
- **`audio.cpp` does not qualify.** It is a CMake project (`cmake_minimum_required
  3.20`, `LANGUAGES C CXX`) with no Python distribution, so adopting it means
  OpsPilot owns a native build per platform. It is also currently unreferenced:
  no submodule, no path dependency, no import, and nothing in `pyproject.toml`,
  `uv.lock`, `web/package.json`, or any `Cargo.toml` — the workspace root or
  the per-crate manifests under `crates/*/`, which is where a path dependency
  would actually be declared.
- **Voice input stays in _Later_ with its engine undecided.** The live options
  are a provider transcription API, a local service over HTTP, or a
  wheel-distributed runtime — not a source build.

## Trade-off accepted

The rule costs us any runtime that is genuinely best-in-class but ships only as
source, until someone else packages it. We accept that because OpsPilot already
declines to own a native build even for its own code: the `opspilot-chunker` /
`opspilot-tokenizer` crates are built separately with `maturin`
(`make rust-build`) and are **not** part of the wheel — the CLI falls back to
the pure-Python paths when they are absent (`deploy/packaging/README.md`).
Neither release path compiles them: the wheel is built by hatchling from
`src/opspilot`, and the Dockerfile installs no Rust toolchain. A project that
won't ship its own two small PyO3 extensions in the release artifact has no
business taking on a ggml build chain for a feature nobody is waiting on.

ADR-0012 took a related shape for a different reason — the Telegram channel
runs as a separate process calling the HTTP API rather than importing the
orchestrator.

Revisit when a concrete requirement cannot be met by either admitted form —
hard-offline operation that no wheel-packaged runtime covers, or a latency
budget that a local HTTP hop blows. "We already have the source sitting right
there" is not that requirement; "upstream now publishes wheels" is.

## Consequences

- Voice input, when built, adds a provider capability, an HTTP client, or a
  wheel — not a build-system change.
- The `audio_in` / `audio_out` flags in `docs/specs/providers/SPEC.md` stay as
  they are. Like the rest of the `capabilities` block they describe what a
  provider can do, not what OpsPilot uses; no flag in that block is read by
  code yet.
- `CONTEXT.md` gains no term — the glossary tracks what exists, and there is
  no audio concept in the code.
- The in-process `magika` inference is now recorded rather than accidental. If
  it is ever unwanted, that is a dependency decision about `markitdown`, not a
  violation of this ADR.
