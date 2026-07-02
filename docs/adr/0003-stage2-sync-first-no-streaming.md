# Stage 2 WebUI: synchronous LLM calls with spinner, no streaming

LLM calls in Stage 2 are synchronous: FastAPI blocks until the orchestrator returns, then sends the full response. The WebUI shows a spinner during the wait. Streaming (SSE) is deferred to Stage 3.

## Why not stream in Stage 2

The Stage 1 orchestrator is synchronous by design (explicit decision in docs/zh/design/IMPLEMENTATION_STAGE_1.md §0). Adding SSE in Stage 2 would require converting the orchestrator to async — pulling forward Stage 3 work and increasing Stage 2 scope significantly. The UX cost (spinner vs. live tokens) is acceptable for a local tool where runs take 5–30s.

## Bridge pattern for Stage 3

FastAPI will call the synchronous orchestrator via `asyncio.run_in_executor` to avoid blocking the event loop, without changing the orchestrator internals. When Stage 3 adds streaming, only the FastAPI layer and the orchestrator's chat loop need to change — the session, trace, and harness layers are unaffected.
