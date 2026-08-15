# Distillation target follows the shape of the knowledge

Status: accepted (2026-08-14)

`wiki/query_to_page.py` already distils a qualifying **Session** into a wiki
page: it triggers on ≥ 2 `kb_search` calls or a `user_action.accept` event,
gates on archived-and-not-restricted, and writes a `draft` page for a human to
promote. Meanwhile `ROADMAP.md` lists "Skill distillation" as the largest gap
between the glossary and the code.

Both statements are true, and together they misdescribe the problem. The
distillation *machinery* exists. What is missing is a rule for **which of the
two artifacts a Session should become** — and without that rule, building a
second distiller would just produce two pipelines racing for the same Sessions.

## Decision

The target is chosen by the shape of the knowledge the Session produced.

- **Declarative knowledge — what a thing is, why it exists, how it is put
  together — distils to a wiki page.** The reader needs to understand
  something. Success is comprehension.
- **Procedural knowledge — how to work a problem, in what order, and when to
  stop — distils to a Skill.** The reader (human or agent) needs to *act*.
  Success is a resolved problem.

The operational test is the presence of a **stopping condition**. A body of
knowledge that converges by repeated attempts — try, observe, narrow, try
again — has one, and that is a Skill. A body of knowledge that is understood by
reading it does not, and that is a page.

This borrows **Responsibility Shape** (harness / loop / graph) from the
`Operation_Undock` workspace, cited rather than copied — see `CONTEXT.md`.
A loop-shaped resolution path is the signal for a Skill.

## Trade-off accepted

The test is a judgement call at the margin, and some Sessions will qualify as
both. When they do, the page is written and the Skill is not: a page is cheap,
reversible, and inert, while a wrong Skill actively steers an agent. The
asymmetry is deliberate — over-producing pages is clutter, over-producing
Skills is misdirection.

## Consequences

- `query_to_page`'s trigger conditions stay as they are. A second trigger, for
  the Skill path, has to detect loop-shaped resolution — repeated tool calls
  narrowing on one hypothesis — which is a different signal from the
  synthesis-worthy one it already uses.
- The glossary needs **wiki page** as a term. It currently has none, even
  though the module ships with a full lifecycle, a linter, and API routes.
- `ROADMAP.md`'s "Skill distillation" line is now narrower than it reads and
  should be restated: the gap is a Skill-shaped *target*, not distillation.
