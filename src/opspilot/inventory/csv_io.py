"""CSV import/export for the asset inventory (ADR-0017).

Import is the adoption path for existing spreadsheets; export is the way
authority can be handed to a real CMDB later. Pure functions over
:class:`InventoryStore` — no CLI dependency.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .store import FIELDS, DuplicateSerialError, InventoryStore, UnknownStatusError

# Export column order: id, mutable fields in glossary order, timestamps.
_COLUMNS = ("asset_id", *FIELDS, "created_at", "updated_at")


@dataclass
class ImportReport:
    """Outcome of one CSV import: created rows, skipped rows, header issues."""

    created: int = 0
    skipped: list[tuple[int, str]] = field(default_factory=list)  # (row number, reason)
    unknown_columns: list[str] = field(default_factory=list)


def export_csv(store: InventoryStore, path: Path) -> int:
    """Write every Asset to ``path`` as CSV; return the row count."""
    assets = store.list()
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_COLUMNS)
        writer.writeheader()
        for asset in assets:
            writer.writerow({col: asset[col] for col in _COLUMNS})
    return len(assets)


def import_csv(store: InventoryStore, path: Path) -> ImportReport:
    """Create one Asset per CSV row; bad rows are skipped, never abort the run.

    Columns map by exact field name; unrecognized headers are reported in
    :attr:`ImportReport.unknown_columns` (never silently dropped). A present
    non-empty ``asset_id`` / ``created_at`` passes through to the store so a
    previous export re-imports losslessly (``updated_at`` is regenerated).
    Rows with a duplicate serial or an unknown status are recorded in
    :attr:`ImportReport.skipped` with their 1-based row number (header = row 1).
    """
    report = ImportReport()
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        known = set(_COLUMNS)
        report.unknown_columns = [c for c in (reader.fieldnames or []) if c not in known]
        for row_number, row in enumerate(reader, start=2):  # data starts after the header
            fields = {f: row[f] for f in FIELDS if f in row}
            try:
                store.create(
                    fields,
                    asset_id=row.get("asset_id") or None,
                    created_at=row.get("created_at") or None,
                    event_change="imported",
                )
            except (DuplicateSerialError, UnknownStatusError) as exc:
                report.skipped.append((row_number, str(exc)))
            else:
                report.created += 1
    return report
