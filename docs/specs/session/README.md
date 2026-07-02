# Session — Session & Trace Spec

> **Status**: spec only — schemas, templates, policies. No runtime implementation here.

## TL;DR
A Session is the packaged unit of "context + trace + artifacts + audit" for one AI task. It is the vehicle for OpsPilot compliance (redaction / audit / retention / replay), and the input/output anchor for Sandbox and Harness.

## Where it sits

```
playbooks/  ──▶  Session(create)  ──▶  prompt/LLM
                       │
                       ▼
                 proposed_action  ──▶  sandbox/  ──▶  artifact
                       │                                │
                       ▼                                ▼
                 Session.trace  ◀───────────  recording
                       │
                       ▼
                 harness/(eval)  ──▶  case-studies/
```

## Scope

In scope:
- Session lifecycle and state machine
- Data model (meta / trace / artifact / audit)
- Redaction integration point
- Retention policy
- Replay & diff semantics

Out of scope (not in this directory for now):
- Concrete storage implementations (Postgres / SQLite / filesystem)
- UI / web console
- Quota & billing

## Directory layout

```
session/
├── README.md                         # This file
├── SPEC.md                           # Detailed spec
├── schemas/
│   ├── session.schema.json           # Top-level Session metadata
│   └── trace-event.schema.json       # Trace events
└── templates/
    ├── session-meta.template.yaml    # Copyable session metadata example
    ├── redaction-rules.template.yaml # Default redaction rules
    └── retention-policy.template.yaml# Default retention policy
```

## On-disk layout (recommended)

```
sessions/<session_id>/
├── meta.yaml          # Conforms to schemas/session.schema.json
├── inputs/            # Redacted raw inputs
├── trace.jsonl        # One trace event per line, conforming to trace-event.schema.json
├── artifacts/         # Artifacts (scripts, SOPs, diffs, reports)
└── audit.log          # Append-only, audit events
```

## ID conventions
- `session_id`: `sess_<ULID>` (time-ordered, distribution-friendly)
- `trace_id`: `trc_<ULID>`
- `artifact_id`: `art_<sha256[:16]>` (content-addressed, for dedup and tamper resistance)

## Quickstart (for spec readers)

1. Read `SPEC.md` — field semantics, state machine, hard requirements
2. Start new session metadata from `templates/session-meta.template.yaml`
3. Align redaction rules between `governance/redaction.md` and this directory's `redaction-rules.template.yaml`
4. Decide the retention class → apply `retention-policy.template.yaml`

## Contracts

| Upstream | Input to Session |
|---|---|
| `playbooks/` | playbook_id (required), version |
| `prompts/` | Referenced prompt ids and versions |
| `governance/` | Redaction rules, retention policy, RBAC |

| Downstream | What Session provides |
|---|---|
| `sandbox/` | Proposed action (the `tool_call` in a trace event) |
| `harness/` | trace.jsonl as evaluation input |
| `case-studies/` | Redacted summaries of archived Sessions |

## Open questions

- [ ] For multi-user collaboration, is `owner` single-valued or multi-valued (owner + collaborators)?
- [ ] When `parent_id` is used for replay, do we need branch semantics (a fork tree)?
- [ ] Should artifacts be signed (cosign / minisign) to satisfy audit requirements?
