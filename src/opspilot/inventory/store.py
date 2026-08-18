"""Asset inventory store — OpsPilot's first owned domain (ADR-0017).

One device = one Asset row; every change appends an Asset event with a
timestamp and actor. The row is a projection, the event log is the
history. Schema creation is idempotent (``CREATE TABLE IF NOT EXISTS``),
matching :mod:`opspilot.kb.storage_init`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from ..ids import new_ulid_id
from ..timeutil import UTC, now_rfc3339

# Eight free-set statuses — a convention, not a state machine (ADR-0017).
VALID_STATUSES = (
    "requested",
    "ordered",
    "shipped",
    "received",
    "in_stock",
    "deployed",
    "in_repair",
    "retired",
)

# Mutable Asset fields, in glossary order: identity / procurement / lifecycle.
FIELDS = (
    "asset_tag",
    "category",
    "brand_model",
    "serial_number",
    "specs",
    "notes",
    "work_item_ref",
    "pr_number",
    "order_number",
    "tracking_number",
    "vendor",
    "cost",
    "status",
    "handler",
    "assignee",
    "location",
    "warranty_until",
)

# Columns the free-text search (?q=) matches against.
_SEARCH_FIELDS = ("asset_tag", "brand_model", "serial_number", "assignee", "handler", "vendor")

# Identity fields stamped into the closing ``deleted`` event, so the log still
# names the device once its row is gone.
_SNAPSHOT_FIELDS = ("asset_tag", "serial_number", "category", "brand_model")

# Procurement fields shared by a batch; a Procurement PATCH syncs them to
# every member Asset (#87). A subset of FIELDS.
PROCUREMENT_FIELDS = ("pr_number", "order_number", "tracking_number", "vendor", "cost")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    asset_id        TEXT PRIMARY KEY,
    asset_tag       TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT '',
    brand_model     TEXT NOT NULL DEFAULT '',
    serial_number   TEXT NOT NULL DEFAULT '',
    specs           TEXT NOT NULL DEFAULT '',
    notes           TEXT NOT NULL DEFAULT '',
    work_item_ref   TEXT NOT NULL DEFAULT '',
    pr_number       TEXT NOT NULL DEFAULT '',
    order_number    TEXT NOT NULL DEFAULT '',
    tracking_number TEXT NOT NULL DEFAULT '',
    vendor          TEXT NOT NULL DEFAULT '',
    cost            TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'requested',
    handler         TEXT NOT NULL DEFAULT '',
    assignee        TEXT NOT NULL DEFAULT '',
    location        TEXT NOT NULL DEFAULT '',
    warranty_until  TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_serial
    ON assets(serial_number) WHERE serial_number != '';
CREATE TABLE IF NOT EXISTS asset_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    ts       TEXT NOT NULL,
    actor    TEXT NOT NULL DEFAULT '',
    change   TEXT NOT NULL,
    note     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_asset_events_asset ON asset_events(asset_id, event_id);
CREATE TABLE IF NOT EXISTS procurements (
    procurement_id  TEXT PRIMARY KEY,
    pr_number       TEXT NOT NULL DEFAULT '',
    order_number    TEXT NOT NULL DEFAULT '',
    tracking_number TEXT NOT NULL DEFAULT '',
    vendor          TEXT NOT NULL DEFAULT '',
    cost            TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""


# ``InventoryStore.list`` shadows the builtin inside the class body, so
# methods defined after it use these module-level aliases in annotations.
_Rows = list[dict[str, Any]]
_Ids = list[str]


class AssetNotFoundError(Exception):
    """No Asset with the given id."""


class ProcurementNotFoundError(Exception):
    """No Procurement with the given id."""


class DuplicateSerialError(Exception):
    """A different Asset already carries this serial number."""


class UnknownStatusError(Exception):
    """Status is not one of the eight valid values."""


def _validate_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise UnknownStatusError(f"unknown status '{status}'; valid: {', '.join(VALID_STATUSES)}")


class InventoryStore:
    """CRUD + event log over the ``assets`` / ``asset_events`` tables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        conn.executescript(_SCHEMA)
        # Idempotent column migration (#87): CREATE TABLE IF NOT EXISTS
        # cannot add columns to an existing table.
        asset_cols = {r[1] for r in conn.execute("PRAGMA table_info(assets)")}
        if "procurement_id" not in asset_cols:
            conn.execute("ALTER TABLE assets ADD COLUMN procurement_id TEXT NOT NULL DEFAULT ''")
        conn.commit()

    # ── reads ──────────────────────────────────────────────────────────

    def get(self, asset_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,))
        row = cur.fetchone()
        return dict(zip((d[0] for d in cur.description), row, strict=True)) if row else None

    def events(self, asset_id: str) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT event_id, ts, actor, change, note FROM asset_events "
            "WHERE asset_id = ? ORDER BY event_id",
            (asset_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def all_events(
        self,
        *,
        asset_id: str = "",
        actor: str = "",
        since: str = "",
        until: str = "",
        limit: int = 200,
    ) -> _Rows:
        """Events across every Asset, newest first — including orphaned ones.

        Events survive their Asset (see :meth:`delete`), so this is the only
        read that can reach a deleted Asset's history: the per-asset detail
        endpoint 404s once the row is gone, and by then the caller no longer
        knows the id to ask for. Timestamps are RFC3339 UTC, which orders
        lexicographically, so *since* / *until* compare as plain strings.
        """
        where, params = [], []
        for column, value in (("asset_id", asset_id), ("actor", actor)):
            if value:
                where.append(f"{column} = ?")
                params.append(value)
        for op, value in ((">=", since), ("<=", until)):
            if value:
                where.append(f"ts {op} ?")
                params.append(value)
        clause = f"WHERE {' AND '.join(where)} " if where else ""
        cur = self._conn.execute(
            "SELECT event_id, asset_id, ts, actor, change, note FROM asset_events "
            f"{clause}ORDER BY event_id DESC LIMIT ?",
            (*params, limit),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def expiring_warranties(self, days: int) -> list[dict[str, Any]]:
        """Assets whose warranty ends within *days* (or already ended).

        ISO date strings compare lexicographically, so a plain string
        comparison against the cutoff date is correct for both date-only
        and RFC3339 values. Empty warranties and retired assets are out.
        """
        cutoff = (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%d")
        cur = self._conn.execute(
            "SELECT * FROM assets WHERE warranty_until != '' AND status != 'retired' "
            "AND substr(warranty_until, 1, 10) <= ? ORDER BY warranty_until",
            (cutoff,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def list(
        self,
        status: str | None = None,
        assignee: str | None = None,
        q: str | None = None,
        work_item_ref: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses, params = ["1=1"], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if assignee:
            clauses.append("assignee = ?")
            params.append(assignee)
        if work_item_ref:
            clauses.append("work_item_ref = ?")
            params.append(work_item_ref)
        if q:
            like = f"%{q}%"
            clauses.append("(" + " OR ".join(f"{f} LIKE ?" for f in _SEARCH_FIELDS) + ")")
            params.extend([like] * len(_SEARCH_FIELDS))
        cur = self._conn.execute(
            f"SELECT * FROM assets WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",  # noqa: S608 — clauses are static, values parameterized
            params,
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    # ── writes (every write appends an Asset event) ────────────────────

    def create(
        self,
        fields: dict[str, Any],
        actor: str = "",
        note: str = "",
        asset_id: str | None = None,
        created_at: str | None = None,
        event_change: str = "created",
    ) -> dict[str, Any]:
        """Insert one Asset; ``asset_id``/``created_at`` overrides exist for
        the CSV round trip (#80) — normal callers omit them."""
        payload = {f: "" if fields.get(f) is None else str(fields.get(f, "")) for f in FIELDS}
        if not payload["status"]:
            payload["status"] = "requested"
        _validate_status(payload["status"])
        aid = asset_id or new_ulid_id("ast")
        now = now_rfc3339()
        columns = ["asset_id", *FIELDS, "created_at", "updated_at"]
        values = [aid, *(payload[f] for f in FIELDS), created_at or now, now]
        try:
            self._conn.execute(
                f"INSERT INTO assets ({', '.join(columns)}) "  # noqa: S608 — column names are static
                f"VALUES ({', '.join('?' * len(columns))})",
                values,
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateSerialError(
                f"serial number '{payload['serial_number']}' already exists"
            ) from exc
        self._append_event(aid, actor, event_change, note)
        self._conn.commit()
        result = self.get(aid)
        assert result is not None  # just inserted
        return result

    def update(
        self, asset_id: str, changes: dict[str, Any], actor: str = "", note: str = ""
    ) -> dict[str, Any]:
        current = self.get(asset_id)
        if current is None:
            raise AssetNotFoundError(asset_id)
        applied = {
            k: "" if v is None else str(v)
            for k, v in changes.items()
            if k in FIELDS and ("" if v is None else str(v)) != current[k]
        }
        if not applied:
            return current
        if "status" in applied:
            _validate_status(applied["status"])
        sets = ", ".join(f"{k} = ?" for k in applied)
        try:
            self._conn.execute(
                f"UPDATE assets SET {sets}, updated_at = ? WHERE asset_id = ?",  # noqa: S608 — keys are validated field names
                [*applied.values(), now_rfc3339(), asset_id],
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateSerialError(
                f"serial number '{applied.get('serial_number', '')}' already exists"
            ) from exc
        diff = "; ".join(f"{k}: '{current[k]}' → '{v}'" for k, v in applied.items())
        self._append_event(asset_id, actor, diff, note)
        self._conn.commit()
        result = self.get(asset_id)
        assert result is not None
        return result

    def delete(self, asset_id: str, actor: str = "", note: str = "") -> bool:
        """Hard delete, for data-entry mistakes — retirement is a status.

        The row is a projection and the event log is the truth (ADR-0017), so
        only the projection goes: the events outlive the Asset. A closing
        ``deleted`` event carries a snapshot of the identity fields, because an
        orphaned log that can only say ``ast_01H8X...`` cannot name the device
        it is evidence about.
        """
        row = self.get(asset_id)
        if row is None:
            return False
        snapshot = ", ".join(f"{f}={row[f]}" for f in _SNAPSHOT_FIELDS if row[f])
        self._append_event(
            asset_id, actor, f"deleted ({snapshot})" if snapshot else "deleted", note
        )
        self._conn.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))
        self._conn.commit()
        return True

    # ── procurements: optional grouping with batch field sync (#87) ────

    def get_procurement(self, procurement_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM assets a WHERE a.procurement_id = p.procurement_id)"
            " AS member_count FROM procurements p WHERE p.procurement_id = ?",
            (procurement_id,),
        )
        row = cur.fetchone()
        return dict(zip((d[0] for d in cur.description), row, strict=True)) if row else None

    def list_procurements(self) -> _Rows:
        cur = self._conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM assets a WHERE a.procurement_id = p.procurement_id)"
            " AS member_count FROM procurements p ORDER BY p.created_at DESC"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def procurement_members(self, procurement_id: str) -> _Rows:
        cur = self._conn.execute(
            "SELECT * FROM assets WHERE procurement_id = ? ORDER BY created_at",
            (procurement_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def create_procurement(self, asset_ids: _Ids, actor: str = "") -> dict[str, Any]:
        """Group existing Assets; the Procurement adopts their common fields.

        A field where members disagree starts empty — the next PATCH
        settles it and syncs everyone.
        """
        if not asset_ids:
            raise AssetNotFoundError("no asset ids given")
        members: _Rows = []
        for aid in asset_ids:
            row = self.get(aid)
            if row is None:
                raise AssetNotFoundError(aid)
            members.append(row)
        adopted = {}
        for f in PROCUREMENT_FIELDS:
            values = {m[f] for m in members}
            adopted[f] = next(iter(values)) if len(values) == 1 else ""
        pid = new_ulid_id("prc")
        now = now_rfc3339()
        self._conn.execute(
            "INSERT INTO procurements (procurement_id, pr_number, order_number, "
            "tracking_number, vendor, cost, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (pid, *(adopted[f] for f in PROCUREMENT_FIELDS), now, now),
        )
        for m in members:
            self._conn.execute(
                "UPDATE assets SET procurement_id = ?, updated_at = ? WHERE asset_id = ?",
                (pid, now, m["asset_id"]),
            )
            self._append_event(m["asset_id"], actor, f"grouped into {pid}", "")
        self._conn.commit()
        result = self.get_procurement(pid)
        assert result is not None
        return result

    def update_procurement(
        self, procurement_id: str, changes: dict[str, Any], actor: str = ""
    ) -> dict[str, Any]:
        """Update procurement fields and sync them to every member Asset.

        Each member goes through :meth:`update`, so every touched Asset
        gets its own diff event."""
        current = self.get_procurement(procurement_id)
        if current is None:
            raise ProcurementNotFoundError(procurement_id)
        applied = {
            k: "" if v is None else str(v)
            for k, v in changes.items()
            if k in PROCUREMENT_FIELDS and ("" if v is None else str(v)) != current[k]
        }
        if not applied:
            return current
        sets = ", ".join(f"{k} = ?" for k in applied)
        self._conn.execute(
            f"UPDATE procurements SET {sets}, updated_at = ? WHERE procurement_id = ?",  # noqa: S608 — keys validated against PROCUREMENT_FIELDS
            [*applied.values(), now_rfc3339(), procurement_id],
        )
        self._conn.commit()
        for member in self.procurement_members(procurement_id):
            self.update(
                member["asset_id"], applied, actor=actor, note=f"synced from {procurement_id}"
            )
        result = self.get_procurement(procurement_id)
        assert result is not None
        return result

    def delete_procurement(self, procurement_id: str, actor: str = "") -> bool:
        """Ungroup members (fields untouched) and delete the Procurement."""
        members = self.procurement_members(procurement_id)
        now = now_rfc3339()
        for m in members:
            self._conn.execute(
                "UPDATE assets SET procurement_id = '', updated_at = ? WHERE asset_id = ?",
                (now, m["asset_id"]),
            )
            self._append_event(m["asset_id"], actor, f"ungrouped from {procurement_id}", "")
        cur = self._conn.execute(
            "DELETE FROM procurements WHERE procurement_id = ?", (procurement_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def _append_event(self, asset_id: str, actor: str, change: str, note: str) -> None:
        self._conn.execute(
            "INSERT INTO asset_events (asset_id, ts, actor, change, note) VALUES (?, ?, ?, ?, ?)",
            (asset_id, now_rfc3339(), actor, change, note),
        )
