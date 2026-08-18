# Memory, revised after reading the spec it was written without

Status: accepted (2026-08-18) — revises ADR-0031

ADR-0031 defined **Memory** as OpsPilot's second owned domain four days ago. It
was written without anyone reading `docs/specs/memory/SPEC.md`, which had
described a memory design since Stage 1: three tiers (short-term / mid-term /
long-term), a typed `memory_records` table with FTS5 and triggers, confidence-
weighted retrieval, hard expiry, and a harvest path. The table, its indexes, its
schema file and a CRUD pair existed. Nothing had ever written to it.

Reading it changed the design. This ADR records what changed and why, rather
than editing ADR-0031 in place — that a decision was made in ignorance of an
existing spec, and what a later reading did to it, is the kind of thing an ADR
exists to keep.

## What the old spec got right, and is kept

- **The three tiers are real**, and survive under different names. Short-term
  became two separate things (below); mid-term is **Memory**; long-term is the
  **KB**. What was rejected is the mechanism, not the layering.
- **Its anti-patterns list**, which said what does *not* belong in memory. That
  is the operational form of ADR-0031's "no table" rule — a definition tells you
  where the boundary is, a checklist tells you what crossing it looks like — and
  it is what someone actually consults while writing an entry. Rewritten for
  this domain:
  - Not device facts — **Inventory** has them, with fields.
  - Not procedures — a **Skill** has them, with a stopping condition.
  - Not document content — the **KB** has it, and it is retrievable.
  - Not one incident's resolution — that was a **Session**, and it has a trace.
- **`pin_to_memory`**, its first harvest rule. ADR-0031 had the assistant propose
  an entry at the end of a Consultation; pinning lets a human mark the sentence
  *at the moment it is said*, which fits ADR-0030's rule that the admitter must
  hold what the judgement needs. The person marking has the context; the person
  reviewing a summary afterwards has already moved on.

## What is rejected, and why

Each was argued on its own; none is rejected merely for being old.

- **Typed entries** (`user` / `feedback` / `project` / `reference`). The taxonomy
  is a *personal assistant's* memory model — user preferences, corrections of the
  AI — adopted for cross-tool migration with such systems. Memory here is
  team-global environment constraints, with no "user preference" and no record of
  what you last corrected. A shared shape with unshared semantics is worse than
  no interoperability: the data migrates and is then misread. Portability belongs
  to the export format (ADR-0033), not the storage schema.
- **`confidence` affecting retrieval weight.** A self-reported quality score that
  reorders results, against two standing decisions: ADR-0030 says admission is an
  act and not a score, and `source_authority` is descriptive and never reorders.
- **Hard expiry** (`valid_until`, read-only once expired). ADR-0031 keeps review
  dates as a *label*: expiry changes what an entry carries when it surfaces,
  never whether it surfaces. Environment constraints rot silently — finance moves
  the batch and nobody writes anything anywhere — and dropping a still-correct
  constraint at an unknown moment is the worse failure.
- **Content-addressed ids** (`mem_<sha8>` of the text). Right for an **Artifact**,
  which *is* its content. A Memory entry is a record that someone decided
  something: two people writing the same sentence six months apart are two facts
  about the world, and collapsing them destroys the ageing history that
  supersede-by-append exists to produce. Ids are random, `mem_` + 8 hex.

## What ADR-0031 left open, decided here

- **Reason is mandatory.** Six months on it is the only way to tell a real
  finding from a misdiagnosis someone enshrined, which is exactly the judgement a
  review date asks for. This means admission is never one click — the friction is
  the point, and it falls on the person writing rather than on someone
  rubber-stamping a queue later.
- **Direct write is a first-class admission path**, not a fallback. A person who
  writes the sentence *and* the reason is both author and admitter; the judgement
  rests on their own knowledge. That is the strongest form of ADR-0030's rule,
  not a weaker one.
- **Entries are not redacted.** Memory is authored inside the trust boundary by
  an authenticated member of the team, exactly like an **Asset** — and Inventory
  stores real serial numbers and hostnames without redaction. Redaction exists
  for content arriving from outside. The cost is real and named in ADR-0034:
  anchored constraints carry hostnames and site names into prompts that leave for
  a hosted API. If that is unacceptable it is unacceptable for Inventory and the
  KB too, and it is a bigger decision than Memory should carry.
- **Scope is pick-or-create**, not free text. "HQ", "hq" and "head office" become
  three scopes, and anchor-filtered retrieval then silently misses — the failure
  mode that anchors were introduced to prevent. Offering what already exists lets
  the vocabulary converge without inventing a taxonomy up front.
- **An entry links back to its source** — the Consultation and the message that
  prompted it. The reason says what the writer thought; the link preserves what
  they were looking at. A Consultation referenced this way is pinned against the
  90-day sweep, the same rule ADR-0032 already applies on escalation.
- **A Memory entry is its own audit record.** Consultations get no trace: the
  entry carries actor, time, reason and source, which is what ADR-0030 asks be
  recorded. Adding a second ledger would duplicate it and undo the lightness
  ADR-0032 chose deliberately.

## Also separated here: "short-term memory" was two things

The old spec's short-term is a **context budget** — token ceiling, overflow
policy, pinned events, keep-last-N-turns. ADR-0032's **Working set** is *which
problem you are chasing*, spanning several Consultations. Neither replaces the
other, and calling both "short-term memory" is how one word came to cover three
concepts.

The context budget is not memory at all — it is how a conversation stays inside a
window — so it stays out of this domain. It is deferred, with a stated trigger:
**when a stored Consultation's history can exceed the model's window.** Today
chat is stateless and the client carries that weight. The old policy file
survives the deletion, relocated to
`docs/specs/session/templates/context-budget.template.yaml`.

## Trade-off accepted

Superseding a four-day-old ADR reads as churn, and a reader may reasonably ask
why the first one was written without reading the repository's own spec. That is
the honest record: it was, the omission was found by looking for something else,
and the design is better for it. Hiding that by editing ADR-0031 in place would
cost the one lesson the episode actually carries.

## Consequences

- `docs/specs/memory/SPEC.md` loses §§1–4 and §§13–14 and becomes a KB spec.
  `memory_records`, its FTS table and triggers, its JSON schema and its templates
  are deleted, along with the `write_memory` / `get_memory` pair that nothing
  called. A spec for something never built and now decided against is not
  history; the next reader implements it.
- The Memory domain lives in `opspilot/memory/` — the name freed by #167 — beside
  `opspilot/inventory/`, the first owned domain, and shares the KB connection the
  same way.
- Adding a fifth store to that connection surfaced an incomplete fix: #166 put a
  lock on `SqliteStore`, but `InventoryStore`, `AuthStore` and `SettingsStore`
  drive the *same* connection unguarded, and `commit()` is connection-scoped. The
  lock now belongs to the connection (`opspilot/dblock.py`), which is what it
  always protected.
