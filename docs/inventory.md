# Inventory

An **Asset** is one physical IT device OpsPilot tracks, from procurement to
retirement. This is the one domain where **OpsPilot is the system of record** —
a deliberate, scoped exception to the processing-layer stance
([ADR-0017](adr/0017-inventory-owned-domain.md), which carves it out of
[ADR-0006](adr/0006-processing-layer-not-system-of-record.md)).

The reason is the target deployment: small IT teams usually have no CMDB at
all, and the authoritative list lives in a spreadsheet. There is nothing to
mirror, so owning the data is the honest design. CSV import and export are the
migration path in *and* out, so authority can be handed to a real CMDB later
without a rewrite.

## The model

**One device, one Asset.** A batch purchase of five laptops is five Assets that
share procurement fields, exactly as a spreadsheet would duplicate them. If you
want the batch to behave as a unit, group it into a [Procurement](#procurements).

Fields, in three groups:

| Group | Fields |
| --- | --- |
| Identity | `asset_tag`, `category`, `brand_model`, `serial_number`, `specs`, `notes` |
| Procurement | `work_item_ref`, `pr_number`, `order_number`, `tracking_number`, `vendor`, `cost` |
| Lifecycle | `status`, `handler`, `assignee`, `location`, `warranty_until` |

The id is an opaque `ast_<ULID>`. The human-readable name is `asset_tag` —
sequential ids were rejected precisely so the two roles stay separate.

`serial_number` is unique **when set**; a duplicate is rejected with 409. Empty
serials never collide, so devices can be entered before their serials are known.

`pr_number` is a **Purchase Requisition** number, not a pull request. Elsewhere
in this repo "PR" means the latter; inside Inventory it never does.

`handler` and `assignee` are different people: the handler is the IT staffer
processing the device, the assignee is whoever ends up using it. Both are free
text in v1 — they are not linked to the user directory.

### Statuses are a convention, not a state machine

```
requested → ordered → shipped → received → in_stock → deployed
                                              ↕
                                          in_repair → retired
```

Eight values, and **any of them is directly settable from any other**. Real
inventories are full of corrections, back-filling, and existing stock entering
mid-flow; enforced transitions would push people back to Excel.

There is no `approved` status — a filled `pr_number` is the approval evidence.

### Asset events

Every change appends one **Asset event**: a timestamp, the actor, what changed,
and an optional note. The current row is a projection; the event log is the
history.

Three properties worth knowing:

- **The actor is derived, never declared.** It comes from the caller's
  identity — the signed-in user, `svc:<prefix>` for the Service token,
  `session:<id>` when a playbook drafted the Asset, `cli:<os-user>` for CSV
  import. There is no request field for it, because an actor the caller can
  choose is not evidence of who acted.
- **Events outlive the Asset.** Deleting an Asset removes the row, not its
  events. A closing `deleted` event carries a snapshot of the identity fields,
  so the orphaned log can still name the device it is evidence about. Read them
  back through the [events feed](#rest-api) — the detail endpoint 404s once the
  row is gone.
- **Nothing is ever edited or backfilled.** Events written before attribution
  was derived carry placeholders such as `web-user`; they are left alone.
  Rewriting the log to make an audit view look tidier is the one thing an
  append-only log may not do.

Hard delete exists for data-entry mistakes. Retirement is a *status*, not a
deletion — a device that left the building should end as `retired`.

## Procurements

An optional grouping over existing Assets, for when a batch really is one
purchase. The Procurement adopts the fields its members agree on; a field where
they disagree starts empty.

Editing the Procurement syncs `pr_number`, `order_number`, `tracking_number`,
`vendor` and `cost` to every member, each sync appending an event on the member.
Deleting the Procurement ungroups the members and leaves their fields untouched.

Ids are `prc_<ULID>`.

## Migrating a spreadsheet in

```bash
opspilot inventory import assets.csv
```

One Asset per row. Columns map by exact field name; unrecognized headers are
reported rather than silently dropped, and a bad row is skipped with its row
number rather than aborting the run — a 500-row sheet with three bad rows
imports 497 and tells you about the three.

Rows are skipped for a duplicate serial or an unknown status. Every created
event records `cli:<os-user>` with the source filename in the note.

```bash
opspilot inventory export assets.csv
```

Exports `asset_id`, every field, `created_at` and `updated_at`. The round trip
is lossless: re-importing an export preserves `asset_id` and `created_at`
(`updated_at` is regenerated), so export → edit in Excel → import back works as
a bulk-edit workflow.

## Warranty expiry

```bash
opspilot inventory warranty-check --days 30
```

Lists Assets whose warranty ends within the window or has already ended.
Retired assets and empty warranties are excluded. When `WECOM_WEBHOOK_URL` is
set it also pushes a summary to the group robot, which makes it a reasonable
cron job.

The same filter is on the list endpoint as `?expiring_days=30`.

## REST API

Reads need the `viewer` role, writes need `operator` (ADR-0020).

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/api/inventory` | filters: `status`, `assignee`, `q`, `expiring_days` |
| `POST` | `/api/inventory` | 422 unknown status · 409 duplicate serial |
| `GET` | `/api/inventory/{asset_id}` | the row plus its full event log |
| `PATCH` | `/api/inventory/{asset_id}` | a no-op patch appends no event |
| `DELETE` | `/api/inventory/{asset_id}` | row goes, events stay |
| `GET` | `/api/inventory/events` | cross-Asset feed; filters: `asset_id`, `actor`, `since`, `until`, `limit` |
| `GET` | `/api/inventory/procurements` | |
| `POST` | `/api/inventory/procurements` | group existing Assets by id |
| `GET` | `/api/inventory/procurements/{id}` | with members |
| `PATCH` | `/api/inventory/procurements/{id}` | syncs shared fields to members |
| `DELETE` | `/api/inventory/procurements/{id}` | ungroups; fields stay |

`q` searches `asset_tag`, `brand_model`, `serial_number`, `assignee`, `handler`
and `vendor`.

The events feed is the only read that reaches a deleted Asset's history.

## Web UI

The `inventory` module is on by default and is toggled with the other modules:

```yaml
ui:
  modules:
    run: true
    history: true
    inventory: true
```

## Assets drafted from a Service Request

A physical-device Service Request can draft its Assets automatically: when a
fulfillment artifact validates with an `asset_draft` block, OpsPilot creates the
requested-status Assets for that Work item, stamped with the Session that
produced them and idempotent per Work item
([ADR-0018](adr/0018-fulfillment-drafts-assets.md)).

This is the one path where Assets appear without anyone typing them, which is
why those events carry a `session:<id>` actor rather than a person.

## What v1 deliberately does not do

- **No enforced status transitions** — see above.
- **No normalized Procurement as the primary model.** Procurements are an
  optional grouping layered on top; the Asset row still carries its own
  procurement fields.
- **No AI in the inventory itself.** The only automated writer is the
  fulfillment draft path, and it goes through the same validation as a human.
