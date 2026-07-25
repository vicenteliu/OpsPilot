"""Inventory CSV import/export — spreadsheet migration path (ADR-0017).

Pure csv_io functions over a real InventoryStore on in-memory SQLite;
no CLI, no network.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from opspilot.inventory import FIELDS, InventoryStore, export_csv, import_csv


def _store() -> InventoryStore:
    return InventoryStore(sqlite3.connect(":memory:", check_same_thread=False))


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


class TestImport:
    def test_maps_fields_by_exact_name(self, tmp_path: Path) -> None:
        source = tmp_path / "assets.csv"
        _write_csv(
            source,
            ["asset_tag", "category", "serial_number", "status"],
            [["NB-001", "laptop", "SN-A1", "deployed"]],
        )
        store = _store()
        report = import_csv(store, source)
        assert report.created == 1
        assert report.skipped == []
        assert report.unknown_columns == []
        (asset,) = store.list()
        assert asset["asset_tag"] == "NB-001"
        assert asset["category"] == "laptop"
        assert asset["serial_number"] == "SN-A1"
        assert asset["status"] == "deployed"
        assert asset["vendor"] == ""  # absent column → field default

    def test_unknown_columns_reported_not_silently_dropped(self, tmp_path: Path) -> None:
        source = tmp_path / "assets.csv"
        _write_csv(
            source,
            ["asset_tag", "colour", "Serial Number"],
            [["NB-001", "black", "SN-A1"]],
        )
        report = import_csv(_store(), source)
        assert report.created == 1
        assert report.unknown_columns == ["colour", "Serial Number"]

    def test_duplicate_serial_skipped_with_row_number(self, tmp_path: Path) -> None:
        source = tmp_path / "assets.csv"
        _write_csv(
            source,
            ["asset_tag", "serial_number"],
            [["NB-001", "SN-A1"], ["NB-002", "SN-A1"], ["NB-003", "SN-B2"]],
        )
        store = _store()
        report = import_csv(store, source)
        assert report.created == 2
        [(row_number, reason)] = report.skipped
        assert row_number == 3  # header is row 1
        assert "SN-A1" in reason
        assert {a["asset_tag"] for a in store.list()} == {"NB-001", "NB-003"}

    def test_unknown_status_skipped_not_aborted(self, tmp_path: Path) -> None:
        source = tmp_path / "assets.csv"
        _write_csv(
            source,
            ["asset_tag", "status"],
            [["NB-001", "lost"], ["NB-002", "in_stock"]],
        )
        store = _store()
        report = import_csv(store, source)
        assert report.created == 1
        [(row_number, reason)] = report.skipped
        assert row_number == 2
        assert "lost" in reason
        (asset,) = store.list()
        assert asset["asset_tag"] == "NB-002"

    def test_each_created_asset_gets_one_imported_event(self, tmp_path: Path) -> None:
        source = tmp_path / "assets.csv"
        _write_csv(
            source,
            ["asset_tag", "serial_number"],
            [["NB-001", "SN-A1"], ["NB-002", "SN-B2"]],
        )
        store = _store()
        import_csv(store, source)
        for asset in store.list():
            assert [e["change"] for e in store.events(asset["asset_id"])] == ["imported"]


class TestRoundTrip:
    def test_export_import_is_lossless(self, tmp_path: Path) -> None:
        original = _store()
        # One Asset with every mutable field set, one with all defaults.
        full = {f: f"v-{f}" for f in FIELDS} | {"status": "deployed"}
        original.create(full)
        original.create({"category": "monitor"})

        out = tmp_path / "export.csv"
        assert export_csv(original, out) == 2

        restored = _store()
        report = import_csv(restored, out)
        assert report.created == 2
        assert report.skipped == []
        assert report.unknown_columns == []

        def by_id(store: InventoryStore) -> dict[str, dict[str, str]]:
            return {a["asset_id"]: a for a in store.list()}

        before, after = by_id(original), by_id(restored)
        assert before.keys() == after.keys()  # asset_id preserved
        for asset_id, expected in before.items():
            actual = after[asset_id]
            for column in ("asset_id", *FIELDS, "created_at"):
                assert actual[column] == expected[column], column
            # updated_at is regenerated on import — not compared.
