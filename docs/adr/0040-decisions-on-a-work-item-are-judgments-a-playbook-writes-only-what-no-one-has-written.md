# Decisions on a Work item are Judgments; a Playbook writes only what no one has written

Status: accepted (2026-09-23)

A Work item reaches a suggestion through a string of decisions, and today a
language model makes every one of them in prose. Classification is one call
that returns a type and a confidence the model scored itself; the run holds back
anything under 0.7, a threshold on a number nobody calibrated, and on JSM the
held-back item is marked processed and never heard of again. The summary
Playbook names scope, severity, cause class, missing fields and an escalation
hint in the same generation that writes the summary, so none of those decisions
can be thresholded, measured or priced on its own.

A typed judgment model offers a different shape. TypeSafe's Jev (released
2026-09-19) takes a state, a question and the answers it may give, and returns
one of them with a probability calibrated against outcomes: no reply, no
reasoning trace, at a vendor-stated fraction of a cent per call
(docs.typesafe.ai/concepts/system-one, docs.typesafe.ai/models). Calibration
holds across groups of predictions, not for any single answer, which is why
every threshold below is set from labelled data. The design was settled in one
review on 2026-09-23. **Nothing below is measured yet.**

## Three kinds of decision

- **Lookup**: the answer follows from a table. It costs nothing and never calls
  a model.
- **Judgment**: the answer is picked from a set written down in the repo, and
  comes back with a calibrated probability.
- **Words**: someone has to write what no one has written yet. Only a
  Playbook's language model does this.

The rule that sorts them: **a decision is a Judgment only if its answer set is
written down; if a table can answer it, it is a Lookup.** A decision that fits
neither is not ready to be automated.

## The Judgments stage

A new stage, **Judgments**, runs before a Playbook is chosen. For an Incident it
asks, in this order:

| # | Decision | Kind | Answer space | On the answer |
|---|---|---|---|---|
| 1 | Security issue? | Judgment (Noul) | yes · no | yes: stop. No suggestion, no KB fix, a person |
| 2 | Incident or request? | Judgment (Choice) | `incident` · `service_request` | request: the request path |
| 3 | Already open? | Judgment (Choice) | open Work items from the last hour, or none | a match is named in the write-back comment |
| 4 | Enough to act on? | Judgment (Noul) | yes · no | no: 5 |
| 5 | What do we ask? | Words | none | the ask goes out; the reply re-enters at 4 |
| 6 | Which team? | Judgment (Choice) | the team list (default `network` · `systems`) | the escalation target |
| 7 | Impact | Judgment (Score) | `single_user` · `multiple_users` · `site_wide` | Severity |
| 8 | Urgency | Judgment (Score) | `stopped` · `slowed` · `worked_around` | Severity |
| 9 | Seen before? | Judgment (Score, then Noul) | KB candidates from `kb_search` | a match: the known fix |

Severity is then a Lookup over Impact × Urgency, and who receives a known fix,
the user or the service desk, is a Lookup over the handbook page it came from.

**A declared type, or an explicit Playbook, skips decision 2 and nothing
else.** Declared-first stays as it is for the type, but a declaration never
skips decision 1: a phishing mail forwarded with "please check this" arrives as
a request.

**Security runs first and stops the run.** Its threshold is set so that every
labelled security item reaches a person, and the false alarms are the price. A
wrong "not security" is the one mistake the next step cannot undo.

Code builds each candidate list, the last hour's open items from a JQL query and
the KB hits from `kb_search`; the model only picks. That is also why decision 9
cannot be a score floor: `kb_search` ranks by weighted RRF, and its scores do
not compare across queries.

## The engine, and what it may see

- Jev, through its three task types, Noul (yes or no), Choice (one of N, or
  none) and Score (ordered levels), behind a Judgment protocol of its own and a
  new provider kind, `typesafe`. The chat `ProviderProtocol` carries no
  probabilities, so it is not stretched to fit.
- The Playbook's model is the baseline every Judgment is measured against, and
  the fallback when Jev cannot be reached. The trace records which engine
  decided.
- The stage is **optional and off by default**. Off, OpsPilot runs exactly as it
  does today.
- It sends the redacted text only, through the same Redactor Classification
  already applies, and nothing a Playbook call would not already send.
- Every call it makes has a timeout. A Judgment that times out falls back and
  says so in the trace.

A local classifier was considered for the sake of local-first. Jev ships no
weights, and ADR-0034 already makes hosted models primary; everything outside
this stage still runs fully local.

## Where a model still writes

Two places, both where nothing has been written yet:

1. **The ask** (decision 5), when the report is too thin to act on.
2. **The brief for an unseen problem.** The summary Playbook runs only when
   decision 9 finds no known fix, and writes the diagnosis plan for the
   engineer with its citations, as it does today. When a fix is known, the fix
   *is* the handbook's text. Nothing is generated.

With the stage on, the summary Playbook receives the type, impact, severity and
team as inputs instead of deciding them in prose. With it off, nothing changes.

## Below the threshold, a person, and the person can see it

