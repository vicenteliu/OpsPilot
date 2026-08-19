# Source authority describes a citation; it does not rank one

Status: accepted (2026-08-19)

`source_authority` has four ordered tiers — `official`, `vendor`, `internal`,
`unverified` — and `_sort_key` consulted them as a tie-break behind the RRF
score. Issue #150 enumerated what that tie-break actually does: under the default
0.6/0.4 weights, **6 rank pairs out of 369,370 compare exactly equal**, and none
of them involves an ANN rank better than 18. Authority cannot influence the
ordering of any well-matched result.

The question that leaves is not "how do we make the tie fire more often". It is
whether ranking should carry trust at all.

## Decision

**It should not. `source_authority` is descriptive, and the ordering is
relevance.**

The argument that this was a trust mechanism was true when #150 was filed and is
not any more. The case it named — *"which of two contradictory answers reaches a
model and then an operator"* — now has a mechanism of its own, and a better one.
A **Conflict** is detected, a human settles it with a recorded **Resolution**,
the losing **Chunk** is marked superseded, and superseded chunks are excluded
from retrieval outright. **Ranking never sees the loser.**

ADR-0029 already decided this for the hardest case it could find — a team's
verified finding against a vendor's documentation — and decided it the same way:

> No automatic demotion of the vendor chunk, and no ranking change: the mechanism
> stays descriptive, and the judgement stays an event.

and

> A resolved Conflict is a statement about two specific chunks at a point in
> time, **not a standing preference between tiers**.

A per-tier weight in the score *is* a standing preference between tiers. It makes
the same judgement on every query, about every chunk, with no reason recorded and
nothing to re-examine — which is the property ADR-0029 was written to protect.

**So the tie-break is removed rather than tuned.** A comparison that fires on six
rank pairs is not a feature; it is a line of code that reads like a trust signal
and is not one, and leaving it in place with an explanatory comment keeps the
misreading and adds a footnote. Determinism comes from `valid_from` and then the
chunk id, which is what the sort actually needs.

**Descriptive means visible.** A signal nobody sees is not descriptive, it is
absent — so `source_authority` travels with a chat citation, not only with a KB
search row. The reader most likely to be misled is the one reading an answer, who
until now could not tell whether it rested on a signed-off SOP or a scraped forum
post.

## When to revisit

Not on a calendar — nothing here is driven by time. Revisit when **the same
direction is chosen repeatedly between the same two authority tiers**: if people
keep settling `official` against `vendor` the same way, a standing preference is
emerging in the data, and encoding it would then rest on evidence rather than on
what the field's name suggests.

That signal is free to watch. `kb_conflicts` already records the resolution and
both chunk ids, and the tier of each is a lookup away.

## Trade-off accepted

A poorly-written official SOP still loses to a well-matching forum post, and a
reader has to notice the tier and judge. That is the cost, and it is the same
cost ADR-0029 accepted: the judgement stays with a person, and when they make it
they leave a reason behind.

The cheaper-looking alternative — a tolerance on the score comparison — was
rejected outright. A tolerance is a magic number that silently decides how often
authority beats relevance, and RRF scores are not comparable across queries, so
the same tolerance would mean different things for different questions.

## Consequences

- `_AUTHORITY_RANK` and its use in `_sort_key` go. The four tests #149 made
  genuinely exercise the tie-break are **inverted** rather than deleted: they now
  assert that a more authoritative but worse-matching chunk is *not* promoted. A
  decision nobody can test is one that gets undone by accident, which is how this
  survived unnoticed in the first place.
- `Hit.source_authority` was already carried and already shown on KB search rows.
  Chat citations gain it.
- `CONTEXT.md`'s **Source authority** entry stops saying the question is open.
- The spec was silent on this — `SPEC.md` documents RRF and never mentions
  authority — which is why the code could drift from an intent nobody had
  written down. This ADR is that record.
