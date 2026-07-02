---
# SKILL.md template / Skill template
# Equivalent to schemas/skill.schema.json

name: "ticket_summary_zh"
description: "Summarize a redacted Chinese IT support ticket and emit a ticket_summary_v1 JSON with citations to KB SOPs. Trigger when input includes a ticket body or vpn-client-style log snippet. Requires kb.search and an LLM with json_mode."
version: "1.2.0"
language: "zh-CN"

author: "vicente@example.com"
source: "self_authored"             # self_authored | distilled | imported_trusted | imported_community | imported_unknown
license: "MIT"

# Compatible models; use a registry alias or a concrete model_ref; latest/auto/stable are forbidden
model_compat:
  - "@chat-strong"
  - "anthropic-claude/claude-sonnet-4-6@2026-04"
  - "openai-main/gpt-4o@2024-11-20"

requires:
  tools:
    - "kb.search"
    - "artifact.write"
  mcps: []                          # MCP server ids; this skill needs no external MCP
  providers:
    tools: true                     # the model must support tool calling
    json_mode: true
    long_context_tokens: 32000
  skills: []                        # other skills this one depends on

safety:
  classification: "internal"        # public | internal | confidential | restricted
  approval_required: false
  telemetry_optout: true
  pii_allowed: false                # input must not contain PII; reject on detection

inputs:
  schema_ref: "examples/scn_ticket_summary_zh/harness/fixture.json#input"
  description: "Redacted ticket payload (subject + body + log attachment)"
outputs:
  schema_ref: "examples/scn_ticket_summary_zh/harness/golden.json#schema_check"
  description: "ticket_summary_v1 structured JSON"

# If source ≠ self_authored, the distillation section is required
# distillation:
#   type: "from_traces"
#   sources:
#     - "sess_01J0Z9ZQXK7M6P3F0XK5K7C5K0"
#   pipeline_run: "run_dist_01J0Z9ZQXK7M6P3F0XK5K7"
#   distilled_at: "2026-05-01T12:00:00Z"
#   redaction_rules_version: "1.0.0"

redacted: true
redaction_rules_version: "1.0.0"

tags: ["ticket", "L1", "zh-CN", "rag"]
labels:
  team: "service-desk"

extensions: {}
---

# Ticket Summary (zh-CN)

## When to use

The input contains a **redacted** IT work item (body + optional attached log snippet), and the user wants a structured summary.

## Steps

1. **Search the KB**: call `kb.search` with the ticket's key symptom (e.g. "VPN authentication failure"); scopes default to `opspilot:public-kb`, top_k=8, hybrid mode + cross_encoder rerank.
2. **Generate the structured summary**: fill in all required keys of the `ticket_summary_v1` schema.
3. **Citations are mandatory**: whenever a `next_actions[].rationale` cites a Chunk, its citations field must resolve back to `source_path:line_range`.
4. **Write the Artifact**: call `artifact.write`, filename = `art_<sha256(payload)[:16]>.json`.

## Hard rules

- The output `summary` field must not contain `[REDACTED:` placeholders (not even in technical-detail fields)
- `severity_suggested` must match `^P[0-4]$`
- `next_actions` must contain at least 3 entries, each either actionable or marked missing-info
- Every cited chunk_id must have appeared in a `kb.search` response

## Failure modes

- No KB hits: still produce the summary, but with `citations: []`, and add a "recommend a human supplement the SOP" entry to `next_actions`
- The work item contains unredacted PII: refuse to process; return `safety_violation` and record `tool_result.status=aborted`

## Resources

- `resources/rubric.md` — scoring dimensions (kept in sync with the Harness rubric)
- `resources/example-output.json` — reference output, used for in-context learning
