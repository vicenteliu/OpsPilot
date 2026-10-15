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

The other decisions' columns (already open, enough to act on) exist in the schema and stay empty
until their slice.

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
- **Team** (#228, `d6-v1`): each row labelled `incident` is shown the same way, and the labeller
  picks the team that would fix it (`opspilot labelset label-team`).

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
`runs_d7_v1.jsonl` (`runs_d8_v1.jsonl`). A Score's levels are ordered, so beside exact accuracy
the report gives how often an answer is within one level of the label, what each engine answered
for each labelled level, and what always answering the most common label would score. Its Brier
score is on the answer: each answer's probability against whether it was right. The
threshold follows decision 2's rule: the lowest probability at which the levels decided without a
person are at least 95% right. A person sets each file's threshold from it.

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
