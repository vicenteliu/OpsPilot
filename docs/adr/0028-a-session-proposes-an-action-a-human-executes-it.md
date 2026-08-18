# A Session proposes an action; a human executes it

Status: accepted (2026-08-14)

`SandboxEngine` (validate → dry-run → [approval] → apply, L2 hardened container
or L3 gVisor) is reachable from the CLI (`opspilot sandbox …`) and from
`/api/sandbox`, but nothing in the orchestrator can reach it. A Session today
produces a suggestion and stops; anything that runs is driven by a person who
retyped it somewhere else.

## Decision

Close the loop one notch, and only one notch:

1. A **Session** may emit a proposed **action** as part of its artifact —
   the command, the target, the level, and the reason it is being proposed.
2. The UI surfaces it with its dry-run preview and the **approval gate**'s
   verdict.
3. A **human presses execute.** The `SandboxEngine` runs it.
4. The result — request, preview, gate verdict, who pressed, outcome — appends
   to the Session's trace.

**Automatic execution is not in this step**, including for actions the gate does
not flag. The gate is a heuristic denylist and says so in its own docstring; it
is a defence-in-depth signal, not a security boundary, and it is not the thing
that should decide whether an action runs unattended.

## Trade-off accepted

A human in the loop caps throughput, and for the large class of routine actions
whose acceptance can be checked automatically, that cap is pure cost. Accepted
for now: the value of this step is not saved keystrokes, it is that the boundary
between proposing and doing becomes **visible in the product and recorded in the
trace**. That record is the prerequisite for ever widening it — you cannot argue
for unattended execution from a system that has never logged an attended one.

## Consequences

- The artifact schema gains an optional proposed-action block, versioned like
  every other artifact schema. Playbooks opt in; existing ones are unaffected.
- The trace gains the execution as first-class events, so a Session becomes
  replayable end to end: retrieval, suggestion, approval, run, result.
- OpsPilot stays a processing layer (ADR-0006). Proposing and running a scoped
  command inside an ephemeral container is not becoming a system of record.
- The natural next step — auto-executing actions whose acceptance is
  machine-checkable — is now a separate, arguable decision with evidence behind
  it, rather than a default that arrived by omission.
