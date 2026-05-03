# Retrieval mode: prefetch for weak tool-calling models

Weak open-source models (≤7B, e.g. gemma4:e4b) reliably ignore `kb_search` tool-call instructions and emit final JSON directly, causing zero KB retrieval and a weighted harness score of 0.233. We added a `prefetch` retrieval mode to playbooks: the system fetches top-k KB chunks before the LLM call and injects them into the system prompt as markdown, telling the model to cite directly without calling tools. The default (`tool` mode) is preserved for strong models that handle ReAct correctly.

## Considered options

- **Prompt engineering**: add stronger instructions to force tool calls — rejected, the model's tool-calling training is the bottleneck, not the prompt.
- **Switch to a stronger model**: works, but abandons the "local small model" product positioning.
- **Prefetch (chosen)**: orthogonal to model capability; harness evaluators (recall, precision, citation_validity) work unchanged because prefetch writes the same `tool_call` + `tool_result` trace events that the harness already reads.

## Consequences

- Playbooks must explicitly declare `retrieval.mode: prefetch` for weak-model scenarios; omitting it defaults to `tool` for backwards compatibility.
- Prefetch mode caps retrieval to one query per session (no multi-turn search refinement). Acceptable for ticket triage; revisit if multi-hop reasoning scenarios emerge.
- KB embedding model upgrades require full reindex — citation chunk IDs are content-addressed and will change.
