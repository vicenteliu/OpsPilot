# The handbook is the source; the KB is a build artifact

Status: accepted (2026-08-21)

`sysadmin-self-cultivation` (SSC) is a public handbook — seven platforms, the
full stack, cross-cutting notes, 153 markdown files written to be *read*. Its
material is the same material OpsPilot's KB needs: runbooks, platform
mechanics, the operating model behind a triage decision. The question is which
copy is true when the two disagree.

## Decision

**SSC is the single source. The KB is a build artifact, and nothing edits it by
hand.**

Ingestion runs one way — handbook to chunks — and never back.

## Why not maintain both

Two hand-maintained copies of the same knowledge drift. Not eventually; from the
first edit that lands on one side and not the other. And drift here is
expensive in a specific way: the KB is what grounds a citation, so a stale chunk
does not merely go out of date, it produces a **confidently cited wrong answer**
with an audit trail that looks clean.

## Why not the other direction

Because it does not invert. A handbook chapter is prose with an argument in it —
it establishes a mental model, then names the platform-specific spellings of it.
A chunk is a retrieval unit. **Chunking prose is mechanical; reconstituting an
argument from chunks is not.** Whichever side is generated has to be the cheaper
projection, and that is the KB.

There is a second reason, particular to this pairing. SSC is entirely public.
Making it the only inbound path means "private material must never reach the
KB" is not a rule anyone has to remember — there is no channel for it to arrive
through. That property is worth more than the flexibility we give up.

## What follows

- **The build script lives here, not in SSC.** A handbook that knows the name of
  its consumer is coupled to it; the next consumer would have to be added to the
  source repo. SSC exposes markdown and nothing else. The profile, the path
  handling, and the ingest invocation are OpsPilot's problem:

  ```
  opspilot kb ingest --profile ssc --source <path to SSC checkout>
  ```

  The checkout path is a parameter or an environment variable, never a constant.

- **Manual runs plus a dry run in CI. No scheduled job.** SSC changes on the
  order of a commit or two a week. A cron job over that would spend nearly all
  of its runs doing nothing, which is the failure mode where a *silently* broken
  job is indistinguishable from a correctly idle one — the operator sees the
  same empty log either way.

- **Conflict detection reports back to SSC.** `conflict.py` already runs after
  each document is ingested. Two handbook modules that contradict each other are
  **a bug in the handbook**, not a KB condition to be resolved downstream — the
  Conflict/Resolution machinery from ADR-0029 and ADR-0037 exists for genuinely
  competing sources, not for a single source disagreeing with itself. Write the
  report to a file for a human to read. Do not open issues automatically; at
  this volume that is noise, and noisy alerts get filtered, including the one
  that mattered.

## Cost we are accepting

Anything the KB wants that does not belong in a handbook — a chunk with no
readable home — has to either earn a place in SSC's prose or not exist. That is
a real constraint, and it is the point: it keeps the KB's contents traceable to
something a person has read and stands behind.
