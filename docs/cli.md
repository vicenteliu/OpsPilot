# CLI and TUI reference

All commands assume an activated venv with `opspilot` installed
(see the [README quick start](../README.md#quick-start)).

## Terminal UI

Launch with `opspilot tui`. Press keys `1`–`8` to jump between modules.

| Key | Module | Description |
|-----|--------|-------------|
| `1` | Dashboard | Session/KB/wiki counts |
| `2` | Sessions | All runs; `W` → generate wiki page from selected session |
| `3` | KB Browser | Ingested documents and chunk counts |
| `4` | Wiki Tree | All wiki pages; `P` → promote selected draft/reviewed page to live |
| `5` | Harness | Eval run history |
| `6` | Lint Issues | Wiki lint results (orphans, broken links, redaction warnings) |
| `7` | Providers | Ollama / Anthropic / OpenAI connectivity status |
| `8` | Config | Active configuration values |
| `R` | — | Open Run modal (any screen) |
| `Q` | — | Quit |

```bash
opspilot tui run --input work_item.json --playbook playbooks/pb_ticket_summary_en
```

## Harness

```bash
# Run a single fixture against a playbook
opspilot harness run \
  --fixture examples/scn_ticket_summary_zh/harness/fixture.json \
  --golden  examples/scn_ticket_summary_zh/harness/golden.json \
  --playbook playbooks/pb_ticket_summary_zh \
  --output results.jsonl

# Stage 1 golden test (Anthropic baseline, weighted_score ≈ 0.968)
opspilot harness golden

# OpenRouter golden test (delta < 0.1 exit criterion)
opspilot harness golden-openrouter  # requires OPENROUTER_API_KEY

# Gemini golden test
opspilot harness golden-gemini      # requires GEMINI_API_KEY
```

Golden test scores vs baseline (threshold: delta < 0.1):

| Provider | Model | weighted_score | delta |
|---|---|---|---|
| Anthropic | claude-sonnet-4-6 | 0.968 | — baseline |
| OpenRouter | claude-haiku-4-5 (via OR) | 0.983 | 0.015 ✅ |
| Gemini | gemini-2.5-flash | 0.983 | 0.015 ✅ |

## Sandbox

The sandbox runs AI-proposed shell actions in a Docker L2 container (seccomp +
`--cap-drop=ALL` + read-only rootfs). An approval gate flags patterns like
`rm -rf`, `DROP TABLE`, `chmod 777`, and fork bombs for human sign-off — a
defense-in-depth signal, not a boundary
([ADR-0005](adr/0005-approval-gate-is-defense-signal-not-boundary.md)).

```bash
# Preview an action (no execution) — prints the exact docker argv
opspilot sandbox dry-run examples/sandbox_shell_l2/action.yaml

# Execute (requires Docker; dangerous patterns require --approve)
opspilot sandbox run examples/sandbox_shell_l2/action.yaml
opspilot sandbox run examples/sandbox_shell_l2/action.yaml --approve
```

### L3 (gVisor)

Add `--level l3` to either command to route execution through gVisor's `runsc`
runtime instead of the host kernel — all L2 hardening flags are retained, with
a stronger isolation boundary on top
([ADR-0009](adr/0009-sandbox-l3-gvisor-over-firecracker.md)).

```bash
# Dry-run shows the injected --runtime=runsc in the docker argv
opspilot sandbox dry-run --level l3 examples/sandbox_shell_l2/action.yaml

# Execute under gVisor (requires runsc registered with the Docker daemon)
opspilot sandbox run --level l3 examples/sandbox_shell_l2/action.yaml
```

L3 is **fail-closed**: if `runsc` is not registered in
`/etc/docker/daemon.json`, the run is refused with an explicit error rather
than silently downgrading to L2. Host setup (install `runsc`, register the
runtime) is documented in
[`docs/specs/sandbox/backends/README.md` §3](specs/sandbox/backends/README.md).

## MCP

```bash
# List all enabled MCP servers and their available tools
opspilot mcp list --config mcp-config.yaml

# Connect to a single server and report health
opspilot mcp probe --config mcp-config.yaml --server fs-readonly
```

MCP tools are injected into the orchestrator's ReAct loop automatically when
`mcp-config.yaml` is present at startup — no playbook changes needed. Config
example:

```yaml
version: "1.0.0"
mcps:
  - id: fs-readonly
    name: "Filesystem (read-only)"
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "${WORKSPACE_ROOT:-/workspace}"]
    tools_prefix: "mcp__fs__"
    tools_allowlist: ["read_file", "list_directory"]
    enabled: true
    trust: trusted

  - id: notion-main
    name: "Notion (main workspace)"
    transport: stdio
    command: npx
    args: ["-y", "@notionhq/notion-mcp-server"]
    env:
      NOTION_TOKEN: "${NOTION_API_KEY}"
    tools_prefix: "mcp__notion__"
    tools_denylist: ["delete_page", "delete_database"]
    enabled: true
    trust: trusted
```

Per-server allowlist/denylist, `${VAR:-default}` env expansion, and
best-effort inline-secret detection across env/args/url/headers (a footgun
guard, not a guarantee — keep secrets in the environment).

## Wiki

The wiki layer converts KB documents and session responses into a browsable,
lint-checked, lifecycle-managed knowledge base.

```bash
# Ingest a KB document into a wiki summary page
opspilot wiki ingest <doc_id>

# Convert qualifying archived sessions into synthesis pages (auto-scan)
opspilot wiki query-to-page
opspilot wiki query-to-page --session sess_<id>   # single session

# Promote a draft page through the lifecycle
opspilot wiki promote <slug>                       # draft → live (default)
opspilot wiki promote <slug> --to reviewed         # draft → reviewed

# Lint the wiki for structural issues
opspilot wiki lint
```

**Wiki page lifecycle:** `draft` → `reviewed` → `live` → `stale` → `archived`

Pages are always written as `draft` by automated tools. Human review (CLI or
TUI `P`) promotes them to `live`.