Every Judgment has its own threshold, set from the label set and never guessed:
decision 2 at the lowest value where the items it routes on its own are at
least 95% right, decision 1 so that no labelled security item is routed on its
own. Below a threshold the outcome is **needs a person**, and every surface with
a way back to a person shows it. The web banner and the Telegram reply stay as
they are. **JSM gets a comment naming the undecided decision and its
probability**, instead of today's behaviour, where the item is marked processed
and dropped (`intake/base.py`). The webhook answers before the run (ADR-0015),
so it logs.

## Answer spaces are repo files, not handbook content

The question, the answer space, the kind, the threshold and a version for each
decision live in files beside `playbooks/`, together with the team list, the
Severity table (Impact × Urgency to P0–P4; its values are policy and live in the
file, not here), a sample catalog (an organisation brings its own) and the
audience table (handbook page to `user` or `service_desk`). **An unmapped page
goes to the service desk**: a fix nobody reviewed for users never goes straight
to one.

SSC is not touched. It exposes markdown and nothing else, it does not know its
consumer, and a catalog is an organisation's private configuration
(ADR-0038).

## A Task is an output

The Work item type is `incident` | `service_request`, which is all
Classification and the JSM intake have ever produced. A Task is what a Work
item is broken into, never a third kind of input: no user files a task. ITSM
tools model it the same way. A request becomes requested items and catalog
tasks for the fulfillers, and an automated item gets no task at all. Problem
and change stay out of scope.

## "Already open" is advisory

Decision 3 names the likely open Work item in the write-back comment, and a
person links them. OpsPilot does not link, merge or close anything in the
system of record (ADR-0006, ADR-0013).

## Severity stays the word

Severity keeps its name and its P0–P4 scale, and becomes a Lookup over two
Judgments: Impact, which takes the `scope` values without `unknown` (a low
probability already says unknown), and a new Urgency. The glossary goes on
avoiding "priority".

## The request path

Which catalog item (a Choice over the catalog), then whether it is really a
request or an incident or change in disguise (a Judgment), then whether there
is enough to fulfil it (a Judgment, with the ask if not). Approval,
entitlement, stock and automation are Lookups against the item, and the output
is Tasks. An item the catalog does not have goes to a person.

Most of this path is Lookups because requests are pre-defined: the thinking was
done when the catalog was written. The model-decided `approval_needed` retires
once the item is known.

## Measurement

The label set: about 80 synthetic English Work items, written around SSC's
topics with deliberately ambiguous cases ("I cannot access X"), drafted by a
model from neither family being compared (a GPT or Gemini model through
OpenRouter, which OpsPilot already supports), labelled by a person, and
committed to this repo. Each row records the answer-space version it was
labelled against.

The first report compares Jev with the Playbook's model on decision 2 by
accuracy, Brier score, cost per call and p50/p95 latency. **Eighty rows is not
a benchmark**; what it buys is a threshold that was measured instead of
guessed. The numbers are published whichever engine wins.

Every Judgment records its answer, probability, engine, latency and price in
the trace. Classification keeps its token usage, which it discards today, so
the baseline's cost is measured, not assumed.

## Order of work

1. Decision 2 end to end, with the label set and the JSM "needs a person"
   comment.
2. Security (1).
3. Seen before (9), with the audience table.
4. Impact, Urgency and Severity (7, 8).
5. Which team (6).
6. The ask and its reply loop (4, 5).
7. Already open (3).
8. The request path.

## What was left out on purpose

- **Shadow mode.** OpsPilot has no live traffic to shadow; the label set is the
  measurement. The switch changes the engine, and the trace says which one ran.
- **Chinese.** The zh Playbooks are first-class, but a Chinese label set is its
  own piece of work, and its numbers are not mixed into these.
- **"Did it work?"**: reading the user's reply to a known fix and marking the
  page when the fix failed. It is the helpfulness signal ADR-0039 says does not
  exist, and it needs the reply loop first. A tenth decision, filed, not built.
- **Linking in the system of record** (see "Already open" is advisory).

## Consequences

- A `typesafe` provider kind behind a Judgment protocol, and a Judgments stage
  ahead of playbook selection in `_resolve_run_plan`; both off unless
  configured.
- One file per decision beside `playbooks/`, plus the team list, the Severity
  table, the sample catalog and the audience table.
- A known-fix run still archives a Session. Its artifact records the Judgments
  and the handbook page, so the recurring report (ADR-0039) keeps counting
  repeats, by the page that fixed them.
- `CONTEXT.md`: the Work item type loses `task`, and a Task is an output; new
  entries for Judgments, Judgment, Lookup, Security issue, Impact and Urgency;
  Severity is a Lookup.
- README: "incidents and service requests, broken into routable tasks".
- Issues, in the order of work: #224 (the first slice, with #223, the JSM
  item that needs a person and is dropped), #225 (security), #226 (seen
  before), #227 (Impact, Urgency, Severity), #228 (which team), #229 (the ask
  and the reply), #230 (already open), #231 (the request path). Filed, not
  scheduled: #232 (did it work?), #233 (a Chinese label set). Found on the
  way: #234 (the web UI's service-request choice runs the incident Playbook).
