# ADR-0006: OpsPilot is a processing layer over work items, not a system of record

**Status**: Accepted
**Date**: 2026-06-05
**Stage**: 5 (work item type model)

## Context

To cover IT support beyond a single implicit "ticket," OpsPilot is introducing a
**Work item** type system — Incident, Service Request, Task (see CONTEXT.md). The
foundational question is whether OpsPilot owns these work items (stores them,
runs their lifecycle, assigns and closes them) or merely processes work items
that live elsewhere.

## Decision

OpsPilot is a **processing layer**, not a system of record.

- A Work item's **authoritative state and lifecycle live externally** — an ITSM
  platform (ServiceNow / Jira / Zendesk) or a JSON input. OpsPilot does not do
  CRUD, status state machines, queues, assignment, SLA timers, or notifications.
- OpsPilot's job is the per-item processing loop: **type → playbook → artifact**.
  It *suggests* (Severity, Tier, Tasks) and *cites* (KB chunks); the external
  system decides and persists.

## Rationale

- Matches the existing single-user, local-first, no-auth positioning (ADR-0002).
  A system of record implies multi-user state, auth, durability, and integrations
  that contradict that scope.
- The compounding-knowledge value (KB citations, skill distillation, wiki) is in
  *processing quality*, not in being another ticket database — organizations
  already have one.
- Keeps the surface small: OpsPilot maps cleanly onto its current
  Session → Playbook → Artifact model; a Work item is just the typed input to a
  Session.

## Consequences

- Outputs are **advisory**: `severity_suggested`, suggested `Tier`, decomposed
  `Tasks` — never the system-of-record's final values.
- No incident/request/task lifecycle, status, or assignment is built in OpsPilot.
  If lifecycle tracking is ever needed, it is a deliberate, separately-ADR'd
  reversal of this decision.
- Integration is import/export shaped (read a work item, emit an artifact), not
  ownership shaped.
