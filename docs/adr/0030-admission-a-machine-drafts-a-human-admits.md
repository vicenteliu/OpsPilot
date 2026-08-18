# Admission: a machine drafts, a human admits, and the admission is an event

Status: accepted (2026-08-18)

Three decisions have now landed the same shape without naming it. ADR-0027:
a model may draft a Skill, but it enters `agent_skills/` only through a human
review and a commit. ADR-0028: a Session may propose an action, but it runs only
when a human presses execute. Adding **Memory** (ADR-0031) produces a third
instance — the assistant proposes a fact about the environment, a human confirms
it.

Writing a third parallel ADR would record the same reasoning a third time and
leave a future reader to notice the pattern on their own. Name it once instead.

## Decision

**Admission** is the act by which a human moves a boundary that the machine may
prepare but may not cross. It has three properties, and all three are load-bearing.

1. **The machine may draft.** Drafting is the part models are good at, and
   nothing here restricts it. A drafted Skill, a proposed command, a suggested
   Memory entry are all welcome output.

2. **A human performs a discrete act.** Not a configuration, not a default, not
   a threshold — an act, by a named person, at a moment in time. What the act
   moves is always the same kind of thing: what the system may **do** without
   being asked again (a Skill's `allowed_tools`, an executed command) or what it
   may **believe** without being told again (a Memory entry).

3. **The act is recorded, and the record is the point.** A merge commit, a trace
   event, a Memory entry stamped with its actor from the caller's identity. The
   value is not the gate — a determined operator clicks through any gate. The
   value is that six months later there is a timestamp and a diff for every
   movement of the boundary.

**Admission is per-item, and the admitter must hold what it takes to judge.**
Delay and distance are not the problem. A Skill is admitted in a pull request
days after a model drafted it; a proposed action is admitted from a list some
time after the Session that proposed it. Both are admissions, because each item
is judged on its own and the admitter has what the judgement needs — a Skill's
diff shows its stopping condition and its `allowed_tools`, and a proposed action
arrives with its command, target, dry-run preview, and gate verdict.

Two things defeat it. **Batching**: approving a list without reading it is a
click that is never withheld, which is not a decision. And **a missing basis for
judgement**: an item whose judgement needs context the admitter no longer has
cannot be admitted later at all, however carefully it is read.

The second failure is why a Session may not propose a **Memory entry**
(ADR-0031). Judging one means deciding whether a sentence was a conclusion or a
guess floated mid-investigation, and that is legible only to someone who was
there. A day later the reviewer holds the sentence but not the moment it was
said in, and there is nothing left to judge it against.

## Trade-off accepted

Everything gated this way grows at the speed of human attention: the Skill bank
grows slowly, actions run one at a time, the Memory store fills a fact at a
time. That cap is real and it is accepted.

The alternative failure is worse because it is silent. A system that widens what
it does or believes without an admission event does not report an error when it
widens too far — from its own point of view, nothing went wrong. There is
nothing to re-examine afterwards, because nothing was written down.

## Consequences

- ADR-0027 and ADR-0028 are instances of this rule, not independent decisions.
  Neither is superseded; both are now readable as the same sentence applied to a
  different boundary.
- Any future proposal to remove a human from one of these paths argues against
  this ADR, not against the specific one it touches. That is the intended effect:
  the question "should this run unattended?" should be asked once, at the level
  where it is actually the same question.
- Widening is still arguable, and the recorded admissions are the evidence it
  would be argued from. ADR-0028 already states the asymmetry: you cannot argue
  for unattended execution from a system that has never logged an attended one.
