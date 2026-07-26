# Admin edits the playbook model list in place

Status: accepted (2026-07-25)

Admins can curate which models the UI offers by editing the active
playbook's model list from the admin module — remove models the team no
longer wants and upgrade a model's name/version (e.g. to a newer
snapshot) — without hand-editing YAML or restarting the server. This
amends ADR-0020 (admin module) and touches the model-pinning discipline
in the README ("playbooks pin model versions; a regression harness gates
every upgrade").

## Decision

- **The edit writes `playbook.yaml` directly**, not a separate override
  layer. The playbook spec stays the single source of truth for models —
  there is no second place to reconcile, and the change is visible in
  `git diff` like any other spec edit. The alternative (a DB override
  layer merged over the playbook at read time) was rejected: it splits
  the model definition across two stores and hides deployment state
  outside version control.
- **Only the `model` and `extra_models` value blocks are rewritten;
  every comment and all other content is spliced back untouched**
  (`opspilot.playbook_models`). These files are hand-authored and
  comment-rich; a naïve dump-and-write would erase that documentation on
  every save. ruamel renders the two replacement blocks (correct quoting
  and indentation); the rest of the file is preserved byte-for-byte.
- **The change reloads live.** After writing, the route reloads the
  playbook and rebuilds the startup-cached primary provider and
  `active_model_ref`, so a run selecting the (possibly renamed) primary
  uses the new model rather than the one built at boot. A team-default
  model that no longer points at an offered model is cleared.
- **Scope is the active playbook only** (the one whose model list feeds
  `/api/models` and the Run-page selector). Other playbooks keep their
  own pinned models, editable via their own `playbook.yaml`.
- **`kind` is restricted to the protocol kinds the provider factory can
  build** (`anthropic` / `openai` / `ollama`), and `provider_id` to the
  known providers — so the UI cannot save a model no run could
  construct.

## Trade-off accepted

Editing from the UI **bypasses the regression harness** that normally
gates a model upgrade. That gate is a deliberate safeguard (see README);
skipping it means the admin owns validating that a new or upgraded model
actually behaves. The admin UI states this inline. We accept it because
the operator convenience of curating the dropdown — especially removing
retired models and bumping to a new snapshot — outweighs forcing a spec
PR + harness run for what is often a one-line name change, and because
the harness remains available (and recommended) for real upgrades.

## Consequences

- A UI save produces a real `playbook.yaml` diff; teams tracking specs in
  git will see (and can review/revert) model-list changes.
- The reload is per-process. With multiple uvicorn workers, only the
  worker that served the request reloads immediately; others pick up the
  change on their next restart. The all-in-one image runs a single
  worker, so this is not a concern for the default deployment.
