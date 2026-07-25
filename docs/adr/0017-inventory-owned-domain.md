# Inventory: OpsPilot's first owned domain — a scoped exception to ADR-0006

Status: accepted (2026-07-25)

OpsPilot gains an IT asset inventory (procurement-to-retirement tracking:
request → PR → order → shipping → device → holder), and OpsPilot itself is
the **system of record** for it. This is a deliberate, scoped exception to
ADR-0006's processing-layer stance.

- **The exception is scoped to Assets.** ADR-0006 says the *Work item*
  lifecycle belongs to the external ITSM — that boundary is untouched.
  Inventory is a different domain, and in the small IT teams OpsPilot
  targets it typically has no system at all: the authoritative data lives
  in a spreadsheet. Mirroring an external inventory (the JSM-style
  posture) is impossible when there is nothing to mirror. Owning it is
  the honest design; CSV import/export is the migration path in and out,
  so authority can be handed to a real CMDB later.
- **One device, one Asset; history is an event log.** A batch purchase is
  N Assets sharing procurement fields (PR/order/tracking duplicated, as a
  spreadsheet would) — correct-but-heavier procurement normalization is a
  future refactor, not v1. Every change appends a timestamped **Asset
  event** with the actor; the row is a projection, the log is the truth —
  the same append-only pattern as session traces.
- **Statuses are a convention, not a state machine.** Eight values
  (requested / ordered / shipped / received / in_stock / deployed /
  in_repair / retired), any of them directly settable. Real inventories
  are full of corrections, back-filling, and existing stock entering
  mid-flow; enforced transitions would push people back to Excel. There
  is no "approved" status — a filled `pr_number` is the approval evidence.
- **v1 surface: API + web UI module + CSV.** REST CRUD plus event query,
  an `inventory` UI module behind the existing `ui.modules` toggle, and
  CSV import/export (`opspilot inventory import/export`) — import is the
  adoption path for existing spreadsheets. No AI involvement in v1; a
  request-fulfillment playbook drafting an Asset from a Service Request
  is a recorded extension direction, not scope.

**Rejected:** mirroring an external inventory system (nothing to mirror
in the target deployments); a normalized Procurement entity in v1 (a
second table and association UI for no v1 gain); enforced status
transitions (fights how inventory work actually happens); sequential
human-readable ids as primary keys (the asset tag field carries the
human name; the id stays an opaque `ast_<ULID>` — the house convention
for mutable entities).
