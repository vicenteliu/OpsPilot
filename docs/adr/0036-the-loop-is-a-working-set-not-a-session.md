# The loop is a Working set, not a Session

Status: accepted (2026-08-18) — revises ADR-0026

ADR-0026 decided that a **Session** whose resolution was loop-shaped — converged
on by repeated attempts — distils to a **Skill**, and that a declarative one
distils to a **Wiki page**. The rule is right. The unit was wrong, and could not
have been right at the time: **Consultation** and **Working set** did not exist
yet (ADR-0032, ADR-0035).

A Session is one playbook run over one input, producing one artifact against a
schema. It is **harness-shaped by construction** — inputs, outputs and acceptance
are definable up front, which is the definition ADR-0026 borrows from
Responsibility Shape. Nothing about it is a loop. Trying to detect one inside it
would have meant reading a proxy — *"two or more `kb_search` calls"*, which is
what the Wiki path already triggers on, and which measures retrieval rather than
convergence.

## Decision

**A closed Working set is the loop.** It is a problem someone opened, worked
across several Consultations, and closed. The chain of those Consultations is the
record of the attempts.

**The criterion is how it closed, plus how long the chain is.**

- **Manually closed** — the person said the problem was finished, which is the
  only signal here that means *converged*. A set closed by the inactivity
  fallback was **abandoned**, and an abandoned investigation has no procedure in
  it.
- **At least two Consultations.** One conversation is a question, not a loop.

Rejected: judging convergence from tool-call args narrowing on a hypothesis. It
sounds precise and is brittle — someone searching the same term four times reads
as narrowing, and "narrowing" needs a semantic judgement to detect at all.

**It is offered at the moment the set is closed**, not by a scan. The same lesson
`pin_to_memory` already taught: the person closing knows what the procedure was,
and a nightly queue reaches somebody who has moved on. A queue also means batch
approval, which ADR-0030 names as the failure that defeats admission.

**The whole chain is the input, dead ends included.** Keeping only the steps that
worked produces something that reads like documentation and cannot be reproduced.
A procedure's most useful content is what to rule out and in what order, and that
only exists in the branches somebody walked into and backed out of.

**The stopping condition and `allowed_tools` are left blank, and the drafter
refuses to guess them.** ADR-0027 is specific: they are a Skill's load-bearing
content, a run that went well never exercised either, and a Skill whose procedure
is excellent and whose stopping condition is absent is *rejected, not merged with
a follow-up issue*. A guessed stopping condition reads perfectly well, gets
skimmed, and gets merged. **A blank field cannot be rubber-stamped; a filled one
can.**

**The default outcome is an amendment to an existing Skill, not a new one.** One
Skill covers a subsystem, not a single failure; fragmenting the bank is a named
failure mode, and the `load_skill` catalog rides in context, so a bank that grows
once per incident spends exactly the tokens progressive disclosure was meant to
save. Creating a new Skill requires a typed reason, which travels with the draft.

An amendment is also **more reviewable, not less**: it arrives as a diff, and a
diff is what ADR-0027's review reads. A new file has to be read whole.

**Only the author may distil their own Working set.** A Consultation is visible
to its author and to admins, and that privacy is what buys it "cheap" — people do
not weigh their words on a surface nobody browses. An admin turning someone
else's private chain into a team artifact is a different act: **read for audit,
not publish.**

## Trade-off accepted

Requiring a manual close means a solved problem whose owner simply moved on is
never distilled, and those are common. Accepted: the alternative is distilling
abandoned investigations, which produces confident procedures for problems nobody
actually solved.

Leaving two fields blank guarantees every draft is incomplete when it lands. That
is the intent. The reviewer's job under ADR-0027 has exactly two items, and a
draft that appears to have done them already turns that review into a formality.

## Consequences

- ADR-0026's *rule* stands — declarative distils to a page, procedural to a Skill,
  and when a body of work qualifies as both the page wins because a wrong page is
  clutter and a wrong Skill is misdirection. Only its unit changes.
- A **Consultation** gains `working_set_id`, set when the conversation starts
  under an open set. Without it a chain is not identifiable, and the chain is the
  whole input.
- `wiki/query_to_page.py` is untouched. It still triggers on a Session, and now
  the two paths measure different things rather than the same proxy.
- Drafting uses the designated thinking-tier model. It is the most
  judgement-heavy generation the product does — the output steers another agent
  rather than informing a person — and it runs once per closed Working set, so
  choosing it for cost would be saving in the wrong place.
