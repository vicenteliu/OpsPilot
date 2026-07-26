# MCP management: remote-add via UI, stdio stays file-only

Status: accepted (2026-07-25)

The agentic Chat assistant gains MCP tools (e.g. information search) to help
solve problems, and admins want to add MCP servers. MCP transports differ
sharply in risk: `stdio` runs a local `command` + `args` — **arbitrary code
execution on the OpsPilot host** — while `http`/`sse` are remote endpoints
(URL + env-based auth). A UI that adds arbitrary stdio servers is an RCE
hole, which contradicts OpsPilot's security posture (env-only secrets,
sandboxed actions, admin-gated governance).

## Decision

- **The admin UI can add / enable / disable / probe REMOTE (`http`/`sse`)
  MCP servers**: URL + auth via environment variable (never stored, per
  ADR-0020), tools allow/deny lists, trust level.
- **`stdio` servers stay file-only** in `mcp-config.yaml`, git-reviewed —
  never addable or editable from the UI. Local command execution requires a
  reviewed commit, not a form submission.
- **MCP tools are injected into the chat agent's ReAct loop** (and remain in
  the existing pipeline loop). A ready-to-enable **information-search** MCP
  is shipped as the first concrete example.
- MCP management is an **admin** action (ADR-0020); `global_policy` still
  audits every call.

## Trade-off accepted

Remote-add gives admins real "add an MCP" power without opening an RCE
surface; stdio's greater power stays behind git review. The line is drawn at
the security boundary: the UI must never let anyone with admin (or an
attacker who has taken an admin session) configure arbitrary local command
execution. The cost is that adding a local/stdio tool server is less
convenient than adding a remote one — deliberately.

## Consequences

- An admin MCP UI limited to remote servers; `mcp-config.yaml` remains
  authoritative and the only path for stdio.
- The shipped info-search MCP is remote (or a documented stdio example for
  self-hosters to add via file).
