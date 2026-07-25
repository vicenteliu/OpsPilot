"""Asset drafting from a fulfillment artifact (ADR-0018).

Real InventoryStore over in-memory SQLite; the artifact dicts mirror what
a schema-valid request_fulfillment_v1 run produces.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from opspilot.inventory import InventoryStore, draft_assets_from_result
from opspilot.schemas import validate


def _store() -> InventoryStore:
    return InventoryStore(sqlite3.connect(":memory:", check_same_thread=False))


def _artifact(**over: Any) -> dict[str, Any]:
    return {
        "schema_version": "request_fulfillment_v1",
        "work_item_ref": "REQ-42",
        "work_item_type": "service_request",
        "summary": "Two laptops for the new platform hires.",
        "requested_item": "2× laptops for new hires",
        "approval_needed": True,
        "asset_draft": {
            "category": "laptop",
            "brand_model": "ThinkPad T14",
            "specs": "32GB RAM",
            "quantity": 2,
        },
        "missing_fields": [],
        "tasks": [
            {"ref": "task-1", "action": "Order laptops", "rationale": "per SOP", "tier": "L1"}
        ],
        "citations": [{"id": "kb-1", "chunk_id": "chk_00000000", "document_id": "doc_00000000"}],
        **over,
    }


class TestDraftAssets:
    def test_quantity_devices_drafted_with_backlink_and_event(self) -> None:
        store = _store()
        created = draft_assets_from_result(store, _artifact(), session_id="ses_x")
        assert len(created) == 2
        for aid in created:
            row = store.get(aid)
            assert row is not None
            assert row["status"] == "requested"
            assert row["work_item_ref"] == "REQ-42"
            assert row["category"] == "laptop"
            assert row["brand_model"] == "ThinkPad T14"
            events = store.events(aid)
            assert [e["change"] for e in events] == ["drafted"]
            assert events[0]["actor"] == "session:ses_x"
            assert "REQ-42" in events[0]["note"]

    def test_idempotent_by_work_item_ref(self) -> None:
        store = _store()
        first = draft_assets_from_result(store, _artifact(), session_id="ses_x")
        second = draft_assets_from_result(store, _artifact(), session_id="ses_y")
        assert len(first) == 2
        assert second == []
        assert len(store.list(work_item_ref="REQ-42")) == 2

    def test_no_draft_block_creates_nothing(self) -> None:
        store = _store()
        artifact = _artifact()
        del artifact["asset_draft"]
        assert draft_assets_from_result(store, artifact, session_id="ses_x") == []
        assert store.list() == []

    def test_missing_work_item_ref_creates_nothing(self) -> None:
        store = _store()
        assert draft_assets_from_result(store, _artifact(work_item_ref=""), "ses_x") == []

    def test_quantity_capped_and_floored(self) -> None:
        store = _store()
        big = _artifact()
        big["asset_draft"]["quantity"] = 500
        assert len(draft_assets_from_result(store, big, "ses_x")) == 20
        bad = _artifact(work_item_ref="REQ-43")
        bad["asset_draft"]["quantity"] = "not-a-number"
        assert len(draft_assets_from_result(store, bad, "ses_x")) == 1


class TestSchemaAdditive:
    def test_artifact_with_asset_draft_validates(self) -> None:
        validate("request_fulfillment_v1", _artifact())

    def test_artifact_without_asset_draft_still_validates(self) -> None:
        artifact = _artifact()
        del artifact["asset_draft"]
        validate("request_fulfillment_v1", artifact)
