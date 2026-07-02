# ADR-0008: Package the macOS CLI via `uv tool`, not a frozen binary

**Status**: Accepted
**Date**: 2026-06-06
**Stage**: 5 (productionization)

## Context

Stage 5 (docs/zh/design/STAGES.md §7.5) lists "macOS desktop packaging (CLI binary)". The goal
is to let a user run `opspilot` on macOS without a project virtualenv or a
hand-managed Python on PATH.

The dependency graph makes this non-trivial. `opspilot.cli` imports the memory
stack at module load, which pulls heavy native packages **at import time**:
`lancedb` (Rust), `pyarrow`, `pandas`, `markitdown`, and `onnxruntime` (a large
ML runtime). Even `opspilot --help` loads all of them. A true single-file
freeze (PyInstaller) would have to bundle every one of those native libraries,
require custom collection hooks, produce a ~300MB+ artifact, and need macOS
code-signing/notarization for the bundled dylibs to clear Gatekeeper — a brittle
build for low payoff.

## Decision

Package the CLI with **`uv tool`**, not a frozen binary.

- `make package-macos` builds a wheel (`uv build --wheel`) and installs it with
  `uv tool install`, which creates an **isolated** environment and a single
  `opspilot` shim on PATH (under `uv tool dir --bin`).
- `uv` is itself a single static binary that fetches its own Python and resolves
  the platform-native wheels (`lancedb`/`pyarrow`/`onnxruntime` all ship macOS
  wheels), so installation needs no system Python and no project venv.

shiv / pex / pipx were rejected: they still require a Python interpreter on the
target and handle native wheels less cleanly (unpack-to-cache).

## Rationale

- Satisfies the actual requirement — `opspilot` on a clean macOS shell with no
  project venv — at far lower risk than freezing `onnxruntime` + `lancedb`.
- The native dependencies are distributed as wheels by their own maintainers;
  `uv` consumes those directly instead of us re-bundling and re-signing them.
- Matches the project's positioning (single-user, local-first; ADR-0002): a
  developer/operator installing a single `uv` binary is an acceptable
  prerequisite. It is not a consumer app needing zero-prereq distribution.

## Consequences

- The shipped artifact is a **wheel** + the `uv tool install` step, not a
  single self-contained executable. Installing `uv` is a documented prerequisite.
- If a zero-prerequisite single binary is ever required (e.g. distributing to
  non-technical users), revisiting PyInstaller — likely after making the CLI
  lazy-import the memory stack so the `--help` path stays light — is a deliberate
  reversal recorded in its own ADR.
- Build/install steps live in `deploy/packaging/README.md` and `make
  package-macos`.
