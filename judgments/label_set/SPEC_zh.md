# Label set zh v1: specification

The Chinese Work items that decisions 1 and 2 are measured on (#233). Source of the requirement:
ADR-0040, *What was left out on purpose*: the zh Playbooks are first-class, but a Chinese label
set is its own piece of work, and its numbers are not mixed into the English ones. This file says
how this set differs from the English one. Everything it does not change is as `SPEC.md` says.
The rows go in `label_set_zh_v1.jsonl` beside it.

**Why now.** The `en` and `zh` classification Playbooks both run `claude-haiku-5-5`, so the
Playbook model's engine has the same name either way, and Jev's name does not depend on language.
A deployment set to `pb_classify_work_item_zh` therefore runs at the cuts measured in English:
0.94 and 0.70 for decision 2, 0.10 and 0.30 for decision 1. None of these has been measured on
Chinese. This set measures them; until it has, that gap stands.

**Eighty rows is not a benchmark**, here as in English. Every report that uses the set says it is
small, synthetic, Chinese, and labelled by one person.

## 1. What gets labelled

Decisions 1 and 2 only. These two run on every Work item, and the stage refuses to start without
a cut for either (#274, #301).

| Column | Decision | Answer space |
|---|---|---|
| `work_item_type` | 2 · Incident or service request? | `d2-v1` |
| `security` | 1 · Security issue? | `d1-v2` |
| `security_sign` | which of d1-v2's signs, for each `security: yes` | `d1-signs-v1` (§6) |

The answer spaces are the English files as written (`d1.yaml`, `d2.yaml`,
`signs_d1_v2.yaml`): the labeller reads their definitions, and the engines are asked them. The
other decisions are not labelled on this set. If they are wanted later, they are added as their
own columns and their own passes, as they were in English.

## 2. Row schema

As `SPEC.md` §2, limited to the columns above: `id` (`LZ1-001` …), `subject`, `body`, `channel`,
`topic`, `draft_intent`, `draft_security`, `work_item_type`, `security`, `security_sign`,
`security_sign_note`, `label_confidence`, `label_note`, `answer_space`, `drafted_by`, `labelled_by`,
`labelled_at` and `labelled_time`. `topic` names the SSC topic in English, verbatim from the slot.

## 3. What goes in (80 rows)

The same mix as `SPEC.md` §3, so the two reports compare:

- by intent: 36 `incident`, 28 `service_request`, 16 `ambiguous`;
- at least 12 rows with `draft_security: yes`, across all three intents;
- the same topics, at most 8 rows a topic;
- the same forms, with two changes.

**Forms.**

- `non_native` becomes **`mixed`** (6 rows): Chinese with English words switched in beyond product
  names and pasted errors, the way many Chinese-speaking staff write to IT (e.g. "VPN 连上就
  disconnect", "帮我 reset 一下 MFA"). Product names, menu labels and pasted error text in English
  are fine in every form.
- **Lengths count characters, not words**, with whitespace left out:
  - a `one_liner` is a subject only, or a body under 20 characters;
  - a `long_rambling` body is 180 to 300 characters;
  - no body is over 300 characters.

  `SPEC.md` counts words by spaces, which Chinese does not have; these limits are roughly the
  English ones at about 1.7 characters a word.

**Security is drafted against d1-v2's signs.** The English drafting prompt described security in
d1-v1's broader words. This set's prompt lists d1-v2's signs, so a row drafted `security: yes`
shows one of them. That is what the labeller is asked about, and what the engines are asked.

## 4. What must not go in

As `SPEC.md` §4, with these points for Chinese:

- People are obviously fictional, named by role or a common placeholder (财务部的同事, 小李).
- Domains are `example.com` and `example.org`.
- No mobile, landline, QQ or ID numbers, and no WeChat IDs. The redactor catches any run of eight
  or more digits; QQ numbers and WeChat IDs it may not catch, so the prompt forbids them outright.
- The set must pass through the redactor unchanged.
- The text is Chinese, apart from the English that §3 allows: `mixed`, and product names, menu
  labels and pasted error text in any form.

## 5. Drafting

- **Prompt.** `DRAFT_PROMPT_zh.md`, committed. It has the same structure and rules as
  `DRAFT_PROMPT.md`, with §3's changes, written in English for the drafting model, and it asks for
  Chinese text.
- **Model.** A trial in Chinese, as `SPEC.md` §8.1 did in English. One batch of 10 goes to each of
  the English trial's candidates, `openai/gpt-6.1-sol` and `google/gemini-3.8-flash`. The one that
  keeps to its slots drafts the rest, or the cheaper one if both do. A model that writes English
  well may not keep to the slots in Chinese, which is why the trial is run again.
- **Batches, checks, redraft, shuffle.**
  - As `SPEC.md` §5: 8 calls of 10 rows.
  - Each row is checked against its slot, with §3's character counts.
  - Near-duplicates on a topic are redrafted.
  - The rows are then shuffled and given ids.
- **Cost cap.** $1, on a ledger of its own (`~/.opspilot/label_set_zh_v1/`).

## 6. Labelling

As `SPEC.md` §6:

- Blind: the labeller sees `subject`, `body` and `channel` only.
- One sitting, in shuffled order.
- `label_confidence` on each row.
- A blind relabel of 10 random rows at least 20 hours later.

One change, from #281. **A `security: yes` is asked which sign it shows**, at once, from
`signs_d1_v2.yaml`'s answers.

- The English set's yes labels followed the topic of 27 rows that showed no sign. The fault
  surfaced only after both engines disagreed, and took a review to settle. Asking for the sign
  while the row is on screen settles it as it is labelled.
- `no_sign` records the row as `security: no`. Every other answer keeps it `yes`, including
  `in_doubt` (d1-v2: when in doubt, yes).
- `another_sign` and `in_doubt` take a note in `security_sign_note`. That note says which sign the
  list does not name, or what raises the doubt.

The relabel asks the same questions, the sign included. Agreement is reported on the type and on
security, as in English, and the report also says how many relabelled yes rows named the same
sign.

## 7. How the report uses it

`opspilot labelset report --decision d2` and `--decision d1` run on this set, apart from the
English one.

- **The engines.** Jev, and the Playbook's model through `pb_classify_work_item_zh`, which is what
  a Chinese deployment runs: Classification for decision 2, the question as written for decision 1.
- **The files.**
  - The calls go in `runs_zh_v1.jsonl` and `runs_d1_zh_v1.jsonl`.
  - The reports go in `report_zh_v1.md` and `report_d1_zh_v1.md`.
  - Each report says the set is Chinese.

Each report gives what the English one gives:

- per engine, accuracy and the Brier score;
- the cut measured on this set: decision 2's lowest probability at which the routed answers are
  95% right, and decision 1's highest P(yes) at which every security item stops.

It also says what the committed English cut does on this set:

- for decision 2, how many answers it routes and how many of those are right;
- for decision 1, its recall and how many it stops.

**What the numbers decide.** The report writes nothing to `d1.yaml` or `d2.yaml`. With both
reports in hand, the user decides how Chinese is measured into the stage, and ADR-0040 is revised
to say so. The criterion proposed: for each engine,

- if the English cut keeps decision 2's routed answers at least 95% right on this set, and keeps
  decision 1's recall at 100%, one cut per engine serves both languages;
- otherwise, thresholds are keyed by language as well as engine, and a deployment's language
  comes from its classification Playbook.

## 8. Decided before drafting (2026-10-17)

1. **Scope**: decisions 1 and 2 only.
2. **Thresholds**: measured first. How Chinese takes effect in the stage is decided with the
   numbers (§7), not before.
3. **Size and mix**: 80 rows in the English mix, with `mixed` in place of `non_native`.
4. **Drafter**: a Chinese trial between the English trial's two candidates. It was run on
   2026-10-17:
   - `openai/gpt-6.1-sol` kept 10 of 10 rows to their slots;
   - `google/gemini-3.8-flash` kept 9, missing one long body at 176 characters.

   So `gpt-6.1-sol` drafted the set: 80 rows, $0.16 in all.
5. **Signs**: a `security: yes` is asked its sign while it is labelled (§6).
6. **Labeller**: `labelled_by: vicenteliu`.
