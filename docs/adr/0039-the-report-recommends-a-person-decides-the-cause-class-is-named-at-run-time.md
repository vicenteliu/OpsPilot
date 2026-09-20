# The report recommends, a person decides; the cause class is named at run time

Status: accepted (2026-09-19)

Every run closes one ticket: a Work item becomes a KB-cited suggestion and
leaves an archived Session with a trace and an `incident_summary_v1` artifact.
What the corpus of those runs could say — *this month, half the P2s were the
same class of thing, and here is the one fix* — nobody was reading. #220 asked
for that report. Two decisions shape it.

## Decision 1 — the cause class is named by the run, not by the report

`incident_summary_v1` gains one optional field, `cause_class`, with four
members: `user_error` · `server_side` · `process_or_kb_gap` · `unknown`. The
summary playbooks ask for it in the same breath as `scope` and `severity`.

The alternative was to classify at report time — one cheap call per archived
summary, the `triage` pattern. It would have covered history and left the
pipeline alone. It was rejected because the answer would not be durable: the
same ticket could fall into a different class on the next report, and a report
whose rows move under re-runs cannot be the evidence for a change request.
A class named once, at run time, sits in the artifact next to the citation it
came from and never moves.

Artifacts written before the field existed carry no class. The report puts
them in an `unclassified` row, sorted last, and says so. **They are not
guessed at.** If a person wants them counted, the honest move is to re-run a
sample under the new prompt.

## Decision 2 — the fix per class is fixed text

`opspilot report recurring` prints, per class, a count, a share, the
severities inside it, the KB pages it cited most, and a recommended fix. The
fix is a sentence decided when the class was defined — *update the cited page
or the intake form* for a KB gap, *file the change against the cited component*
for server-side — not one generated per report.

This is [ADR-0006](0006-processing-layer-not-system-of-record.md) applied one
level up. OpsPilot processes; the person decides. A generated recommendation
would read as a decision already made, with the report's numbers as its
justification. A fixed one reads as what it is: the meaning of the bucket, with
the tickets in it as the evidence, and the decision still in front of someone.

## What was left out on purpose

*"KB pages cited but marked unhelpful"* was in the issue. There is no such
signal today — the only feedback stream is skill iteration's `signals.jsonl`,
and the wiki lint knows orphans, not disapproval. Building the report on a
signal that does not exist would have meant inventing the signal first. When a
helpfulness mark on a suggestion is recorded, the report gets that column; not
before.

## Consequences

- `opspilot report recurring [--since 30d|all] [--until] [--format md|json] [--out]`.
  Reads archived Sessions only; makes no model call; costs nothing to run.
- The four `pb_ticket_summary_*` prompts ask for `cause_class`; a model that
  omits it still validates (the field is optional) and rolls up as unclassified.
- A fifth class needs a schema change, a prompt change and a fix sentence — a
  visible diff, which is the right cost for changing what the system may call
  a cause.
