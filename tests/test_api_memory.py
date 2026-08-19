"""Memory, Consultation and Working set over HTTP.

Two rules run through these routes and are the reason they are not generic CRUD.

**The actor is never taken from the request** — it comes from the caller's
Identity, the same rule as an Asset event, a Resolution and a Correction. These
are decisions about what the assistant will believe, so the one thing that must
not be self-reported is who decided.

**A Consultation is visible to its author and to admins.** ADR-0032 buys "cheap
and deletable" with privacy, and a surface colleagues can browse is one where
people weigh their words. Someone else's conversation answers 404, not 403:
whether it exists is itself private.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opspilot.api.routes.memory import router as memory_router
from opspilot.auth import AuthStore
from opspilot.consultation import ConsultationStore, WorkingSetStore
from opspilot.kb.storage_init import init_sqlite
from opspilot.memory import MemoryStore


def _app(tmp_path: Path):
    app = FastAPI()
    app.include_router(memory_router, prefix="/api")
    conn = init_sqlite(tmp_path / "kb.db")
    app.state.auth = AuthStore(conn)  # no users + no token → local-dev operator
    app.state.service_token = None
    app.state.memory = MemoryStore(conn)
    app.state.consultations = ConsultationStore(conn)
    app.state.working_sets = WorkingSetStore(conn)
    return app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(_app(tmp_path))


class TestMemory:
    def test_admitting_stamps_the_caller_not_the_body(self, client: TestClient) -> None:
        res = client.post(
            "/api/memory",
            json={
                "statement": "No ESXi restarts Tuesday evening",
                "reason": "finance runs its batch then",
                "scope": "dc-1",
                # A body field named like the actor must not be honoured.
                "actor": "somebody-else",
            },
        )
        assert res.status_code == 200
        assert res.json()["actor"] != "somebody-else"

    def test_a_missing_reason_is_refused(self, client: TestClient) -> None:
        res = client.post("/api/memory", json={"statement": "x", "reason": "  "})
        assert res.status_code == 400
        assert "reason is required" in res.json()["detail"]

    def test_anchored_reads_are_a_filter(self, client: TestClient) -> None:
        client.post("/api/memory", json={"statement": "a", "reason": "r", "scope": "site-a"})
        client.post("/api/memory", json={"statement": "b", "reason": "r", "scope": "site-b"})
        client.post("/api/memory", json={"statement": "global", "reason": "r"})
        got = {e["statement"] for e in client.get("/api/memory?scope=site-a").json()["entries"]}
        assert got == {"a", "global"}

    def test_superseding_keeps_the_old_entry(self, client: TestClient) -> None:
        old = client.post(
            "/api/memory", json={"statement": "old", "reason": "r", "scope": "dc-1"}
        ).json()
        new = client.post(
            f"/api/memory/{old['id']}/supersede", json={"statement": "new", "reason": "changed"}
        ).json()
        listed = client.get("/api/memory?include_retired=true").json()["entries"]
        by_id = {e["id"]: e for e in listed}
        assert by_id[old["id"]]["superseded_by"] == new["id"]
        assert by_id[old["id"]]["statement"] == "old"

    def test_scopes_are_offered_for_pick_or_create(self, client: TestClient) -> None:
        client.post("/api/memory", json={"statement": "a", "reason": "r", "scope": "site-b"})
        client.post("/api/memory", json={"statement": "b", "reason": "r", "scope": "site-a"})
        assert client.get("/api/memory/scopes").json()["scopes"] == ["site-a", "site-b"]


class TestPin:
    def test_pinning_admits_and_protects_the_consultation(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        store = client.app.state.consultations
        con = store.start(author="local-dev", title="VPN")
        msg = store.append(con.id, role="assistant", content="The RADIUS pool has three nodes")
        res = client.post(
            f"/api/consultations/{con.id}/messages/{msg.id}/pin",
            json={"reason": "explains the partial outage", "scope": "dc-1"},
        )
        assert res.status_code == 200
        assert res.json()["source_ref"] == f"{con.id}/{msg.id}"
        assert store.get(con.id).pinned_reason == "memory_source"

    def test_a_refused_admission_pins_nothing(self, client: TestClient) -> None:
        store = client.app.state.consultations
        con = store.start(author="local-dev", title="VPN")
        msg = store.append(con.id, role="assistant", content="something")
        res = client.post(
            f"/api/consultations/{con.id}/messages/{msg.id}/pin", json={"reason": "   "}
        )
        assert res.status_code == 400
        assert not store.get(con.id).is_pinned


class TestVisibility:
    def test_someone_elses_consultation_answers_404_not_403(self, client: TestClient) -> None:
        """Whether another person's conversation exists is itself private."""
        store = client.app.state.consultations
        con = store.start(author="someone-else", title="not yours")
        assert client.get(f"/api/consultations/{con.id}").status_code == 404

    def test_listing_shows_only_your_own(self, client: TestClient) -> None:
        store = client.app.state.consultations
        store.start(author="local-dev", title="mine")
        store.start(author="someone-else", title="theirs")
        titles = [c["title"] for c in client.get("/api/consultations").json()["consultations"]]
        assert titles == ["mine"]


