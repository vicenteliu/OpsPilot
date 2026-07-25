# Fulfillment drafts Assets automatically — guarded, idempotent, deletable

Status: accepted (2026-07-25)

The first bridge between the pipeline and the inventory (extension
direction recorded in ADR-0017): when a Service Request asks for physical
devices, the request-fulfillment run drafts the Asset(s) automatically —
status `requested`, `work_item_ref` linking back to the Work item, device
fields extracted by the model. LLM output writing into the owned ledger
is the sensitive part; the design is guardrails-first:

- **An explicit schema block, not inference.** `request_fulfillment_v1`
  gains an *optional* `asset_draft` object ({category, brand_model,
  specs, quantity}). The playbook prompt instructs the model to emit it
  only when the request is clearly for physical hardware and to omit it
  otherwise — absence is the safe default, and schema validation bounds
  the shape (quantity 1–20). Old artifacts without the field still
  validate: additive, no v2 fork.
- **Auto-create, because intake has no human to click.** The JSM,
  Telegram, and webhook paths run unattended; a "create asset" button
  would mean drafts never materialize exactly where they are most
  valuable. A wrong draft is cheap to undo: status stays `requested`,
  the `drafted` event names the session (`actor: session:<id>`), and
  DELETE exists precisely for data-entry mistakes.
- **Idempotent by work_item_ref.** If any Asset already references the
  Work item, drafting is skipped — `--rerun` and webhook redeliveries
  never duplicate hardware.
- **Drafting never fails the run.** It happens after the artifact is
  validated and archived, in the API layer (all intake paths converge on
  `POST /api/run`); an inventory error is logged and the run response is
  unaffected. CLI-direct orchestrator runs skip drafting — they bypass
  the API layer by design.

**Rejected:** suggest-only with a UI button (dies on unattended intake
paths); drafting inside the orchestrator (layering — the orchestrator
must not know the inventory exists); keyword heuristics on the request
text instead of a model-emitted block (exactly the false-positive
machinery the explicit schema field avoids); unbounded quantity (a
hallucinated "500 laptops" must die at validation, not in the ledger).
