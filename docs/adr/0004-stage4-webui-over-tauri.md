# ADR-0004: Keep Svelte WebUI, drop Tauri GUI plan

**Status**: Accepted  
**Date**: 2026-05-05  
**Stage**: 4 exit review

## Context

Stage 4 exit criterion 4 required a WebUI vs native GUI review before committing to Stage 5 scope.
Options considered:

1. **Keep Svelte 5 WebUI** (`web/`) — already implemented, FastAPI-backed, works in any browser.
2. **Add Tauri GUI** — wrap the WebUI in a Rust/Tauri shell for native desktop distribution.

## Decision

Keep the Svelte 5 WebUI. Tauri GUI is **not** added.

## Rationale

- The WebUI already satisfies all Stage 4 UI requirements (iteration history, lineage, provider status, run modal).
- Tauri adds build complexity (Rust toolchain, platform-specific bundles) with no functional gain for the target users (internal IT ops teams running on shared infrastructure).
- Browser-based delivery is simpler to update and deploy.

## Consequences

- Stage 5 scope excludes any Tauri / Electron work.
- `web/` remains the sole UI surface; the TUI (`src/opspilot/tui/`) remains the local terminal alternative.
