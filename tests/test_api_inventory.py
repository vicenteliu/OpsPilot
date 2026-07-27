"""Inventory — Asset CRUD, event log, serial uniqueness (ADR-0017).

Real InventoryStore over an in-memory SQLite; only the FastAPI app is
test-built. No LLM, no network.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.inventory import router as inventory_router
from opspilot.auth import AuthStore
from opspilot.inventory import InventoryStore


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(inventory_router, prefix="/api")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    app.state.inventory = InventoryStore(conn)
    # No users + no service token → deps fall back to local-dev operator,
    # so these inventory tests exercise CRUD without managing sessions.
    app.state.auth = AuthStore(conn)
    app.state.service_token = None
    return TestClient(app)


def _laptop(**over: Any) -> dict[str, Any]:
    return {
        "asset_tag": "NB-001",
        "category": "laptop",
        "brand_model": "ThinkPad T14 Gen 5",
        "serial_number": "SN-A1",
        "work_item_ref": "REQ-42",
        "pr_number": "PR-2026-007",
        "handler": "vicente",
        **over,
    }


class TestCreate:
    def test_create_defaults_to_requested_with_created_event(self) -> None:
        c = _client()
        res = c.post("/api/inventory", json=_laptop())
        assert res.status_code == 201
        body = res.json()
        assert body["asset_id"].startswith("ast_")
        assert body["status"] == "requested"
        detail = c.get(f"/api/inventory/{body['asset_id']}").json()
        assert [e["change"] for e in detail["events"]] == ["created"]

    def test_existing_stock_enters_mid_flow(self) -> None:
        c = _client()
        res = c.post(
            "/api/inventory",
            json={"brand_model": "Dell U2723QE", "category": "monitor", "status": "deployed"},
        )
        assert res.status_code == 201
        assert res.json()["status"] == "deployed"
        assert res.json()["pr_number"] == ""  # no procurement trail is fine

    def test_unknown_status_rejected_422(self) -> None:
        c = _client()
        res = c.post("/api/inventory", json=_laptop(status="lost"))
        assert res.status_code == 422

    def test_duplicate_serial_409(self) -> None:
        c = _client()
        assert c.post("/api/inventory", json=_laptop()).status_code == 201
        res = c.post("/api/inventory", json=_laptop(asset_tag="NB-002"))
        assert res.status_code == 409

    def test_empty_serials_do_not_conflict(self) -> None:
        c = _client()
        assert c.post("/api/inventory", json={"category": "mouse"}).status_code == 201
        assert c.post("/api/inventory", json={"category": "keyboard"}).status_code == 201


class TestUpdate:
    def test_patch_appends_one_diff_event(self) -> None:
        c = _client()
        aid = c.post("/api/inventory", json=_laptop()).json()["asset_id"]
        res = c.patch(
            f"/api/inventory/{aid}",
            json={"status": "deployed", "assignee": "Alice"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "deployed"
        events = c.get(f"/api/inventory/{aid}").json()["events"]
        assert len(events) == 2  # created + one combined diff
        assert "status: 'requested' → 'deployed'" in events[-1]["change"]
        assert "assignee: '' → 'Alice'" in events[-1]["change"]
        assert events[-1]["actor"] == "local-dev"  # from the identity, not the body

    def test_status_freely_settable_backwards(self) -> None:
        c = _client()
        aid = c.post("/api/inventory", json=_laptop(status="deployed")).json()["asset_id"]
        # No state machine: corrections go backwards without complaint.
        assert c.patch(f"/api/inventory/{aid}", json={"status": "received"}).status_code == 200

    def test_noop_patch_appends_no_event(self) -> None:
        c = _client()
        aid = c.post("/api/inventory", json=_laptop()).json()["asset_id"]
        c.patch(f"/api/inventory/{aid}", json={"handler": "vicente"})  # same value
        assert len(c.get(f"/api/inventory/{aid}").json()["events"]) == 1

    def test_patch_to_taken_serial_409(self) -> None:
        c = _client()
        c.post("/api/inventory", json=_laptop())
        other = c.post("/api/inventory", json=_laptop(serial_number="SN-B2")).json()
        res = c.patch(f"/api/inventory/{other['asset_id']}", json={"serial_number": "SN-A1"})
        assert res.status_code == 409

    def test_patch_missing_404(self) -> None:
        assert _client().patch("/api/inventory/ast_missing", json={"notes": "x"}).status_code == 404


class TestListAndFilters:
    def test_filters_and_search(self) -> None:
        c = _client()
        c.post("/api/inventory", json=_laptop(status="deployed", assignee="Alice"))
        c.post(
            "/api/inventory",
            json=_laptop(asset_tag="NB-002", serial_number="SN-B2", status="in_stock", assignee=""),
        )
        assert len(c.get("/api/inventory").json()["assets"]) == 2
        deployed = c.get("/api/inventory", params={"status": "deployed"}).json()["assets"]
        assert [a["assignee"] for a in deployed] == ["Alice"]
        by_person = c.get("/api/inventory", params={"assignee": "Alice"}).json()["assets"]
        assert len(by_person) == 1
        hits = c.get("/api/inventory", params={"q": "SN-B2"}).json()["assets"]
        assert [a["asset_tag"] for a in hits] == ["NB-002"]


class TestWarrantyExpiry:
    @staticmethod
    def _days_from_now(days: int) -> str:
        from datetime import UTC, datetime, timedelta

        return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%d")

    def test_expiring_filter_includes_soon_and_past_excludes_far_empty_retired(self) -> None:
        c = _client()
        soon = self._days_from_now(10)
        far = self._days_from_now(100)
        past = self._days_from_now(-5)
        c.post("/api/inventory", json=_laptop(warranty_until=soon))
        c.post(
            "/api/inventory",
            json=_laptop(asset_tag="NB-002", serial_number="SN-B2", warranty_until=far),
        )
        c.post(
            "/api/inventory",
            json=_laptop(asset_tag="NB-003", serial_number="SN-C3", warranty_until=past),
        )
        c.post(
            "/api/inventory",
            json=_laptop(asset_tag="NB-004", serial_number="SN-D4"),  # no warranty
        )
        c.post(
            "/api/inventory",
            json=_laptop(
                asset_tag="NB-005", serial_number="SN-E5", warranty_until=soon, status="retired"
            ),
        )
        hits = c.get("/api/inventory", params={"expiring_days": 30}).json()["assets"]
        assert sorted(a["asset_tag"] for a in hits) == ["NB-001", "NB-003"]
        # Tighter window drops the 10-days-out one but keeps the already-past one.
        week = c.get("/api/inventory", params={"expiring_days": 7}).json()["assets"]
        assert [a["asset_tag"] for a in week] == ["NB-003"]


class TestProcurements:
    def _five(self, c: TestClient) -> list[str]:
        ids = []
        for i in range(5):
            res = c.post(
                "/api/inventory",
                json=_laptop(
                    asset_tag=f"NB-10{i}",
                    serial_number=f"SN-P{i}",
                    pr_number="PR-2026-007",
                    vendor="JD" if i < 3 else "Tmall",  # disagreeing field
                ),
            )
            ids.append(res.json()["asset_id"])
        return ids

    def test_group_adopts_common_fields_and_marks_members(self) -> None:
        c = _client()
        ids = self._five(c)
        res = c.post("/api/inventory/procurements", json={"asset_ids": ids})
        assert res.status_code == 201
        proc = res.json()
        assert proc["procurement_id"].startswith("prc_")
        assert proc["member_count"] == 5
        assert proc["pr_number"] == "PR-2026-007"  # unanimous → adopted
        assert proc["vendor"] == ""  # disagreeing → starts empty
        first = c.get(f"/api/inventory/{ids[0]}").json()
        assert first["procurement_id"] == proc["procurement_id"]
        assert any("grouped into" in e["change"] for e in first["events"])

    def test_patch_syncs_to_all_members_with_events(self) -> None:
        c = _client()
        ids = self._five(c)
        pid = c.post("/api/inventory/procurements", json={"asset_ids": ids}).json()[
            "procurement_id"
        ]
        res = c.patch(
            f"/api/inventory/procurements/{pid}",
            json={"tracking_number": "SF-123456"},
        )
        assert res.status_code == 200
        assert res.json()["tracking_number"] == "SF-123456"
        for aid in ids:
            detail = c.get(f"/api/inventory/{aid}").json()
            assert detail["tracking_number"] == "SF-123456"
            sync_events = [e for e in detail["events"] if "tracking_number" in e["change"]]
            assert len(sync_events) == 1
            assert pid in sync_events[0]["note"]

    def test_list_and_detail_routes_not_shadowed_by_asset_id(self) -> None:
        c = _client()
        ids = self._five(c)
        pid = c.post("/api/inventory/procurements", json={"asset_ids": ids}).json()[
            "procurement_id"
        ]
        listing = c.get("/api/inventory/procurements")
        assert listing.status_code == 200  # literal segment wins over {asset_id}
        assert listing.json()["procurements"][0]["member_count"] == 5
        detail = c.get(f"/api/inventory/procurements/{pid}").json()
        assert len(detail["members"]) == 5

    def test_delete_ungroups_without_touching_fields(self) -> None:
        c = _client()
        ids = self._five(c)
        pid = c.post("/api/inventory/procurements", json={"asset_ids": ids}).json()[
            "procurement_id"
        ]
        assert c.delete(f"/api/inventory/procurements/{pid}").status_code == 204
        for aid in ids:
            detail = c.get(f"/api/inventory/{aid}").json()
            assert detail["procurement_id"] == ""
            assert detail["pr_number"] == "PR-2026-007"  # fields kept
            assert any("ungrouped" in e["change"] for e in detail["events"])
        assert c.delete(f"/api/inventory/procurements/{pid}").status_code == 404

    def test_group_unknown_asset_404(self) -> None:
        c = _client()
        res = c.post("/api/inventory/procurements", json={"asset_ids": ["ast_missing"]})
        assert res.status_code == 404


class TestDelete:
    def test_delete_then_404(self) -> None:
        c = _client()
        aid = c.post("/api/inventory", json=_laptop()).json()["asset_id"]
        assert c.delete(f"/api/inventory/{aid}").status_code == 204
        assert c.get(f"/api/inventory/{aid}").status_code == 404
        assert c.delete(f"/api/inventory/{aid}").status_code == 404

    def test_events_outlive_the_asset_and_still_name_the_device(self) -> None:
        c = _client()
        aid = c.post("/api/inventory", json=_laptop()).json()["asset_id"]
        c.patch(f"/api/inventory/{aid}", json={"status": "deployed"})
        assert c.delete(f"/api/inventory/{aid}").status_code == 204

        events = c.get("/api/inventory/events", params={"asset_id": aid}).json()["events"]
        # created + the status diff + the closing deleted event.
        assert [e["change"] for e in events][-1] == "created"  # newest first
        closing = events[0]
        assert closing["change"].startswith("deleted (")
        # The orphaned log has to name the device; the id alone is not evidence.
        assert "asset_tag=NB-001" in closing["change"]
        assert "serial_number=SN-A1" in closing["change"]
        assert closing["actor"] == "local-dev"


class TestActorAttribution:
    """The actor is the caller's identity, never what the caller claims."""

    def test_forged_actor_in_body_is_ignored(self) -> None:
        c = _client()
        res = c.post("/api/inventory", json=_laptop(actor="ceo", note="signed off"))
        assert res.status_code == 201  # unknown field ignored, not a 422
        aid = res.json()["asset_id"]
        event = c.get(f"/api/inventory/{aid}").json()["events"][0]
        assert event["actor"] == "local-dev"
        assert event["note"] == "signed off"  # note is an annotation, still the caller's

    def test_service_token_identity_is_recorded(self) -> None:
        app = FastAPI()
        app.include_router(inventory_router, prefix="/api")
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        app.state.inventory = InventoryStore(conn)
        app.state.auth = AuthStore(conn)
        app.state.service_token = "tok-abcdef-secret"
        c = TestClient(app, headers={"Authorization": "Bearer tok-abcdef-secret"})
        aid = c.post("/api/inventory", json=_laptop()).json()["asset_id"]
        event = c.get(f"/api/inventory/{aid}").json()["events"][0]
        assert event["actor"] == "svc:tok-ab"


class TestEventsFeed:
    def test_spans_assets_and_filters(self) -> None:
        c = _client()
        first = c.post("/api/inventory", json=_laptop()).json()["asset_id"]
        second = c.post(
            "/api/inventory", json=_laptop(asset_tag="NB-002", serial_number="SN-B2")
        ).json()["asset_id"]
        c.patch(f"/api/inventory/{second}", json={"status": "shipped"})

        everything = c.get("/api/inventory/events").json()["events"]
        assert len(everything) == 3
        assert {e["asset_id"] for e in everything} == {first, second}
        # Newest first, so the shipped diff leads.
        assert "shipped" in everything[0]["change"]

        only_first = c.get("/api/inventory/events", params={"asset_id": first}).json()["events"]
        assert [e["asset_id"] for e in only_first] == [first]
        assert c.get("/api/inventory/events", params={"actor": "nobody"}).json()["events"] == []
        assert len(c.get("/api/inventory/events", params={"limit": 1}).json()["events"]) == 1

    def test_events_path_is_not_captured_as_an_asset_id(self) -> None:
        # /inventory/events must be routed before /inventory/{asset_id}.
        assert _client().get("/api/inventory/events").status_code == 200
