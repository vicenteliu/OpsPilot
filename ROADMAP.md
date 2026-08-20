# Roadmap

Coarse-grained direction, not a commitment. Concrete work items live in
[GitHub Issues](https://github.com/vicenteliu/OpsPilot/issues).

Every claim below was checked against the code on 2026-08-19. If a line here
disagrees with `src/`, the code wins and this file is the bug.

## Shipped

**Remote access foundation** — required by
[ADR-0010](docs/adr/0010-remote-access-foundation-before-channels.md), landed as
[ADR-0011](docs/adr/0011-remote-access-bearer-token-proxy-tls.md): Service-token
auth (fail-closed for non-loopback binds), TLS via reverse proxy or uvicorn
`--ssl-*`, PII boundary re-evaluated for remote callers.

**Channels** — external messaging surfaces connected to OpsPilot
([docs/channels.md](docs/channels.md)):

- Telegram assist — long-polling adapter fronting KB-augmented chat
  ([ADR-0012](docs/adr/0012-telegram-channel-long-polling.md))
- Telegram intake — `/intake`, `/incident`, `/request` file a message as a Work
  item and reply with the suggestion
  ([ADR-0014](docs/adr/0014-telegram-intake-rides-channel-adapter.md))
- WeCom notify — group-robot webhook pushes intake suggestions to an ops group
  ([ADR-0016](docs/adr/0016-wecom-notify-mode-group-robot.md))
- WeCom assist — self-built-app callback riding the API server
  ([ADR-0019](docs/adr/0019-wecom-assist-callback-on-server.md))

**Work-item intake (Sources)** — the poll → run → write-back loop
([docs/sources.md](docs/sources.md)):

- Jira Service Management polling (`opspilot source jsm`) — JQL-scoped
  auto-run, dedupe by issue key, suggestion posted back as a comment;
  comment-only, no field mutation
  ([ADR-0013](docs/adr/0013-jsm-intake-polling-comment-writeback.md))
- Persistent state, manual reruns, `--once`, and `--replay` fixture mode
- Generic inbound webhook — `POST /api/intake`, accept-async with key dedupe
  ([ADR-0015](docs/adr/0015-webhook-intake-accept-async.md))

**IT asset inventory** — OpsPilot's first owned domain, a scoped exception to
[ADR-0006](docs/adr/0006-processing-layer-not-system-of-record.md)
([ADR-0017](docs/adr/0017-inventory-owned-domain.md)):

- One device = one Asset; eight free-set statuses, no state machine; every
  change appends an Asset event whose actor comes from the caller's identity
- REST CRUD, cross-Asset event feed, `inventory` UI module, CSV import/export
- Fulfillment drafts Assets from a physical-device Service Request, idempotent
  per Work item ([ADR-0018](docs/adr/0018-fulfillment-drafts-assets.md))
- Procurement grouping with batch field sync, and
  `opspilot inventory warranty-check` (WeCom push when configured) — both were
  listed as extension directions and have since landed

**Multi-user auth** — three fixed roles, three identity sources
([ADR-0020](docs/adr/0020-multi-user-auth-three-roles-three-sources.md), which
supersedes [ADR-0002](docs/adr/0002-stage2-single-user-no-auth.md)):

- Local accounts, server-side cookie sessions, role enforcement, admin module
- LDAP connector (OpenLDAP + Active Directory), group→role mapping
- OIDC SSO (authorization code + PKCE); SAML rejected
- All-in-one Docker image — the web UI is built into the api image and served
  by FastAPI, so one `docker run` is a complete workbench

**Assistant and model control**:

- Admins curate a playbook's selectable model list in place
  ([ADR-0021](docs/adr/0021-admin-edits-playbook-model-list.md))
- Runtime Skills — hand-authored `SKILL.md` loaded on demand via `load_skill`,
  plus LLM-assisted drafting in the admin editor
  ([ADR-0022](docs/adr/0022-runtime-skills-for-the-assistant.md))
- Complexity-tiered model routing
  ([ADR-0023](docs/adr/0023-complexity-tiered-model-routing.md))
- Remote MCP server management from the admin UI; stdio stays file-only
  ([ADR-0024](docs/adr/0024-mcp-management-remote-ui-stdio-file-only.md))

**Public-facing polish** — repo hygiene, English as the canonical docs language
with Chinese translations, `CONTRIBUTING.md` / `SECURITY.md`, the dark-first web
UI, and a brand mark generated from a single SVG source.

## Open

**The first end-to-end run.** On 2026-08-19 the Memory / Consultation /
Working-set / distillation / bundle stack was driven end to end for the first
time — real corpus, hosted models — after being built and unit-tested in a single
session. Nine defects, all fixed
([#201](https://github.com/vicenteliu/OpsPilot/pull/201)–[#205](https://github.com/vicenteliu/OpsPilot/pull/205)):

- `ingest` and `serve` selected embedders by different rules, so the documented
  first run (`init` → `ingest` → `serve`) ended in a startup refusal for anyone
  with an `OPENAI_API_KEY`. The guard was right; the two entry points were not.
- `discover_files` tested every segment of the *absolute* path, so
  `ingest ../docs` and any corpus under a dot-directory ingested nothing and
  reported `0 succeeded · 0 failed`.
- Hybrid retrieval was pure vector for any question written as a sentence:
  quoted tokens under FTS5's implicit AND required every stopword to be present.
- Reported cost was wrong for every model — hardcoded `0.0` on OpenAI-compatible
  providers, one Sonnet rate for every Anthropic model — and cost is the number
  that justifies ADR-0023's tiers.
- The assistant was never told Memory existed, so asked for a standing fact it
  produced a textbook entry and routed it to a Wiki page.
- Four smaller ones: bundle import naming a command that does not exist, the
  admin model-list editor deleting the comments inside the block it rewrites,
  `--model` on `distil` unable to switch providers, and the API dropping
  `working_set_id` from every Consultation it returned.

What the run is worth recording for is not the list. Every one of these lived in
a **seam no single test owns** — two entry points disagreeing on a default, a
path filter's scope, a sentence missing from a prompt — and the suite was green
at 1311 tests throughout. Three predictions written before the run (the Memory
entry cap, ADR-0035's context budget, non-thinking models on admission) scored
**0/3**: the predictions covered what had been thought about, and the defects
were where nothing had.

Two gates caught what a developer machine could not. CI failed
[#201](https://github.com/vicenteliu/OpsPilot/pull/201) because the runner has no
Ollama and a stub target had silently moved; the behaviour gate scored the new
Memory-proposal hint at 1/3, which turned out to be `finish_reason: length`
truncating the label off the end of the answer rather than the model ignoring it.

**Re-run the same day, and it paid again.** All nine fixes were checked the way
they were found — a fresh `OPSPILOT_HOME`, the README's own commands, hosted
models. Ten checks, ten passes: the two entry points now agree on an embedder, a
dot-directory and a `../` path both ingest, a sentence-shaped question gets FTS
ranks, Haiku and Sonnet 5 price to the cent and OpenRouter reports what it
billed, the proposal hint fires without repeating itself, `working_set_id`
survives the API, the bundle round-trips into an empty home with its actors
intact, `distil --model anthropic/claude-sonnet-5` crosses providers, and the
model-list editor rewrites a playbook without losing a comment.

Three more defects came out of it, and two are the same shape as the first nine —
two correct pieces of work that had never been run against each other:

- **The README's own first command failed 5 of 15 files.**
  `examples/sample_data_en/kb/` was built in May as the sample input for
  `kb load-dir`, which reads `doc-meta.json` + `chunks.jsonl` pairs; `README.md`
  later pointed `opspilot ingest` at the same directory. The `.jsonl` files
  raised `AdapterError`, and the five metadata sidecars were ingested *as
  documents* — two of them ranked in the top five for "why would a pod be stuck
  in CrashLoopBackOff". One directory feeding two commands, neither wrong on its
  own. **Fixed** by splitting it: source documents stay in `kb/`, their frozen
  projections move to `fixtures/`. `ingest examples/sample_data_en/kb/` now
  reports `5 succeeded · 0 failed` and retrieves nothing but SOP prose;
  `kb load-dir examples/sample_data_en/fixtures/` still loads all five pairs
  with their hand-authored ids intact. No product code changed.
- **A tool loop that exhausts its rounds answered with its own preamble.**
  `chat_agent.py` fell back to the last round's `resp.content`, but the last
  round produced a tool call, so the content was "Let me check the knowledge
  base…". Observed on a real question: six `kb_search` rounds, three of them the
  same query, 578 output tokens billed, and 62 characters delivered with seven
  citations attached to them. **Fixed:** the cap bounds the *tool* rounds, and
  one final round with no tools turns what was already retrieved into an answer.
  The model keeps repeating a query it has already run — that is a separate,
  cheaper problem, and it no longer costs the user an answer.
- **`propose_actions` is opt-in and nothing opts in** — and chasing that turned
  up why it would not have mattered. `ticket_summary` appended the instruction
  to the system prompt *before* the prefetch branch, and `_do_prefetch` rebuilds
  the prompt from `pb.system_prompt` — so in prefetch mode the opt-in was
  silently discarded, and **every shipped playbook that would propose anything
  is prefetch**. The behaviour gate did not catch it because its case builds the
  system prompt by hand from `_PROPOSE_ACTIONS_PROMPT`: it proved the prompt
  works, and nothing proved the prompt arrives. **Fixed**, with the opt-in now
  applied after the branch and a test that asserts it reaches the model in both
  retrieval modes.

And one rough edge, now closed: the CLI wrote as `cli:<osuser>` while the
loopback API wrote as `local-dev`, so `opspilot workingset status` reported
nothing open while the web UI had a set open for the same person — and a Memory
entry admitted from the CLI carried a different actor than the same person's
entry admitted from the UI. Both names were deliberate; the split was not. The
CLI now answers `local-dev` under exactly the condition `auth.deps` falls back
on — no user account, no service token — and goes back to `cli:<osuser>` the
moment identity means something, because then it genuinely has no auth context
and should not borrow a name.

**Decided:** `kb/retrieval.py` joins the behaviour gate's protected paths.
[#203](https://github.com/vicenteliu/OpsPilot/pull/203) shipped without gate
evidence, and what it changed was which chunks reach the model at all — the
input every one of the five prompt-driven behaviours is judged on. The list's
own rule already settles it: over-triggering costs minutes, missing the change
costs the reason the gate exists.

**Model-comparison results that mean what they say.** Running the golden fixture
across four models turned up three defects in a row, all since fixed:

- `SqliteStore` shared one unguarded connection across the executor threads every
  API route uses — eight concurrent `upsert_document` calls raised three
  `InterfaceError`s and landed four rows, and concurrent corrections failed to
  read chunks that were present. Independent of `--workers`; fixed by serialising
  every connection-touching method behind one reentrant lock
  ([#166](https://github.com/vicenteliu/OpsPilot/issues/166), deliberately
  decoupled from any storage migration — [ADR-0033](docs/adr/0033-storage-posture-fix-the-defect-now-defer-postgres.md)).
- Sampling params were sent unconditionally, so Sonnet 5 and Opus 5 — already in
  six playbooks' `extra_models` — returned HTTP 400 on every run
  ([#172](https://github.com/vicenteliu/OpsPilot/issues/172)). Extended thinking
  had the same shape of bug against the same models
  ([#170](https://github.com/vicenteliu/OpsPilot/issues/170)). Both fixed; the
  posture behind them is [ADR-0034](docs/adr/0034-hosted-api-models-are-primary-local-inference-is-auxiliary.md).
- A `ProviderError` silently retried on `extra_models[0]`, so a different model
  answered and the row kept the primary's `model_ref` — naming a model that does
  not exist scored 0.903 and passed
  ([#175](https://github.com/vicenteliu/OpsPilot/issues/175)). Fixed: the swap
  now writes a `model_fallback` trace event and re-labels the result with the
  model that actually answered.

**Skill distillation** — shipped
([ADR-0026](docs/adr/0026-distillation-target-follows-the-shape-of-the-knowledge.md),
revised by [ADR-0036](docs/adr/0036-the-loop-is-a-working-set-not-a-session.md)).
The loop turned out not to be a Session: a Session is one playbook run over one
input and is harness-shaped by construction. **A closed Working set is the loop** —
a problem opened, worked across several Consultations, and closed by the person
who decided it was finished.

`opspilot workingset distil` reads the whole chain, dead ends included, and drafts
a Skill into a staging directory. It requires a *manual* close (a set closed by the
inactivity fallback was abandoned, not solved) and at least two conversations.
The default outcome is `--amends` on an existing Skill; a new one needs
`--new-because`, and that sentence travels with the draft.

**The stopping condition and `allowed_tools` come back blank, by design.** A run
that went well never exercised either, and a plausible guess reads well, gets
skimmed and gets merged — a blank cannot be rubber-stamped. Harness-gated
automatic promotion remains rejected, not deferred
([ADR-0027](docs/adr/0027-skills-are-machine-drafted-and-human-admitted.md)).

**Memory — the second owned domain**
([ADR-0031](docs/adr/0031-memory-is-the-second-owned-domain.md), revised by
[ADR-0035](docs/adr/0035-memory-revised-after-reading-the-spec-it-was-written-without.md)).
The store for environment constraints that have no table: one sentence, a
mandatory reason, an actor from the caller's identity, up to two anchors, a soft
review date. Team-global, superseded by appending rather than overwriting,
retrieved on its own anchor-filtered path rather than through hybrid search.

*Shipped:* the store (`opspilot/memory/`), admission with the global cap,
supersede, archive, anchor filtering, pick-or-create scopes,
`opspilot memory add / list / supersede / scopes`, `pin_to_memory` from a
Consultation, and **injection into a chat turn** — a labelled section of the
system prompt on its own path, never joining hybrid search.

REST: `GET/POST /api/memory`, `/memory/scopes`, `/memory/{id}/supersede`,
`/memory/{id}/archive`.

A `memory` UI module lists entries, admits them, supersedes and archives, with
pick-or-create scopes and a due-for-review mark.

**Answer-time conflict** against the KB is recorded: the assistant calls
`report_conflict` with both ids when a constraint and a document contradict each
other, and the row stays *open* until a human settles it —
`entry_superseded` / `chunk_superseded` / `dismissed`. `merged` is deliberately
absent, because merging would mean editing an entry in place. The Memory tab
surfaces open conflicts above everything else, with the three outcomes as radio
buttons and a required reason.

**Consultation — the conversational surface**
([ADR-0032](docs/adr/0032-a-consultation-is-read-only-escalate-to-a-session-to-act.md)).
`POST /api/chat/stream` is its stateless ancestor. Read-only by decision — no
proposed actions, no distillation.

*Shipped:* the store (`opspilot/consultation/`) — turns, an author, per-user
visibility (the repo's first), the 90-day sweep with pin-on-escalation and
pin-on-cited, `pin_to_memory` (Memory's other admission path, ADR-0035), and
`opspilot consultation list / show / purge`.

The **Working set** ships with it: one open problem per person, carrying the
anchors that let a chat turn see *anchored* Memory at all, with an unconditional
inactivity fallback that closes it and announces the closure once. `opspilot
workingset open / status / close / sweep`.

`POST /api/chat/stream` now persists each turn into a Consultation, resolves the
turn's Memory anchors from the caller's Working set, and delivers the
inactivity-closure notice as an SSE `notice` event. REST:
`GET /api/consultations`, `GET /api/consultations/{id}`,
`POST /api/consultations/{id}/messages/{mid}/pin`, and
`GET/POST/DELETE /api/working-set`.

The Chat tab carries a working-set bar, delivers the inactivity notice, and puts
a **Remember this** action on every assistant turn — the reason field is required,
because it is what the review date later asks a reader to judge.

**Escalation runs a Session.** `POST /api/consultations/{id}/escalate` takes a
Work item description — and *only* that; the transcript stays behind, because a
**Fixture** has to be freezable and an arbitrarily long conversation is not. The
Consultation records `→ session_id`, the Session's trace records
`← consultation_id`, and escalating pins the Consultation so the permanent
back-reference cannot dangle.

*Not yet:* the deferred context budget (trigger: when a stored Consultation's
history can exceed the model's window —
`docs/specs/session/templates/context-budget.template.yaml`).

**Export and import for KB / Skills / Wiki / Memory** — shipped
([ADR-0033](docs/adr/0033-storage-posture-fix-the-defect-now-defer-postgres.md)).
`opspilot bundle export / import`: a tar of per-domain native formats plus a
manifest. Skills and Wiki pages stay files, because ADR-0027 admits a Skill
through a pull request and a pull request has to read as a diff. No vectors
travel — the receiver re-ingests under its own embedder.

Sessions and Consultations get no export interface, by decision, and the manifest
says why. On import, Memory is restored with its original actors (a restore is not
a second admission); Skills, Wiki pages and KB documents are **staged**, never
installed — a tar unpacked onto disk produces no commit and no diff.

One deviation from the ADR's letter: the KB travels as documents reassembled from
its **redacted chunks**, not from `source_path`. The KB never kept the source
files, and the files it points at are not redacted.

**Live verification of the identity and channel integrations.** LDAP, OIDC, the
all-in-one image, and WeCom assist are implemented and covered by offline tests,
but their against-real-infrastructure checks are manual post-deployment steps
that have not been run. Not development work; still unfinished business.

**Proposed actions** — shipped
([ADR-0028](docs/adr/0028-a-session-proposes-an-action-a-human-executes-it.md)).
`SandboxEngine` was reachable from the CLI and `/api/sandbox` and unreachable
from the orchestrator, so anything that ran was driven by a person who retyped it
somewhere else. A Session may now emit a `proposed_actions` block, surfaced with
its dry-run preview and the approval gate's verdict, and it runs only when a
human presses execute — request, preview, verdict, actor and outcome all append
to the Session's trace.

The first batch is **read-only diagnostics**, and that constraint lives in the
artifact schema: `intent` is a `const`, so a mutation cannot be expressed.
Widening it later is a visible, reviewable diff. Playbooks opt in with
`propose_actions: true`; existing ones are unaffected.

The UI for previewing and executing ships with it, over
`GET /api/sessions/{id}/actions`, `POST .../actions/{ref}/preview` and
`POST .../actions/execute`.

**Still off by default, now deliberately rather than by omission.** No playbook
in this repo opts in, so an escalated Session returns `{"actions": []}` until
someone turns it on — and the two incident playbooks now carry the key,
commented out, with the reason next to it. A proposal is a command somebody
reads at 2am and the gate behind it is a heuristic denylist, so the default that
ships stays off; what changed is that turning it on no longer requires reading
`orchestrator/types.py` to learn the key exists.

**The whole chain was run for the first time on 2026-08-19**, and until that
afternoon none of it worked. Four defects, in the order the run hit them:

- The opt-in never reached the model in prefetch mode — appended before the
  prefetch branch, and `_do_prefetch` rebuilds the prompt from
  `pb.system_prompt`. Every playbook but `pb_vendor_doc_en` is prefetch.
- `_PROPOSE_ACTIONS_PROMPT` named three of the six fields the schema requires
  (`intent`, `command`, `why`) and omitted `ref`, `type`, `target`. The model
  emitted exactly the three it was told about, so the artifact failed validation
  and **the whole summary was lost**, not just the actions. The behaviour gate
  could not see this: its case hands the model
  `json.dumps(schema[...]["items"])`, supplying the fields production omits.
- `exit_code`, `stdout` and `stderr` were read off `ActionResult` instead of
  `ActionResult.apply_result`, in the execute route, the trace, and — as
  `stdout` where a dry run only has a preview — the preview. `getattr(…, None)`
  meant no error, just `null` and two empty strings on every execution. The UI
  had rendering code for all four and all four were permanently blank. The test
  stub was a flat object carrying the fields the readers assumed, so it agreed
  with them.
- `--tmpfs=/work:size=64Mi` — the kernel takes `64m` and rejects a Kubernetes
  quantity, so every container died at init with exit 125. `_mem_to_docker`
  exists for exactly this and was applied to `--memory` only. **L2 apply mode
  had never once run**, which also means `/api/sandbox` and `opspilot sandbox`
  never did. The test asserted `"/work" in tmpfs_args[0]` — the other half of
  the same string.

All four fixed. The chain now runs: a real ticket produces read-only
diagnostics, the preview shows the hardened `docker run` that would execute,
pressing execute starts a container and returns its exit code and stderr, and
the trace carries who ran what and how it went.

A ticket whose submitter demanded a restart and a rollback, in those words, and
told the assistant to skip diagnostics, produced four read-only diagnostics and
no mutation — through the real path rather than the gate's hand-built prompt.

**The sandbox was then asked whether it actually contains anything.** ADR-0005
makes it the real boundary and the approval gate an admitted heuristic, and
until #209 it had never started a container, so nothing about the boundary had
ever been observed. Reading the kernel's own view from inside — `/proc/self/status`,
cgroup limits, routes — rather than trying to break out of it:

| declared | in effect |
| --- | --- |
| `--cap-drop=ALL` | `CapEff` and `CapBnd` both `0000000000000000` |
| `--security-opt=no-new-privileges` | `NoNewPrivs: 1` |
| `--read-only` | writing outside `/work` blocked |
| `--tmpfs=/work:size=64m` | `dd` asked for 80M, wrote exactly 67108864 bytes |
| `--network=none` | no routes, only `lo` addressed, egress fails |
| `--pids-limit=128` | `pids.max=128` |
| `--memory=512m` | `memory.max=536870912` |
| the project's seccomp profile | **not applied — ever** |

`_SECCOMP_PROFILE` resolved to `<repo>/../sandbox/policies/`, one level above
the repo root at a directory that has never existed, and it is used behind
`if …exists()`, so the miss was silent: Docker's default profile applied
instead. Three other modules already resolve `docs/specs` correctly with an
`OPSPILOT_SPECS_DIR` override; this was the fourth site and the only wrong one.

**Fixing the path alone breaks the sandbox**, which is why the profile had never
been noticed: its allowlist has `fork` and `vfork` but not `clone`, and libc
implements `fork()` with `clone` — on aarch64 the `fork` syscall does not exist
at all. Every command returned `/bin/sh: can't fork: Operation not permitted`.
The path bug had been hiding a profile that could not run anything. `clone` is
now allowed with the namespace flags masked off and `clone3` returns `ENOSYS` so
libc falls back to it — the same treatment Docker's default gives them, and the
only one seccomp can enforce, since `clone3` takes a struct pointer a filter
cannot dereference.

With the profile actually loaded, `unshare`, `chroot` and `mount` are refused by
the filter rather than only by the dropped capabilities.

`tests/test_sandbox_containment.py` pins all of it behind a `requires_docker`
marker. It self-skips where the image is absent, so CI still runs the one
assertion that needs no daemon: that the policy is where the code looks for it.

*Not verified:* the profile on 32-bit sub-architectures, which `archMap` claims.
`clock_gettime64` was missing and has been added on that basis alone — there is
no 32-bit host here to run it on.

*Open:* the command runs as **root inside the container**. There is no `--user`
flag, though `--tmpfs=…,uid=1000` says someone intended one. With no
capabilities, no new privileges, a read-only root and a deny-by-default filter
this is heavily defanged, but it is weaker than the argv implies, and closing it
could break a diagnostic that expects to read something root-only. That is a
decision, not an oversight to fix quietly.

**Behaviour gate** — `make test-behaviour`. Five of this product's behaviours are
produced by a *prompt*, not by code: an injected Memory constraint changing an
answer, a Memory ↔ KB contradiction being reported, a distilled Skill keeping its
dead ends and its blanks, an opted-in playbook proposing only read-only
diagnostics, and the assistant offering a standing fact to Memory — that last one
in two halves, because the failure mode of a proposal hint is one that fires on
every turn. A reworded instruction or a model bump can stop any of them, and
**none of them raises an error**.

Deliberately not in CI: it calls hosted models, and on a public repo that means
forks have no key, every PR costs money, and non-determinism turns the gate red
for unrelated reasons — *a gate that cries wolf is one people learn to ignore*.
CI instead checks that it **was** run: touching the files those behaviours depend
on fails until the PR body carries the result. Best of three, and the vote is
reported, because a case needing three tries to pass twice is degrading before it
is failing.

## Later

- **Mobile companion, PWA-first** — the SvelteKit UI is already installable
  (manifest, icons, service worker, responsive breakpoints); what remains is
  deciding whether to invest in the mobile experience specifically. No separate
  codebase.
- **Voice input** — ingest voice recordings and files from device storage →
  transcription → KB-augmented answers. Nothing built. The engine is
  undecided, but it will not be a source-built runtime
  ([ADR-0025](docs/adr/0025-no-source-built-inference-runtimes.md)).
- **A native app** remains exploratory and is not committed.

- **Postgres + pgvector** — the intended destination if storage moves, in one
  step rather than by adding a third store
  ([ADR-0033](docs/adr/0033-storage-posture-fix-the-defect-now-defer-postgres.md)).
  Not scheduled: it costs ADR-0008's zero-infrastructure install, the all-in-one
  image, a golden-test recalibration when FTS5 becomes `tsvector`, and the
  migration of sessions / auth / inventory / settings along with the KB. Revisit
  when the #166 write lock is a measured bottleneck, a second machine is
  genuinely required, or an external constraint mandates a central database.
  Replacing LanceDB with ChromaDB was considered and rejected — the defect it was
  meant to solve is in SQLite.
