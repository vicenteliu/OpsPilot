# Decisions on a Work item are Judgments; a Playbook writes only what no one has written

Status: accepted (2026-09-23)

> **Revised 2026-10-12** (#225, #281): decision 1 was measured on the label set, against d1-v1
> and against a narrower d1-v2 relabelled blind. No cut stopped every labelled security item
> without stopping nearly every Work item, so by this ADR's own rule it is not ready to be
> automated. Until it is, the stage runs decision 2 without it and says so at startup;
> "Security runs first" below holds once decision 1 is measured for its engine.
>
> **Revised 2026-10-12** (#226, #286): decision 9 was measured on the label set, each engine
> shown every candidate page's passage and then its whole page. Neither engine says a page fixes
> the Work item: a cut that keeps the fixes sent 95% right sends 25 of 240 at most. So decision 9
> is not ready to send a known fix, and every run reaches the summary Playbook as before. Jev
> does rank the pages: for about nine in ten rows with a fix, the page it finds likeliest fixes
> it, against seven in ten for retrieval's first hit. #286 weighs showing the person the pages in
> that order.
>
> **Revised 2026-10-15** (#227): Impact and Urgency were measured on the label set's Incidents,
> and each has a cut per engine. Severity is read off the table only when both clear their cuts
> and come from the primary engine; the summary Playbook is then given it and its artifact carries
> it. Below either cut, Severity is not a decision a person must make before the run goes on: the
> summary Playbook suggests one as it did before the stage, and both Judgments are in the trace.
> The table is `judgments/decisions/severity.yaml`. No Incident in the set is site-wide, so
> Impact's highest level is not yet measured (#288).
>
> **Revised 2026-10-16** (#288): twelve site-wide Incidents were drafted and labelled for impact and
> urgency apart from the set, and decisions 7 and 8 measured again on all 51. Both engines answer
> `site_wide` for every one labelled so; Jev's cuts move to 0.66 (Impact) and 0.86 (Urgency), the
> Playbook model's stay at 0.45 and 0.70.
>
> **Revised 2026-10-16** (#228): the team list is decision 6's answer space, `d6.yaml`, so a
> changed list is a new version measured again. On the label set's Incidents both engines picked
> the labelled team every time. A team that clears its cut from the primary engine replaces the
> summary's free-text escalation hint. Below it, or from the fallback, the hint says a person picks
> the team; the run itself goes on.
>
> **Revised 2026-10-16** (#229): decision 4 is asked first of an Incident, and only a `no` that
> clears its cut from the primary engine holds the summary back; any other answer runs it as
> before, listing what is missing. The ask, written by `pb_ask_en`, goes out once: as a JSM comment,
> whose key the poller then watches for a reply, or as a Telegram reply, whose chat's next message
> is taken as one; the webhook logs it. A reply re-runs the Work item from decision 1 with its type
> as decided, so decision 2 is not asked again, and decision 4 is not asked a second time. On the
> label set only 4 of 39 Incidents are too thin, so its cut rests on very little.
>
> **Revised 2026-10-16** (#230): decision 3 is asked only where a source can list open Work items:
> on JSM the intake adapter queries its own JQL scope for issues created in the last hour and not
> done, and sends them with the run. Each is an answer, keyed by its key, beside `none`. The set's
> rows are distinct problems, so decision 3 is measured on items of its own: a drafted duplicate of
> each Incident, offered among five open Work items, and each Incident offered five that are not.
> At their cuts both engines name a match 95% rightly, finding nearly every duplicate. A match that
> clears its cut is named in the comment, and nothing below it is said.
>
> **Revised 2026-10-16** (#231, #293, #294): the request path starts with one Judgment, which
> catalog item, a Choice over a sample catalog (`judgments/decisions/catalog.yaml`, `r1.yaml`).
> An item that clears its cut is looked up for its approval, entitlement (the submitter's role),
> stock (Assets in stock, ADR-0017) and automation, and its looked-up `approval_needed` replaces
> the model's. An automated item runs no Playbook. Below the cut, or no item, the request
> Playbook runs as before and a person checks the item. Whether it is really a request (#293) and
> whether it gives enough to fulfil (#294) are filed. A changed catalog is a new answer space.
>
> **Revised 2026-10-17** (#293): r2 asks whatever is filed as a request, declared or decided,
> whether it is a request, an incident or a change. Measured on all 80 rows as if filed as
> requests, at its cut Jev names 132 of 141 incident answers and 15 of 33 change answers, 95.5%
> rightly. An incident that clears its cut takes the incident path; a change stops for a person,
> OpsPilot having no change path; anything else stays a request. The labeller, labelling r2, called
> 8 of the 41 requests incidents: a disagreement with their own type labels, which d2's report
> still uses.
>
> **Revised 2026-10-17** (#294): r3 asks a request whose catalog item stood, and is not automated,
> whether it gives what the item's `fields` say fulfilling it needs. Measured on the 25 requests
> with an item, at a P(no) of 0.51 Jev asks about 41 of the 48 answers labelled `no` and none of the
> 27 labelled `yes`. A `no` that clears its cut holds the request back for one ask, written by
> `pb_ask_en` for the missing fields, through the reply loop of #229; the reply runs it again as a
> request. The request path's three Judgments are now built.
>
> **Revised 2026-10-17** (#286): a Judgment may order what a person reads without deciding
> anything; see "Ordering is not deciding" below. Decision 9 now orders each Work item's handbook
> pages, likeliest fix first: on the rows with a fix the first page is one for 89% of Jev's orders,
> against 70% of retrieval's.

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

## Ordering is not deciding

A Judgment asked only to order candidates for a person needs no cut: nothing is decided, and
below no threshold does anything change hands. Decision 9 cannot send a known fix on its own
(#226), but its P(yes) ranks a Work item's handbook pages, the prefetch's own, better than
retrieval does, so the person reads them likeliest fix first (#286). The order is measured on the
label set against the source's, and is shown, not used. One engine scores every candidate,
because two engines' probabilities do not compare; if it fails on one, the source's order stands.

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
