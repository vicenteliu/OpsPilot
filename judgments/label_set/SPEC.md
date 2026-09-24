# Label set v1: specification

The labelled Work items that the first Judgments slice (#224) is measured on. Source of the
requirement: ADR-0040, *The label set* and *Order of work*, step 1. This file says what the set
contains and how it gets made; the rows go in `label_set_v1.jsonl` beside it.

**Eighty rows is not a benchmark.** The set exists to give one decision a fair first comparison
and to set that decision's threshold. It is small, synthetic, English, and labelled by one person.
Every report that uses it says so.

## 1. What gets labelled

Two columns now, the rest later. Each is labelled against a versioned answer space.

| Column | Decision | Answer space | Version | Used by |
|---|---|---|---|---|
| `work_item_type` | 2 · Incident or request? | `incident` · `service_request` | `d2-v1` | #224 (this slice) |
| `security` | 1 · Security issue? | `yes` · `no` | `d1-v1` | #225 |

**`d2-v1`**, the definitions the Playbook's classifier already uses
(`playbooks/pb_classify_work_item_en/prompt.md`):
- `incident`: something is broken or degraded. It worked, or should work, and doesn't.
- `service_request`: an ask for something standard: access, an account, software, hardware, a
  change to a mailbox or group. Nothing is broken.

**`d1-v1`**: `yes` when the item could involve compromise or exposure: a suspicious link or
attachment, an unexpected sign-in or MFA prompt, a lost or stolen device, malware behaviour,
credentials shared or requested, data sent to the wrong place. `no` otherwise. When in doubt,
`yes`: the threshold for decision 1 is set so that every labelled security item reaches a person,
and false alarms are the price (ADR-0040).

The other decisions' columns (already open, enough to act on, network or system, impact, urgency,
seen before) exist in the schema and stay empty until their slice.

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
| `security` | **person** | `d1-v1` |
| `label_confidence` | **person** | `high` · `low`. Low = "I picked, but it could go the other way" |
| `label_note` | person, optional | one line, only when the reason isn't obvious |
| `answer_space` | script | `{"d2": "d2-v1", "d1": "d1-v1"}` at labelling time |
| `drafted_by` | script | exact model id via OpenRouter + date |
| `labelled_by` · `labelled_at` | script | the labeller's handle, date |

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
- **Self-consistency**: a day later, relabel 10 random rows blind. The agreement rate goes in the
  report; if it is under 9 of 10, that says as much about the answer space as about the engines.

## 7. How the report uses it

- Accuracy and Brier score for each engine (Jev, the Playbook's model) on all 80, and separately on
  the `label_confidence: low` subset.
- The decision-2 threshold: the lowest probability at which the items routed without a person are
  at least 95% right (ADR-0040). Set on these 80; there is no held-out split at this size, and the
  report says so.
- Cost per call and p50/p95 latency, each engine run three times over the set.
- Published whichever engine wins.

## 8. Decided before drafting (2026-09-24)

1. **Drafter**: one batch of 10 is drafted by a GPT model and one by a Gemini model through
   OpenRouter; the one that keeps to the quota instructions drafts the rest (the cheaper if both
   do). The losing batch is discarded, not mixed in.
2. **Ambiguous rows**: 16 stands.
3. **Labeller**: `labelled_by: vicenteliu`.
