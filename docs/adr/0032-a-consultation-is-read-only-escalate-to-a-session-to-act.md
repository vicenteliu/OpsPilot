# A Consultation is read-only; escalate to a Session to act or to distil

Status: accepted (2026-08-18)

`POST /api/chat/stream` has existed for some time and appears nowhere in the
glossary. It is stateless — the client resends the whole `messages` array each
turn — and it is where an operator actually talks to the assistant: KB-grounded
answers, `load_skill`, web search, MCP tools.

Meanwhile a **Session** is defined as one playbook run tied to one input,
explicitly *not* a multi-turn conversation, and everything valuable about it
depends on that: it is replayable, scoreable by the harness, and the trace that
ADR-0028 hangs execution records on.

Framing the product around a conversational assistant therefore forces a choice.
Redefining Session to mean "a conversation" would dilute the one unit the harness
and the audit trail are built on.

## Decision

Name the conversational surface a **Consultation**, leave **Session** untouched,
and make the Consultation deliberately weak.

### A Consultation may read, and propose one thing

It searches the KB, reads Memory, loads Skills, calls MCP tools — and it may
propose a **Memory** entry for the human in front of it to admit (ADR-0030).

**It may not propose an action, and it may not be distilled.** Both of those
capabilities rest on machinery a Consultation does not have: ADR-0028 hangs the
whole propose → approve → execute → record chain on a Session's trace, and
`wiki/query_to_page.py` gates distillation on a Session's lifecycle
(`archived`, not `restricted`). Granting them to Consultations means duplicating
both gates onto something with no lifecycle to hold them up.

### To act or to sink knowledge, escalate to a Session

Escalation carries **a Work item description and nothing else** — written by the
human or drafted by the assistant. The Session then runs a playbook exactly as it
does today.

The conversation is not carried across, and this is the load-bearing part. A
**Fixture** is a frozen, versioned input package, and a Session's replayability
rests on its input having edges. Feeding an arbitrarily long transcript — small
talk, dead ends, pasted logs — into a Session makes it unfreezable, and the
harness is the gate a Stage is declared complete against.

Nothing is lost: the Consultation records `→ session_id` and the Session's trace
records `← consultation_id`. **The escalation is itself an audit record** —
exactly the kind of event ADR-0028 wants at the moment a boundary is crossed.

**Escalating pins the Consultation**, exempting it from the retention sweep
below. A Session's trace is permanent; without the pin its `consultation_id`
would dangle on day 91 and the audit record would survive in name only, pointing
at something the system deleted on a timer. Pinning is not free — an escalated
Consultation is precisely the one most likely to hold pasted production logs —
but it is the one whose contents an incident review a year later will need, and
it can still be deleted by hand.

### Private, and short-lived

A Consultation is visible to **its author and to admins**, and is cleaned up
after 90 days unless marked to keep.

Privacy is what makes it cheap. A surface colleagues can browse is one where
people weigh their words, and a surface where people weigh their words is a poor
troubleshooting tool. Team value is not lost, because a Consultation is already
barred from distillation by design: knowledge leaves it by escalation to a
Session or by an admitted Memory entry, and both of those are team-visible and
both passed through a human.

The retention limit is what makes it low-risk. Consultations collect pasted
logs, configs, and stack traces, with none of the redaction a Work item passes
through on its way into a Session — so "cheap and low-risk" has to be paid for by
a retention policy, not asserted in a definition.

## Trade-off accepted

Two costs.

Escalation is friction, and some of it is pure overhead: an operator who already
knows what needs running still has to summarise it into a Work item. Accepted —
that summary is what keeps Sessions replayable.

Per-user visibility introduces the **first per-user data scope in the repo**.
KB, Skills, Wiki, Inventory, and Memory are all instance-global; Consultations
will need their own authorisation checks, admin override, and deletion
semantics. This is a genuine complication accepted for a specific reason, and it
does not open the door to per-user scoping elsewhere — Memory in particular is
team-global by decision (ADR-0031).

## Consequences

- `CONTEXT.md` gains **Consultation** and **Working set**.
- The existing stateless `/api/chat/stream` is the ancestor of this surface. It
  gains server-side persistence, an author, a retention job, and a link to any
  Session it escalated into.
- A **Working set** — the "what I am currently chasing" context that spans several
  Consultations — must close. It closes by hand, with an unconditional
  inactivity fallback, and **the fallback announces itself in the next
  Consultation**: a working set that silently expired leaves the operator
  misreading why the assistant lost the thread.
- Neither a Consultation nor a Session is exportable (ADR-0033); both are local
  ledgers.
