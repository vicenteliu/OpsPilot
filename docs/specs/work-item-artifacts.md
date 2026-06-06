# Work item artifacts — design spec

Design for the Work item type system's artifact schemas and classification.
Companion to the domain language in [CONTEXT.md](../../CONTEXT.md) and the
positioning decision in [ADR-0006](../adr/0006-processing-layer-not-system-of-record.md).
Status: **design agreed, not yet implemented** (output of a grill-with-docs session).

OpsPilot is a *processing layer* (ADR-0006): every field below is **advisory** —
the external system of record owns final values.

## 1. Shared base contract

Every work-item artifact shares this base; each type adds an extension block.
One validator / UI / harness path handles the base across all types.

```jsonc
{
  "schema_version": "incident_summary_v1 | request_fulfillment_v1 | task_triage_v1",
  "work_item_ref":  "external identifier (already redacted)",
  "work_item_type": "incident | service_request | task",
  "summary":        "one-paragraph synthesis for a service-desk lead",
  "tasks":          [ /* Task objects — see §3 */ ],
  "missing_fields": [ "info the work item is missing" ],
  "citations":      [ /* KB chunk refs, unchanged from ticket_summary_v1 */ ]
}
```

`tasks[]` is the decomposition product: processing an Incident or Service Request
emits zero or more assignable Tasks. For a standalone `task` input, `tasks[]`
holds at most the refined single task.

## 2. Per-type extension blocks

**incident** (`incident_summary_v1`) — evolves the current `ticket_summary_v1`:
```jsonc
{ "symptoms": ["..."], "scope": "single_user|multiple_users|site_wide|unknown",
  "severity_suggested": "P0..P4" }
```

**service_request** (`request_fulfillment_v1`) — new:
```jsonc
{ "requested_item": "what is being asked for",
  "approval_needed": true }      // whether fulfillment requires sign-off
```

**task** (`task_triage_v1`) — minimal; base + a refined single action (carried in
`tasks[0]`). No extra block in v1.

## 3. Task object

The element type of `tasks[]`. Minimal upgrade of the old `next_actions[]` —
adds a local `ref` and a routing `tier`. No status / assignee (those are the
system of record's, per ADR-0006).

```jsonc
{
  "ref":       "task-1",                 // local handle, like citations' kb-1
  "action":    "Restart the VPN gateway",
  "rationale": "Gateway unresponsive per KB runbook",
  "tier":      "L1 | L2 | L3",           // suggested support line
  "citations": ["kb-3"]                  // optional; KB chunk refs
}
```

## 4. Classification

When the input does **not** declare `work_item_type`, a lightweight LLM
classification playbook assigns it. Declared types are trusted and skip this.

```jsonc
// classification playbook output
{ "work_item_type": "incident | service_request | task",
  "confidence": 0.0,                     // 0..1
  "rationale": "one line" }
```

Low confidence (threshold TBD) surfaces a human-confirm prompt rather than
silently routing to a playbook. Runs as its own step before the typed Session;
reuses the existing provider / Session machinery (no new infra).

## 5. Migration (ticket_summary_v1 → incident_summary_v1)

1. Rename `orchestrator/schemas/ticket_summary_v1.schema.json` →
   `incident_summary_v1.schema.json`; restructure to base + incident extension.
2. Upgrade `next_actions[] → tasks[]` (add `ref`, `tier`; keep `action`,
   `rationale`, `citations`).
3. Add `work_item_ref` (rename of `ticket_ref`), `work_item_type: "incident"`.
4. Keep `ticket_summary_v1` as a deprecated alias for **one** version; harness
   `golden.json#schema_check` and the `examples/scn_ticket_summary_*` fixtures
   migrate alongside.
5. New playbooks: `pb_request_fulfillment_*`, `pb_classify_work_item_*`.

## 6. Out of scope (this iteration)

- Problem / Change work-item types (need lifecycle OpsPilot does not own).
- Any work-item lifecycle / status / assignment / SLA (lives in the system of
  record — reversing this is a separate ADR).
- Per-task independent `priority` (overlaps incident `severity_suggested`).
- `depends_on` task ordering and `assignment_group_hint` (deferred — revisit if
  routing needs more than `tier`).
