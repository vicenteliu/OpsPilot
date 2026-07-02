# Session — Detailed Spec

## 1. Lifecycle & state machine

```
            ┌──────────┐
            │  draft   │  created as a placeholder, not yet redacted
            └────┬─────┘
                 │ redact() complete
                 ▼
            ┌──────────┐
            │  active  │  in progress (multi-turn dialogue / tool calls)
            └────┬─────┘
       ┌─────────┼──────────┐
       │ pause   │ resume   │ terminate
       ▼         │          ▼
  ┌─────────┐    │     ┌─────────┐
  │ paused  │────┘     │ aborted │
  └─────────┘          └─────────┘
                 │ user.archive()
                 ▼
            ┌──────────┐
            │ archived │  read-only; may be referenced by harness
            └────┬─────┘
                 │ retention expires
                 ▼
            ┌──────────┐
            │ purged   │  only the audit summary retained (meta-only)
            └──────────┘
```

Allowed transitions:
- `draft → active`: redaction complete and all meta fields populated
- `active ↔ paused`
- `* → aborted`: user aborts; all data produced so far is retained
- `active|paused → archived`: user archives; artifacts become read-only
- `archived → purged`: retention period expires; inputs/artifacts are cleaned up automatically, leaving only meta + audit summary

## 2. Top-level fields

> The authoritative definition is `schemas/session.schema.json`. This section is the human-readable explanation.

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string `^sess_[0-9A-HJKMNP-TV-Z]{26}$` | ✓ | ULID |
| `schema_version` | string semver | ✓ | meta schema version, e.g. `"1.0.0"` |
| `owner` | string | ✓ | Primary owner (email or user id) |
| `collaborators` | string[] | ✗ | Collaborators; permissions governed by RBAC |
| `playbook` | { id, version } | ✓ | Referenced Playbook |
| `prompts` | { id, version }[] | ✗ | Prompts used, with versions |
| `model` | { provider_id, kind, name, version, params, ... } | ✓ | Model and sampling params; see `providers/SPEC.md` §1.2. Equivalent to `model_ref = <provider_id>/<name>@<version>`. `latest`/`auto`/`stable` are forbidden for `version`. |
| `status` | enum `draft|active|paused|aborted|archived|purged` | ✓ | See state machine |
| `created_at` | RFC3339 | ✓ | UTC |
| `updated_at` | RFC3339 | ✓ | UTC |
| `parent_id` | session_id | ✗ | Points to the parent Session for replay/branching |
| `retention_class` | enum `low|medium|high|critical` | ✓ | See `retention-policy.template.yaml` |
| `sensitivity` | enum `public|internal|confidential|restricted` | ✓ | Data classification |
| `tags` | string[] | ✗ | Free-form tags |
| `labels` | object | ✗ | k/v pairs; for search and stats |

## 3. Trace events

One event per line in `trace.jsonl`, with `seq` monotonically increasing.

Event types (discriminator = `type`):

| type | Meaning | Key fields |
|---|---|---|
| `prompt` | Prompt sent to the model | `role`, `content`, `prompt_ref` |
| `response` | Model response | `content`, `finish_reason`, `usage` |
| `tool_call` | Model requests a tool invocation | `tool`, `args` |
| `tool_result` | Tool execution result | `tool`, `exit_code`, `stdout_ref`, `artifact_ids` |
| `redaction` | Record of a redaction trigger | `pattern`, `count`, `placeholder` |
| `user_action` | User intervention (accept/reject/edit/approve) | `action`, `payload_diff` |
| `system` | State changes, errors | `event`, `details` |

Authoritative schema: `schemas/trace-event.schema.json`.

## 4. Artifacts

- Path: `artifacts/<artifact_id>.<ext>`
- ID: `art_<sha256[:16]>` (content-addressed; dedup + tamper resistance)
- Must have a sidecar: `artifacts/<artifact_id>.meta.yaml` (see template)
- Artifacts never write large file bodies directly into the trace; the trace only references `artifact_id`

## 5. Redaction integration

- **Entry point**: everything written to `inputs/` and `trace.jsonl` must pass through the redactor
- **Placeholder format**: `[REDACTED:<type>:<8 hex chars>]`, e.g. `[REDACTED:email:a1b2c3d4]`
- **Reversible mapping**: the original ↔ placeholder mapping is stored only in `audit.log` (restricted read access), never in the trace
- Rules template: `templates/redaction-rules.template.yaml`
- Keep consistent with `governance/redaction.md`; governance is authoritative

## 6. Retention

- `retention_class` determines the expiry in days; see `templates/retention-policy.template.yaml`
- On expiry: clear `inputs/` + `artifacts/`, keep `meta.yaml` and the `audit.log` summary
- The `audit.log` retention period is defined separately (longer by default, e.g. 365 days)
- Users may `archive` or `delete` manually; `delete` is irreversible and requires a second confirmation

## 7. Replay & diff

- Re-run with the same `inputs/` + a different `model` or `prompts` → create a new Session with `parent_id` set
- Diff dimensions: response text, tool_call sequence, artifact content, tokens/cost/latency, harness scores
- Replay must be determinism-friendly: record sampling params such as temperature, seed, and top_p

## 8. RBAC & audit

Minimal roles (recommended):
- `owner`: full control
- `collaborator`: read/write trace + artifacts; cannot modify meta/retention
- `viewer`: read-only
- `auditor`: read-only audit.log + meta (including the mapping to redacted originals)

`audit.log` must be append-only, format:
```
<rfc3339>\t<actor>\t<action>\t<target>\t<details_json>
```

## 9. Hard requirements

- All timestamps must be **UTC + RFC3339**
- File encoding must be **UTF-8** (no BOM)
- Every line of `trace.jsonl` must be valid JSON, ≤ 1 MiB per line; anything larger goes through an artifact reference
- After entering `purged`, everything in the directory except `meta.yaml` and `audit.log` must be cleared
- At no time may a Session contain unredacted PII / secrets (**this is the compliance baseline**)

## 10. Extension points

- `meta.yaml.extensions.<vendor>` — vendor/tool custom metadata; must not conflict with defined fields
- `trace-event.extensions.<vendor>` — custom event subtypes; must use a namespace prefix
- Custom evaluators (harness) may read the trace but must not write back to the Session

## 11. Memory integration

Contract between Session and the `memory/` directory:
- **Short-term memory** reuses `trace.jsonl`; context-window management and summarization policy are in `memory/templates/short-term-config.template.yaml`
- **Retrieval injection**: triggered in the trace via `tool_call: kb.search` / `tool_call: memory.search`; results are written back via `tool_result` and referenced as footnotes in subsequent prompts
- **Archive harvesting**: when a Session moves from `archived` into finalize, candidate facts are written to mid-term memory per the `harvest_to_mid_term` rules (candidate_review by default, requiring user confirmation)
- **Retrieval request/response** schema: see `memory/schemas/retrieval-query.schema.json`
- **Hard requirement**: content entering memory must already be redacted (consistent with the redaction integration point in §5)
