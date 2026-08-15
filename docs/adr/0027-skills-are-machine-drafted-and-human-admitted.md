# Skills are machine-drafted and human-admitted; there is no automatic promotion

Status: accepted (2026-08-14)

`CONTEXT.md` describes Skills that are distilled from high-scoring Sessions and
evolved by the iteration engine through harness-gated promotion. ADR-0022 scoped
that out of v1 and kept hand-authored Skills decoupled from the engine. This ADR
resolves the remaining question — whether the automatic path is a deferred
feature or a rejected one.

## Decision

**Machine drafts, human admits.** A Skill may be drafted by a model — from a
description, as `skill_drafter.py` already does, or from a distilled Session per
ADR-0026 — but it enters `agent_skills/` only through a human review and a
commit. Harness scores may inform that review. They do not replace it.

**Automatic promotion is rejected, not deferred.**

The reason is what a Skill contains. Its valuable part is not the procedure —
procedures are recoverable from documentation — it is the two lines a procedure
does not have: **when to stop**, and **what the agent must not touch**. Those are
judgements about blast radius and about which conflicting goal loses. They are
not derivable from a transcript of a Session that went well, because a Session
that went well never exercised the boundary.

A harness cannot catch this either. It scores whether the artifact was right on
its fixtures; a Skill with a stopping condition set one step too late scores
perfectly on every case where stopping late was harmless.

## Trade-off accepted

Skill supply is gated on human attention, so the bank grows slowly. That is
accepted. The alternative failure is an agent that gradually widens what it acts
on, with no event marking when it started — a Skill was promoted, the boundary
moved, and nothing in the trace says so, because from the system's point of view
nothing went wrong.

## Consequences

- `CONTEXT.md`'s Skill entry must stop promising harness-gated promotion as a
  live path. The iteration engine keeps evolving *playbook* variants; Skills are
  out of its scope by decision now, not by sequencing.
- The review has a specific job, and it is not proofreading the procedure. The
  reviewer checks the stopping condition and the `allowed_tools` list. A Skill
  whose procedure is excellent and whose stopping condition is absent is
  rejected, not merged with a follow-up issue.
- This is the product-side statement of the same boundary the assistant is being
  built to enforce: execution can be delegated, and the decision about where
  execution stops cannot.
