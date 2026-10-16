# Label set v1: specification

The labelled Work items that the first Judgments slice (#224) is measured on. Source of the
requirement: ADR-0040, *The label set* and *Order of work*, step 1. This file says what the set
contains and how it gets made; the rows go in `label_set_v1.jsonl` beside it.

**Eighty rows is not a benchmark.** The set exists to give one decision a fair first comparison
and to set that decision's threshold. It is small, synthetic, English, and labelled by one person.
Every report that uses it says so.

## 1. What gets labelled

These columns now, the rest in their slices. Each is labelled against a versioned answer space.

| Column | Decision | Answer space | Version | Used by |
|---|---|---|---|---|
| `work_item_type` | 2 · Incident or request? | `incident` · `service_request` | `d2-v1` | #224 (this slice) |
| `security` | 1 · Security issue? | `yes` · `no` | `d1-v2` (was `d1-v1`) | #225 |
| `known_fix` | 9 · Seen before? | the candidate pages that fix the row, or none | `d9-v1` | #226 |
| `impact` | 7 · Impact | `single_user` · `multiple_users` · `site_wide` | `d7-v1` | #227 |
| `urgency` | 8 · Urgency | `worked_around` · `slowed` · `stopped` | `d8-v1` | #227 |
| `team` | 6 · Which team? | `network` · `systems` | `d6-v1` | #228 |
| `enough` | 4 · Enough to act on? | `yes` · `no` | `d4-v1` | #229 |
| `same` (in `already_open_d3_v1.jsonl`) | 3 · Already open? | an open Work item's key, or `none` | `d3-v1` | #230 |
| `catalog_item` | r1 · Which catalog item? | an item of `catalog.yaml`, or `none` | `r1-v1` | #231 |
| `really` | r2 · Really a request? | `request` · `incident` · `change` | `r2-v1` | #293 |

**`d2-v1`**, the definitions the Playbook's classifier already uses
(`playbooks/pb_classify_work_item_en/prompt.md`):
- `incident`: something is broken or degraded. It worked, or should work, and doesn't.
- `service_request`: an ask for something standard: access, an account, software, hardware, a
  change to a mailbox or group. Nothing is broken.

**`d1-v2`** (2026-10-12, #225), as `judgments/decisions/d1.yaml` states it: `yes` when the item
shows a sign of compromise or exposure: a suspicious link, attachment or message; an unexpected
sign-in, MFA prompt or account change; a lost or stolen device; malware behaviour; a password or
other credential that someone else may have, or that was shared with or asked for by someone who
should not have it; data sent to, or seen by, the wrong people. `no` when nothing suggests
compromise or exposure: a routine request or fault about access, accounts, passwords, MFA, keys or
certificates is `no` unless it shows one of those signs. When in doubt about compromise or
exposure, `yes`: the threshold for decision 1 is set so that every labelled security item reaches
a person, and false alarms are the price (ADR-0040).

**`d1-v1`**, superseded: `yes` when the item could involve compromise or exposure, including any
credentials "shared or requested". On this set 40 rows were labelled `yes` under it: the 12 the
drafter wrote as security items, and 28 it had not. Both engines scored those 28 like the rows
labelled `no`, so a cut that stopped every labelled `yes` stopped nearly every Work item
(`report_d1_v1.md`). Its labels are kept on each row as `security_d1_v1`.

**`d7-v1`** and **`d8-v1`** (2026-10-13, #227), as `judgments/decisions/d7.yaml` and `d8.yaml`
state them. Both are Scores, their levels in the order given here, and both are labelled on the
rows labelled `incident` only: ADR-0040 asks them of an Incident. A request's `impact` and
`urgency` stay empty.
- `impact`: `single_user` is one person, the reporter or one other they name, and also when the
  item does not say anyone else is affected; `multiple_users` is more than one person but not a
  whole site (a team, a floor, a group, several named people, "others have it too"); `site_wide`
  is everyone at a site or in the organisation, or a service everyone uses down for all.
- `urgency`: `worked_around` is working, with a workaround in use or nothing blocked now; `slowed`
  is still working, slower or with errors, with no workaround; `stopped` is unable to do the work
  it blocks at all until it is fixed.

**`d6-v1`** (2026-10-16, #228), as `judgments/decisions/d6.yaml` states it, its answers being the
default team list. Labelled on the rows labelled `incident` only, as `d7` and `d8` are.
- `network`: connectivity, Wi-Fi, VPN, DNS, DHCP, firewalls, switches, routers, and the links
  between sites.
- `systems`: everything else IT runs: endpoints and their software, accounts and identity, email
  and collaboration, servers, printers and business applications.

**`d4-v1`** (2026-10-16, #229), as `judgments/decisions/d4.yaml` states it, labelled on the rows
labelled `incident` only. `yes` when the item says what is wrong, who or what is affected, and
enough of where, since when, or what was seen (an error, a message) to start diagnosing; `no` when
an engineer would have to ask the reporter first.

**`r1-v1`** (2026-10-16, #231), as `judgments/decisions/r1.yaml` states it, over the sample
catalog `judgments/decisions/catalog.yaml` (`catalog-v1`): the catalog item a service request is
for, each meaning its name and description, or `none` when the catalog has no item for what is
asked. Labelled on the rows labelled `service_request` only. A changed catalog is a new answer
space, labelled and measured again.

**`r2-v1`** (2026-10-17, #293), as `judgments/decisions/r2.yaml` states it: whether a Work item
filed as a service request is really one. `request` is an ask for something standard for a
person; `incident`, something broken or degraded; `change`, a change to a shared service or its
configuration (a DNS record, a firewall rule, a server or network setting, a new integration).
Labelled on the rows labelled `service_request`; the rows labelled `incident` count as
`incident`, by their type, since the stage asks it of anything filed as a request, declared
wrongly or not.

**`d3-v1`** (2026-10-16, #230), as `judgments/decisions/d3.yaml` states it: whether a Work item
reports the same problem as one of the open Work items it is offered, or `none` when it is a
different problem, even on the same subject. The set's rows were drafted as distinct problems, so
decision 3 is measured on items of its own (§5, §6), not on a column of `label_set_v1.jsonl`.

## 2. Row schema (`label_set_v1.jsonl`, one JSON object per line)

| Field | Filled by | Notes |
|---|---|---|
| `id` | script | `LS1-001` … |
| `subject` | drafter | may be empty for a few rows (see §3) |
| `body` | drafter | 0–150 words |
| `channel` | drafter | `email` · `portal` · `chat` |
| `topic` | drafter | the SSC page it is written around (§3) |
| `draft_intent` | drafter | what the drafter meant: `incident` · `service_request` · `ambiguous`; **hidden from the labeller**, never ground truth |
| `draft_security` | drafter | `yes` · `no`; hidden, never ground truth |
| `work_item_type` | **person** | `d2-v1` |
| `security` | **person** | `d1-v2`; the `d1-v1` label it replaced is kept as `security_d1_v1` |
| `known_fix` | **person** | `d9-v1`: the `source_path` of each candidate page that fixes the row, `[]` for none; with `known_fix_labelled_by` and `known_fix_labelled_time` |
| `impact` · `urgency` | **person** | `d7-v1` · `d8-v1`, Incidents only; with `impact_urgency_labelled_by` and `impact_urgency_labelled_time` |
| `team` | **person** | `d6-v1`, Incidents only; with `team_labelled_by` and `team_labelled_time` |
| `enough` | **person** | `d4-v1`, Incidents only; with `enough_labelled_by` and `enough_labelled_time` |
| `catalog_item` | **person** | `r1-v1`, service requests only; with `catalog_item_labelled_by` and `catalog_item_labelled_time` |
| `really` | **person** | `r2-v1`, service requests only; with `really_labelled_by` and `really_labelled_time` |
| `label_confidence` | **person** | `high` · `low`. Low = "I picked, but it could go the other way" |
| `label_note` | person, optional | one line, only when the reason isn't obvious |
| `answer_space` | script | `{"d2": "d2-v1", "d1": "d1-v1"}` at labelling time |
| `drafted_by` | script | exact model id via OpenRouter + date |
| `labelled_by` · `labelled_at` · `labelled_time` | script | the labeller's handle; the UTC date; the UTC time to the second, stamped as each row is labelled. Rows labelled before `labelled_time` was added have the date only |

`draft_intent` against `work_item_type` is recorded because the disagreement is information: rows
where the drafter and the person split are the ambiguous ones, whatever the drafter intended.

## 3. What goes in (80 rows)

**By intended type**

| Intent | Rows | Why |
|---|---|---|
| clear `incident` | 36 | the common case |
| clear `service_request` | 28 | the other common case |
| deliberately `ambiguous` | 16 | where the threshold is decided: "I can't access X", "need X working again", "X isn't set up for me", a request written as a complaint, a break written as a request |

**Security**: at least **12** rows with `draft_security: yes`, spread across all three intents (a
phishing report is an incident; "please reset my password, I think someone has it" is both). Twelve
positives is thin for #225 and is stated there; this set's job is decision 2.

**By topic**, written around SSC pages so a later "seen before" slice has something to match, at
most 8 rows a topic:
VPN and remote access · identity and access (accounts, MFA, SSO) · endpoint management (enrolment,
policies, patching) · endpoint encryption and keys · provisioning (new machine, reimage) · Microsoft
365 · other SaaS admin · web and TLS (expired certificates, internal sites) · site network (Wi-Fi,
DNS, printers on the network) · ITSM and assets (hardware requests, returns, loaners) · working with
security.

**By form**, so the set is not all tidy one-paragraph tickets:
- 10 one-liners (subject only, or a body under 12 words)
- 8 long and rambling (100–150 words, the real issue in the middle)
- 6 non-native English
- 6 with pasted error text
- 4 forwarded emails (a quoted thread, the ask at the top)
- 3 with two issues in one item (label the one that would drive the ticket; note it)
- the rest ordinary

## 4. What must not go in

- **No real company data.** No real employer, colleague, customer, internal system or incident. No
  names of real people. Domains are `example.com` / `example.org`; people are obviously fictional.
- Public product names are fine (Microsoft 365, Okta, Jamf, GlobalProtect, Zoom): tickets name
  products.
- No PII that the redactor would have to catch. The set should pass through redaction unchanged.
- English only. A Chinese set is #233.

## 5. Drafting

- **Model**: one GPT or Gemini model through OpenRouter (ADR-0040: neither family being compared).
  The exact model id and the date go in `drafted_by`; the drafting prompt is committed as
  `DRAFT_PROMPT.md`.
- **Batches**: 8 calls of 10 rows, each call given its quota from §3 (intent, security, topic, form)
  so the mix is set by the script, not left to the model.
- **After drafting**: drop near-duplicates (same topic and near-identical subject), redraft to fill
  the gap, shuffle, assign ids.
- **Cost cap**: $1 for drafting; about $0.50 expected.

**Site-wide Incidents for decisions 7 and 8** (#288): the set has no site-wide Incident, so
`opspilot labelset draft-site-wide` asks the model that drafted the set (`SITE_WIDE_PROMPT.md`)
for twelve, one per slot of a topic where an outage for everyone reads naturally and how hard it
stops work, checked as the set's rows are. They go to `site_wide_d7_v1.jsonl`, apart from the set:
drafted as Incidents, they carry that type unlabelled, and only their impact and urgency are
labelled.

## 6. Labelling

- **Blind**: the labeller sees `subject`, `body`, `channel` only. `draft_intent`, `draft_security`
  and `topic` are hidden until labelling is done.
- **One sitting**, shuffled order, about a minute a row (80–90 minutes).
- **Binary on purpose**: `d2-v1` has no "can't tell". Pick the more likely type and mark
  `label_confidence: low`. The low-confidence rows are the ambiguous subset in the report.
- **Self-consistency**: a day later, relabel 10 random rows blind. A day means at least 20 hours
  after the first pass's last `labelled_time`; a row with only a date (the day its sitting began)
  counts from two hours after the end of that UTC day. The relabel refuses to start sooner. The agreement rate goes in the report; if it is
  under 9 of 10, that says as much about the answer space as about the engines.
- **Security review** (#225, added after labelling): decision 1's threshold is set so that every
  labelled security item reaches a person, so each `security: yes` is a row the stage stops on.
  Every row whose `security` label and `draft_security` split is reviewed once more against
  `d1-v1`, with `opspilot labelset review-security` (since replaced by `relabel-security`; its
  record is `security_review_v1.jsonl`). The reviewer sees the row and the label they
  gave it; the drafter's intent stays hidden. Each answer, before and after, goes to
  `security_review_v1.jsonl`, and the set changes only once every split row has been reviewed.
  The review is not blind, and the report says so.
- **Security relabel** (#225, `d1-v2`): when the answer space changed, every row's `security`
  column was labelled again against `d1-v2` (`opspilot labelset relabel-security`): blind to the
  label given before and to the drafter's intent, but by the labeller who had seen these rows
  twice. Each answer goes to `security_d1_v2.jsonl`, and the set changes only once every row has
  one. The d1-v1 relabel and review are not read against `d1-v2` labels.

- **Known fix** (#226, `d9-v1`): each row's candidate pages are its `kb_search` hits over the
  SSC-built KB (`opspilot kb ingest --profile ssc`), grouped by page in rank order, searched on
  the subject then the body, redacted and whitespace-collapsed exactly as the run's prefetch
  does, top 5 hits. They are written once to
  `candidates_d9_v1.jsonl` (`opspilot labelset candidates`), each page with its title, path and
  best hit as its excerpt, so labelling and every engine see the same candidates whatever the KB
  becomes. The labeller marks the pages that fix the row, or none (`opspilot labelset
  label-known-fix`), seeing the row and the candidates and no engine's answer. A fix the
  candidates do not include is recorded as none: decision 9 can only pick from what it is offered.
- **Impact and urgency** (#227, `d7-v1`, `d8-v1`): each row labelled `incident` is shown again,
  its subject, body and channel and no other label, and the labeller gives its impact and then
  its urgency in one pass (`opspilot labelset label-impact-urgency`), each a level's number.
- **Site-wide Incidents** (#288): `site_wide_d7_v1.jsonl` is labelled for impact and urgency with
  the same pass, `opspilot labelset label-impact-urgency --set` that file.
- **Team** (#228, `d6-v1`): each row labelled `incident` is shown the same way, and the labeller
  picks the team that would fix it (`opspilot labelset label-team`).
- **Already open** (#230, `d3-v1`): each item of `already_open_d3_v1.jsonl` shows its subject,
  body and channel and its five open Work items by number, with their subject and body and not
  their keys; the labeller picks the one that is the same problem, or none (`opspilot labelset
  label-already-open`). What an item was drafted from stays hidden.
- **Catalog item** (#231, `r1-v1`): the catalog is shown first, each item by number with its
  description; then each row labelled `service_request`, shown as the Incidents are, and the
  labeller picks its item, or `none` (`opspilot labelset label-catalog-item`).
- **Really a request** (#293, `r2-v1`): each row labelled `service_request` is shown the same way,
  and the labeller says whether it is a request, an incident or a change (`opspilot labelset
  label-really`).
- **Enough to act on** (#229, `d4-v1`): each row labelled `incident` is shown the same way, and
  the labeller says whether an engineer could start on it without asking first (`opspilot
  labelset label-enough`).

## 7. How the report uses it

- Accuracy and Brier score for each engine (Jev, the Playbook's model) on all 80, and separately on
  the `label_confidence: low` subset.
- The decision-2 threshold: the lowest probability at which the items routed without a person are
  at least 95% right (ADR-0040). Set on these 80; there is no held-out split at this size, and the
  report says so.
- Cost per call and p50/p95 latency, each engine run three times over the set.
- Published whichever engine wins.

`opspilot labelset report` produces it. Every call is appended to `runs_v1.jsonl` as it returns,
so a run cut short resumes and the report can be recomputed without calling anything
(`--no-call`). A failed call is counted as a failure and kept out of accuracy. The report never
writes `d2.yaml`: the threshold is set from it by a person.

**Decision 1** (#225): `opspilot labelset report --decision d1` asks Jev and the Playbook's model
`d1.yaml` as written, keeps its calls in a file named by the answer space's version
(`runs_d1_v1.jsonl`, `runs_d1_v2.jsonl`: both decisions' Playbook-model engines share a name), and reports, per engine, accuracy at 0.5 and the Brier score on P(yes), and the
decision-1 threshold: the highest P(yes) at which every labelled security item stops (ADR-0040),
with its recall, the share of all calls it stops, and its false alarms among the rows labelled
`no`. As for decision 2, a person sets `d1.yaml`'s threshold from it.

**Decisions 7 and 8** (#227): `opspilot labelset report --decision d7` (and `d8`) asks Jev and
the Playbook's model `d7-v1` (`d8-v1`) of every Incident three times, keeping the calls in
`runs_d7_v1.jsonl` (`runs_d8_v1.jsonl`), together with the site-wide Incidents of
`site_wide_d7_v1.jsonl` once that file exists (#288). A Score's levels are ordered, so beside exact accuracy
the report gives how often an answer is within one level of the label, what each engine answered
for each labelled level, and what always answering the most common label would score. Its Brier
score is on the answer: each answer's probability against whether it was right. The
threshold follows decision 2's rule: the lowest probability at which the levels decided without a
person are at least 95% right. A person sets each file's threshold from it.

**Decision 6** (#228): `opspilot labelset report --decision d6` reports the team the same way, on
the same Incidents, into `runs_d6_v1.jsonl`; a Choice's answers are not ordered, so it has no
within-one figure.

**Decision 3** (#230): `--decision d3` asks each item of `already_open_d3_v1.jsonl` over its own
five open Work items, each redacted and keyed by its row id, then `none`: the Choice the stage
builds from a source's open Work items. The calls go to `runs_d3_v1.jsonl`. The stage acts only on
a match, so the report gives the cut at which the matches named are at least 95% right, with how
many labelled matches are named rightly and how many items labelled `none` are named one.

**The request path's r1** (#231): `--decision r1` asks each service request which catalog item it is
for, over the catalog's items and `none`, into `runs_r1_v1.jsonl`, and reports it as the Incident
decisions are; with many answers, each labelled item gets right, `none` or another instead of a
column per item. `none` and an answer below the cut both go to a person, so only a named item
acts, and the report also gives that cut: the lowest probability at which the items named are
at least 95% right.

**The request path's r2** (#293): `--decision r2` asks every row whether, filed as a service
request, it really is one, into `runs_r2_v1.jsonl`: the 41 requests against their `really` label,
the 39 Incidents against `incident`, by their type. `request`, and an answer below the cut, leave
the request path as it is, so the report gives the cut on the other answers.

**Decision 4** (#229): `--decision d4` reports whether each Incident has enough to act on, the same
way, into `runs_d4_v1.jsonl`. The stage acts only on a `no` that clears its cut, so the report
also gives that cut: the lowest P(no) at which the Work items asked about are at least 95%
labelled `no`, with how many labelled `no` are asked and how many labelled `yes` are asked.

**Decision 9** (#226): `opspilot labelset report --decision d9` asks Jev and the Playbook's model
`d9-v1` once per candidate page of each row, shown the Work item and the page as the labeller saw
it (`candidates_d9_v1.jsonl`), and keeps the calls in `runs_d9_v1.jsonl`. Per row and run, the
candidate with the highest P(yes) is the fix the stage would send. The decision-9 threshold is the
lowest P(yes) at which the fixes sent are at least 95% right, the rule decision 2 follows; the
report also gives how many rows with a fix get a right page at it, and how many rows with none
are sent one. A person sets `d9.yaml`'s threshold from it. With `--whole-page --source <handbook>`
the engines are shown each candidate's whole page instead, read from the checkout the KB was
built from and redacted, and the calls are kept in `runs_d9_v1_whole_page.jsonl`.

## 8. Decided before drafting (2026-09-24)

1. **Drafter**: one batch of 10 is drafted by a GPT model and one by a Gemini model through
   OpenRouter; the one that keeps to the quota instructions drafts the rest (the cheaper if both
   do). The losing batch is discarded, not mixed in.
2. **Ambiguous rows**: 16 stands.
3. **Labeller**: `labelled_by: vicenteliu`.
