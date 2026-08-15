# Firsthand verification outranks vendor documentation, through a recorded Resolution

Status: accepted (2026-08-14)

`source_authority` has four tiers — `official`, `vendor`, `internal`,
`unverified` — and is descriptive only: it is shown on every Hit and never
reorders retrieval. It has not yet had to settle a real disagreement, because
nothing has been ingested that contradicts anything else.

That changes as soon as a KB carries both a vendor's documentation and a team's
own verified findings, which is the normal case for anyone running someone
else's software on their own hardware.

## Decision

- **Firsthand verified findings are ingested as `official`, not `internal`.**
  The `official` tier means "your own signed-off SOPs"; a failure mode someone
  on the team reproduced and wrote up is exactly that. `internal` remains the
  default for team-written material that has not been verified against a
  running system.
- **On a `direct_contradiction` between an `official` chunk and a `vendor`
  chunk, the expected Resolution is `b_wins` toward the verified finding** —
  vendor documentation describes intended behaviour, and a reproduced finding
  describes actual behaviour on the hardware in question. Troubleshooting needs
  the second.
- **It is settled by a recorded Resolution, never silently.** The Conflict is
  detected, a human resolves it, and the reason is stored. No automatic
  demotion of the vendor chunk, and no ranking change: the mechanism stays
  descriptive, and the judgement stays an event.

## Trade-off accepted

Trusting the local finding over the vendor is wrong sometimes — the reproduction
may have been mistaken, or the vendor may have fixed it since. That is the cost
of the requirement to write a reason: six months on, the reason is the only way
to tell a real finding from a misdiagnosis someone enshrined, and a silent
override leaves nothing to re-examine.

## Consequences

- Ingesting vendor documentation stops being a bulk-import convenience and
  becomes a source of work: every contradiction it raises needs settling.
  That is the intended cost — the contradictions were already there, unlogged.
- Vendor documentation decays and its contradictions will therefore recur as
  products are renamed and behaviour changes. A resolved Conflict is a
  statement about two specific chunks at a point in time, not a standing
  preference between tiers.
- Issue #150 — whether `source_authority` should influence ranking — is
  unaffected. This decision governs how a Conflict is settled, not how results
  are ordered.
