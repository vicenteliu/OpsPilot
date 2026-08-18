# Memory is the second owned domain: the home for knowledge that has no table

Status: accepted (2026-08-18)

OpsPilot has four knowledge carriers and none of them holds an environment
constraint. A **Chunk** is a slice of an ingested document. A **Wiki page** is
declarative knowledge someone wrote here. A **Skill** is a procedure with a
stopping condition. A **Session trace** is a record of what happened.

"Do not restart the ESXi cluster on Tuesday evening, finance runs its batch
then" is none of these. It is not a document, not a procedure, and not a record
of an event. Today it lives in someone's head, and the assistant does not have it.

## Decision

**Memory** is the store for knowledge that has no table, and it is the second
domain OpsPilot owns as system of record — a second scoped exception to
ADR-0006, after Inventory (ADR-0017).

### What belongs in it

The test is shape, not subject: a Memory entry's natural form is **one sentence,
a reason, who said it, and when**. Anything whose natural form is a set of
fields belongs in a table.

This draws the line against Inventory, which already stores `brand_model`,
`serial_number`, `location`, `assignee`, `vendor`, and `category`. "This gateway
is a Fortigate 60F" is an **Asset**, not a Memory. "The firewall rules at this
site are managed by the vendor and we have no access" is a Memory.

**The reverse rule matters more than the definition: when entries in Memory
accumulate to the point where you want to query them by field, that is the
signal to build a table — not the signal to give Memory fields.** Without this
rule, Memory becomes a junk drawer, then grows a schema, and then OpsPilot has a
second Inventory that nobody designed.

### Shape

- **Two optional anchors, and only two**: a reference to an Asset, and a
  free-text scope tag (site, environment, system). Both may be empty; empty means
  the constraint is global. An anchor is the *address a sentence applies at*, not
  a field about a thing, so it does not violate the rule above. The cap is
  deliberate: a third anchor is evidence that what you want is a table.
- **Team-global. No per-user layer.** An environment constraint is a property of
  the environment, not of whoever discovered it. Splitting it per user means one
  operator's assistant knows about Tuesday and another's does not, with nothing
  anywhere explaining the difference.
- **The actor is derived from the caller's identity, never from the request** —
  the same rule as an Asset event, a Resolution, and a Correction.
- **One instance is one team.** Multiple teams get multiple instances. Adding a
  tenant dimension to Memory would mean adding one to Inventory, KB, Skills, and
  Wiki as well, since all of those are instance-global today. That is an
  architecture change, not something to derive from this decision.

### Writing

A Memory entry is **admitted**, per ADR-0030: the assistant proposes it at the
end of a Consultation and a human confirms it there and then.

**A Session may not propose a Memory entry.** An intake-driven Session runs
unattended, so its proposals could only land in a queue, and a queue produces
batch approval — which is the automatic extraction this rule exists to prevent,
wearing a click as a disguise.

Automatic extraction from transcripts is rejected outright, and the reason is
specific: mid-investigation someone says "I suspect it's the driver version." An
extractor cannot tell a hypothesis from a conclusion, and records it as a fact
about the environment. Months later nobody remembers it was a guess, and **a
wrong Memory entry never raises an error — it just makes the assistant quietly
avoid something, or quietly recommend the wrong thing.**

### Ageing

Every entry carries a review date. **Expiry changes the label an entry carries,
never its content or its availability**: past the date it still applies, marked
"not reviewed in N months." This follows two precedents in the repo —
`source_authority` is descriptive and never reorders retrieval, and a Wiki page's
`stale` state is not deletion.

Hard expiry is rejected: environment constraints rot silently — finance moves the
batch to Thursday and nobody writes anything anywhere — but automatic expiry
drops correct constraints at the worst possible moment.

### Correcting

A superseded entry is **appended, not overwritten**, and the old one is marked
superseded.

The KB's **Correction** overwrites a Chunk in place because a Chunk is a
*projection* of an external document; editing it repairs a projection error.
**A Memory entry is not a projection — it is the original.** An entry that is
overturned ("finance moved the batch to Thursday") does not mean it was recorded
wrong; it means the world changed. Those two must stay distinguishable, because
one says a past judgement was faulty and the other says this class of constraint
has a rhythm. Overwriting collapses them into one.

The superseded entry keeps its review date, so the history shows **how long a
constraint stayed true** — the only available data for judging how often
constraints of that kind change.

### Reading

Memory is retrieved on **its own path**: filtered by anchor, injected directly.
It does not join hybrid search and does not enter the RRF ranking.

Three reasons, the first decisive. **Conflict between Memory and KB is detected
at answer time** (below), which requires the assistant to distinguish "this came
from Memory" from "this came from the KB" — a shared RRF ranking destroys that
distinction. Second, the volumes differ by orders of magnitude (tens of entries
against tens of thousands of chunks): in one ranking Memory is either drowned or
needs a hand-tuned weight, and needing a weight is itself the proof they do not
belong in one ranking. Third, Memory's retrieval condition is not semantic
relevance but "does this constraint apply at this address" — that is a filter,
not a ranking.

Un-anchored (global) entries are injected on every turn, so they carry a **hard
cap**. On overflow the entry must gain an anchor or be archived. The cap does not
exist to save tokens; it exists to force the recognition that there should not be
dozens of global constraints.

### Conflicting with the KB

Detected **at answer time**, not at write time. What is reused is the *record
types* — Conflict and Resolution — not the detector. The existing path is cosine
similarity between chunks at ingest; this is a second and genuinely new detection
path, running while an answer is composed.

Resolving one also needs its own outcomes, because the existing four are written
for two Chunks. Against a Memory entry the available Resolutions are: **the entry
is superseded** (appended, per the rule above), **the Chunk is superseded**, or
**dismissed**. `merged` is unavailable — merging would mean editing the entry in
place, which this ADR forbids.

Write-time detection has the wrong timing. When an entry is saved the human is
present and has just confirmed it (ADR-0030); a prompt at that moment gets
dismissed. The moment worth interrupting is six months later, a different
person, investigating something unrelated, when the assistant holds both that
entry and a document that says the opposite — **because that is the moment
nobody knows both things exist.** Write-time detection would also require
embedding Memory into the vector store, which turns it back into a Chunk and
undoes the boundary this ADR draws.

## Trade-off accepted

Memory fills one entry at a time, by hand, at the end of conversations —
so it will be sparse, and the assistant will not know things somebody could have
told it in bulk. Accepted, per ADR-0030.

The narrow definition also means some knowledge has no home for a while: it is
not a document, not a procedure, and not one sentence either. That knowledge
waits until it earns a table. That is the intended behaviour of the reverse rule,
and it is the mechanism keeping Memory from becoming a junk drawer.

## Consequences

- `CONTEXT.md` gains **Memory** and **Working set**, and its **Correction** entry
  must say that the append-not-overwrite rule applies to Memory while the
  overwrite rule stays for Chunks.
- Conflict detection gains a second *path*, running at answer time rather than at
  ingest. The existing chunk-to-chunk path (cosine similarity in LanceDB) is
  unchanged, and the two share only the Conflict and Resolution records.
- `src/opspilot/kb/` is the KB implementation and now collides with a domain
  term. Renaming it to `kb/` is issue #167.
- Two owned domains means ADR-0006 is now a rule with two exceptions rather than
  one. A third should be argued against this pattern, not against ADR-0006 alone.