class TestWorkingSet:
    def test_open_then_read_then_close(self, client: TestClient) -> None:
        opened = client.post(
            "/api/working-set", json={"title": "dc-1 latency", "scope": "dc-1"}
        ).json()
        assert client.get("/api/working-set").json()["working_set"]["id"] == opened["id"]
        assert client.delete("/api/working-set").status_code == 200
        assert client.get("/api/working-set").json()["working_set"] is None

    def test_the_inactivity_notice_is_delivered_once(self, client: TestClient) -> None:
        client.post("/api/working-set", json={"title": "dc-1 latency", "scope": "dc-1"})
        client.app.state.working_sets.sweep(idle_days=0)
        assert "closed after" in (client.get("/api/working-set").json()["notice"] or "")
        assert client.get("/api/working-set").json()["notice"] is None

    def test_closing_nothing_is_a_404(self, client: TestClient) -> None:
        assert client.delete("/api/working-set").status_code == 404


class TestRoles:
    def test_a_viewer_may_read_but_not_admit(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        auth: AuthStore = app.state.auth
        auth.upsert_user("reader", role="viewer", password="pw-reader-long")
        client = TestClient(app)
        client.cookies.set("opspilot_session", auth.create_session("reader"))

        assert client.get("/api/memory").status_code == 200
        res = client.post("/api/memory", json={"statement": "x", "reason": "y"})
        assert res.status_code == 403
        assert client.get("/api/memory").json()["total"] == 0


class TestConsultationCarriesItsWorkingSet:
    """ADR-0036 makes the Working set the chain of Consultations on one problem,
    and that chain is what distillation reads. The API returned every other
    field and dropped this one, so no client could see the relationship the
    domain is built on. Nothing broke at the time — distillation reads the store
    directly and the web client never asked for it — which is why it survived.
    """

    def test_both_reads_return_it(self, client: TestClient) -> None:
        ws = client.post("/api/working-set", json={"title": "503s after deploy"}).json()
        store = client.app.state.consultations
        con = store.start(author="local-dev", title="pods", working_set_id=ws["id"])

        assert client.get(f"/api/consultations/{con.id}").json()["working_set_id"] == ws["id"]
        listed = client.get("/api/consultations").json()["consultations"]
        assert [c["working_set_id"] for c in listed] == [ws["id"]]

    def test_a_consultation_with_no_working_set_reports_null(self, client: TestClient) -> None:
        con = client.app.state.consultations.start(author="local-dev", title="stray")
        assert client.get(f"/api/consultations/{con.id}").json()["working_set_id"] is None
