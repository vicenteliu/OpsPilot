# Storage posture: fix the concurrency defect now, keep Postgres as a separate decision

Status: accepted (2026-08-18)

The question that started this was whether to replace LanceDB with ChromaDB
because OpsPilot is becoming an internal online service. Reading the code moved
the problem somewhere else entirely.

`docker-compose.prod.yml` already runs `serve --workers 2` behind nginx, so the
online posture is not a future state — it shipped. And `POST /api/kb/ingest`
runs the whole ingestion pipeline inside an API worker, so writes happen in the
serving process, not only in the CLI.

More importantly, `SqliteStore` holds **one** `sqlite3.Connection` opened with
`check_same_thread=False`, kept as **one** shared instance on `app.state.sqlite`,
and every blocking route call reaches it through
`loop.run_in_executor(None, ...)` — the default multi-threaded pool. Write paths
are `execute(...)` then `commit()` with no lock. `commit()` is connection-scoped,
not thread-scoped, so concurrent writes share one implicit transaction and
interleave. `_PRAGMAS` has no `busy_timeout`.

This is a present-day correctness defect, it is **independent of `--workers`**,
and no vector store is involved in it.

## Decision

### 1. Fix the defect now, decoupled from any migration

Serialise the write paths with a lock and add `busy_timeout` — issue #166.
Writes on a KB workbench should be serial; this is not OLTP.

A defect that can corrupt data today must not be scheduled behind an
architectural decision that has not been made yet. The fix is tens of lines and
it is what turns Postgres back into a decision that can be taken calmly.

### 2. Reject the LanceDB → ChromaDB swap

The stated motivation — a store that is networked and safe for concurrent
writers — is right, and the vector store is the wrong place to apply it. The
defect is in SQLite, which would still hold document metadata, chunks,
conflicts, corrections, settings, inventory, sessions, and auth after the swap;
hybrid search would still span two stores, since the keyword half is SQLite
FTS5 and RRF is fused in the application layer.

Per ADR-0029, any vendor claim about a candidate store's concurrency behaviour
should be settled by running it on our own hardware and ingesting the finding as
`official`, not by reading its documentation.

`LanceStore` has a six-method surface (`open_or_create`, `upsert_vectors`,
`delete_by_vector_ids`, `count`, `ann_search`, `build_ann_index`). It is the
cheapest thing in the system to replace, and therefore the least urgent.

### 3. Postgres + pgvector is the intended destination, scoped separately

If the storage does move, it moves in one step to Postgres with pgvector — not
to a third store alongside the two that exist. Postgres puts vectors
(`pgvector`), keyword search (`tsvector`/GIN), and metadata in one database, so
RRF becomes one query, and it resolves concurrency for sessions, auth,
inventory, and settings at the same time.

It is **not** scheduled here, because it has four bills that are easy to
overlook while looking at the KB alone:

1. **ADR-0008's zero-infrastructure install.** `uv tool install opspilot` works
   on a clean macOS shell because storage is files under `~/.opspilot`. A
   required Postgres ends that, and ADR-0008 would need superseding or a
   dual-backend story.
2. **The all-in-one Docker image**, which `ROADMAP.md` describes as "one
   `docker run` is a complete workbench."
3. **FTS5 → `tsvector`/GIN.** Different tokenisation and ranking, so RRF weights
   need re-tuning against an existing gate: the golden test's ≥ 0.85 weighted
   score. This is a measurable regression risk, not a port.
4. **Everything else in SQLite moves too** — sessions, auth, inventory
   (assets / events / procurements), settings, intake state. This is a
   whole-application storage migration wearing a KB migration's clothes.

**Migration trigger.** Revisit when one of these is true: the write lock from
issue #166 becomes a measured bottleneck under real load; a second machine is
genuinely required; or an external constraint mandates a central database.
Growth in user count alone is not a trigger — the bottleneck on this workload is
LLM inference, which runs outside the process.

### 4. Backup is not export

**Sessions and Consultations get no export interface**, for two different
reasons.

A **Session** is an append-only ledger whose value is that it happened on this
machine and was not edited. The moment it becomes a file you can export, that
guarantee is gone: what lands is a copy anyone can edit, and re-importing it is
indistinguishable from re-importing the original.

A **Consultation** is not that — it is deleted after 90 days unless pinned
(ADR-0032), so durability is not what is being protected. It is withheld because
it collects pasted logs, configs, and stack traces with none of the redaction a
Work item passes through, and an export interface is the cheapest possible way
for that to leave the building.

Both travel only by whole-directory cold backup, at the filesystem layer.

**KB, Skills, Wiki, and Memory do get one**, because they are knowledge and
knowledge is supposed to move. The bundle is a tar of per-domain native formats
plus a manifest — not a uniform JSON envelope. Skills and Wiki pages are already
files (`agent_skills/<id>/SKILL.md`, `wiki/pages/<kind>/<slug>.md`), and
converting them into JSON would destroy the property ADR-0027 depends on: a Skill
is admitted through a pull request, and a pull request has to be readable as a
diff.

**KB exports its source documents, never chunks or vectors.** Chunks are an
artefact of the splitter, and vectors are bound to an embedding model —
`lance_store.normalize_embedding_model` already enforces that consistency, so
vectors carried to a machine running a different model are garbage. The receiver
re-ingests. The manifest records the export time, the OpsPilot version, per-domain
counts, and the KB's embedding `model_ref` — the last so the receiver can tell
whether to recompute, and the answer is always yes.

**An imported Skill lands in a staging area, not in `agent_skills/`.** ADR-0027
is specific that admission *is* a pull request, and a tar unpacked onto disk
produces no commit and no diff — so "lands as a draft" would be a phrase, not a
gate. Import writes somewhere outside the git-reviewed tree; moving an entry from
there into `agent_skills/` is the commit, and that commit is the admission
(ADR-0030). Import is not a way around it.

## Trade-off accepted

Keeping SQLite means keeping a single-writer store and a serialising lock, and
one day that lock will be the thing to remove. Accepted: the lock makes the
system correct now, and the trigger conditions above say when to look again.

Recording a decision that has not been made — "we will probably migrate, here is
what it costs, here is when to revisit" — risks reading as indecision. The
alternative is worse. In six months nobody will remember `check_same_thread=False`,
and nobody will remember that the bill included ADR-0008.

## Consequences

- Issue #166 is the immediate work and is independent of everything else here.
- ADR-0008 stands. Any Postgres proposal must address it explicitly rather than
  discovering it during implementation.
- ChromaDB is rejected, not deferred, for this problem. A future vector-store
  change should be argued from a measured need in the vector layer specifically.
- The export interface is a new surface for KB / Skills / Wiki / Memory. The
  deliberate absence of one for Sessions and Consultations is a decision, not a
  gap, and should not be "fixed" later without reopening this ADR.
