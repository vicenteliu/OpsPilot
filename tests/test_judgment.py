"""Judgments: the decision file, the baseline engine, and the fallback (ADR-0040)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from opspilot.errors import ConfigError, ProviderError
from opspilot.judgment import (
    DECISIONS_DIR,
    ClassificationJudge,
    Judgment,
    JudgmentError,
    Question,
    Stage,
    TypeSafeJudge,
    build_stage,
    judge_with_fallback,
    load_question,
)
from opspilot.label_set import ANSWER_SPACE
from opspilot.orchestrator.classify import VALID_TYPES
from opspilot.orchestrator.types import load_playbook
from opspilot.providers.types import ChatResponse, Usage

REPO_ROOT = Path(__file__).resolve().parents[1]
D2 = REPO_ROOT / DECISIONS_DIR / "d2.yaml"


class _Classifier:
    provider_id = "fake"
    kind = "fake"

    def __init__(self, content: str, *, error: Exception | None = None) -> None:
        self._content = content
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def chat(
        self, messages: Any, *, model: str, params: Any, tools: Any = None, timeout_ms: int = 90_000
    ) -> ChatResponse:
        self.calls.append({"messages": messages, "timeout_ms": timeout_ms})
        if self._error is not None:
            raise self._error
        return ChatResponse(
            content=self._content,
            finish_reason="stop",
            usage=Usage(input_tokens=120, output_tokens=30, cost_usd=0.00027),
        )


def _baseline(content: str = "", **kw: Any) -> tuple[ClassificationJudge, _Classifier]:
    provider = _Classifier(content, **kw)
    playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
    return ClassificationJudge(playbook, provider), provider  # type: ignore[arg-type]


_REQUEST = json.dumps({"work_item_type": "service_request", "confidence": 0.58, "rationale": "x"})


class TestDecisionFile:
    def test_d2_is_the_answer_space_the_label_set_is_labelled_against(self) -> None:
        q = load_question(D2)
        assert (q.id, q.kind, q.version) == ("d2", "choice", ANSWER_SPACE["d2"])
        assert tuple(q.answers) == VALID_TYPES
        assert q.threshold is None  # measured from the label set, never guessed

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ("kind: verdict", "kind must be one of"),
            ("kind: noul\nanswers: {yes: a, maybe: b}", "answers yes or no"),
            ("kind: choice\nanswers: {only: a}", "at least two answers"),
            ("kind: choice\nanswers: {a: x, b: y}\nthreshold: 1.5", "between 0 and 1"),
        ],
    )
    def test_a_file_an_engine_could_not_be_asked_is_refused(
        self, tmp_path: Path, body: str, message: str
    ) -> None:
        path = tmp_path / "dx.yaml"
        path.write_text(f"id: dx\nversion: dx-v1\nquestion: q?\n{body}\n", encoding="utf-8")
        with pytest.raises(JudgmentError, match=message):
            load_question(path)


class TestClassificationJudge:
    def test_answers_decision_2_with_its_own_confidence_cost_and_latency(self) -> None:
        judge, provider = _baseline(_REQUEST)
        j = judge.judge(load_question(D2), "VPN access for a new starter", timeout_s=7.5)
        assert (j.question, j.version, j.answer, j.probability) == (
            "d2",
            "d2-v1",
            "service_request",
            0.58,
        )
        assert j.engine == "playbook:anthropic/claude-haiku-4-5-20251001"
        assert j.cost_usd == 0.00027  # kept from the call, not assumed
        assert j.latency_ms >= 0 and j.fallback is None
        [call] = provider.calls
        assert call["timeout_ms"] == 7500
        assert call["messages"][1].content == "VPN access for a new starter"

    def test_refuses_a_question_it_cannot_answer(self) -> None:
        judge, provider = _baseline(_REQUEST)
        security = Question("d1", "d1-v1", "noul", "Security?", {"yes": "", "no": ""}, None)
        with pytest.raises(JudgmentError, match="only incident or request"):
            judge.judge(security, "state", timeout_s=5)
        assert provider.calls == []


class _Down:
    name = "typesafe:jev-test"

    def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
        raise ProviderError("timed out after 2.0s")


class _Up:
    name = "typesafe:jev-test"

    def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
        return Judgment(question.id, question.version, "incident", 0.97, self.name, 120, 0.00001)


class TestFallback:
    def test_the_primary_decides_when_it_can(self) -> None:
        baseline, provider = _baseline(_REQUEST)
        j = judge_with_fallback(_Up(), baseline, load_question(D2), "s", timeout_s=2)
        assert (j.engine, j.answer, j.fallback) == ("typesafe:jev-test", "incident", None)
        assert provider.calls == []

    def test_a_failed_primary_hands_over_and_the_judgment_says_why(self) -> None:
        baseline, _ = _baseline(_REQUEST)
        j = judge_with_fallback(_Down(), baseline, load_question(D2), "s", timeout_s=2)
        assert j.engine == baseline.name and j.answer == "service_request"
        assert j.fallback == "typesafe:jev-test: timed out after 2.0s"
        assert j.as_trace()["fallback"] == j.fallback

    def test_when_both_fail_the_error_reaches_the_caller(self) -> None:
        baseline, _ = _baseline(error=ProviderError("anthropic down"))
        with pytest.raises(ProviderError, match="anthropic down"):
            judge_with_fallback(_Down(), baseline, load_question(D2), "s", timeout_s=2)

    def test_a_bug_is_not_quietly_handed_to_another_model(self) -> None:
        class Broken(_Up):
            def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
                raise KeyError("probabilities")

        baseline, provider = _baseline(_REQUEST)
        with pytest.raises(KeyError):
            judge_with_fallback(Broken(), baseline, load_question(D2), "s", timeout_s=2)
        assert provider.calls == []


# ── The stage: built at startup, and wired into the run (ADR-0040) ───────────


def _decisions(tmp_path: Path, threshold: str) -> Path:
    text = D2.read_text(encoding="utf-8").replace("threshold: null", f"threshold: {threshold}")
    (tmp_path / "d2.yaml").write_text(text, encoding="utf-8")
    return tmp_path


class TestBuildStage:
    def test_refuses_to_start_until_the_threshold_is_measured(self) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        with pytest.raises(ConfigError, match=r"no threshold\. Measure it on the label set"):
            build_stage(REPO_ROOT / DECISIONS_DIR, playbook, _Classifier(""), "ts-key")  # type: ignore[arg-type]

    def test_jev_decides_and_the_playbook_model_is_the_fallback(self, tmp_path: Path) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        stage = build_stage(_decisions(tmp_path, "0.82"), playbook, _Classifier(_REQUEST), "ts-key")  # type: ignore[arg-type]
        assert stage.threshold == 0.82
        assert isinstance(stage.primary, TypeSafeJudge)
        assert stage.primary.name == "typesafe:jev-latest"
        assert isinstance(stage.fallback, ClassificationJudge)

    def test_refuses_to_start_without_a_typesafe_key(self, tmp_path: Path) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        with pytest.raises(ConfigError, match="TYPESAFE_API_KEY"):
            build_stage(_decisions(tmp_path, "0.82"), playbook, _Classifier(""), None)  # type: ignore[arg-type]

    def test_with_a_fallback_the_stage_hands_over_on_failure(self) -> None:
        baseline, _ = _baseline(_REQUEST)
        stage = Stage(load_question(D2), 0.8, primary=_Down(), fallback=baseline)
        assert stage.decide(stage.work_item_type, "s").fallback == (
            "typesafe:jev-test: timed out after 2.0s"
        )


class _Engine:
    """Answers decision 2 as told, and keeps what it was shown."""

    name = "typesafe:jev-test"

    def __init__(self, answer: str, probability: float) -> None:
        self.answer, self.probability = answer, probability
        self.states: list[str] = []

    def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
        self.states.append(state)
        return Judgment(
            question.id, question.version, self.answer, self.probability, self.name, 140, 0.00002
        )


_UNTYPED = {
    "ticket_id": "TKT-9",
    "subject": "Need Jira access",
    "body": "Please add me to the Jira project. Reach me at jane.doe@example.com.",
}


def _app_with_stage(engine: _Engine) -> Any:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from unittest.mock import MagicMock

    from fastapi import FastAPI

    from opspilot.api.routes.run import router
    from opspilot.redaction import Redactor

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.playbook = MagicMock(name="incident_pb")
        app.state.request_fulfillment_pb = MagicMock(name="request_pb")
        app.state.chat_provider = MagicMock()
        app.state.session_mgr = MagicMock()
        app.state.redactor = Redactor.from_yaml()
        app.state.classify_pb = MagicMock()
        app.state.classify_threshold = 0.7
        app.state.judgments = Stage(load_question(D2), 0.8, primary=engine)
        app.state.sqlite = app.state.lance = app.state.mcp_registry = None
        app.state.embed_fn = lambda text: [0.0]
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(router, prefix="/api")
    return app


def _run_result() -> Any:
    from opspilot.orchestrator.types import RunResult, TokenUsage

    return RunResult(
        session_id="sess_J1",
        artifact_id="art_1",
        summary={"summary": "ok"},
        schema_valid=True,
        error=None,
        usage=TokenUsage(),
    )


class TestStageInTheRun:
    def test_above_the_threshold_the_judgment_picks_the_playbook_and_is_traced(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        engine = _Engine("service_request", 0.93)
        app = _app_with_stage(engine)
        with (
            patch("opspilot.api.routes.run.classify_work_item") as classify,
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()) as run,
            TestClient(app) as client,
        ):
            data = client.post("/api/run", json={"input": _UNTYPED}).json()

        classify.assert_not_called()  # the stage replaces Classification's call
        assert run.call_args.args[0].playbook is app.state.request_fulfillment_pb
        assert data["needs_confirmation"] is False
        assert data["classification"]["work_item_type"] == "service_request"
        assert data["classification"]["judgment"]["engine"] == "typesafe:jev-test"
        # Only the redacted text reaches an engine.
        [state] = engine.states
        assert "Need Jira access" in state and "jane.doe@example.com" not in state
        # The Judgment lands on the Session's trace.
        writes = app.state.session_mgr.trace.return_value.__enter__.return_value.write
        [event] = [c.args[0] for c in writes.call_args_list]
        assert event.payload["event"] == "judgment"
        assert event.payload["details"]["probability"] == 0.93
        app.state.session_mgr.trace.assert_called_with("sess_J1")

    def test_below_the_threshold_a_person_decides_and_nothing_runs(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        app = _app_with_stage(_Engine("incident", 0.61))
        with (
            patch("opspilot.api.routes.run.run_ticket_summary") as run,
            TestClient(app) as client,
        ):
            data = client.post("/api/run", json={"input": _UNTYPED}).json()

        run.assert_not_called()
        assert data["needs_confirmation"] is True and data["session_id"] == ""
        assert (data["classification"]["work_item_type"], data["classification"]["confidence"]) == (
            "incident",
            0.61,
        )

    def test_a_declared_type_skips_the_stage(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        engine = _Engine("service_request", 0.99)
        app = _app_with_stage(engine)
        declared = {**_UNTYPED, "work_item_type": "incident"}
        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()) as run,
            TestClient(app) as client,
        ):
            data = client.post("/api/run/stream", json={"input": declared})

        assert data.status_code == 200
        assert engine.states == []
        assert run.call_args.args[0].playbook is app.state.playbook
        app.state.session_mgr.trace.assert_not_called()


def test_the_trace_schema_accepts_a_judgment_event(tmp_path: Path) -> None:
    """The trace write is best-effort, so a schema that refused the event would
    lose it silently; this writes through the real, validating TraceWriter."""
    from types import SimpleNamespace

    from opspilot.api.routes.run import _trace_judgment
    from opspilot.session.manager import SessionManager
    from opspilot.session.types import Model, Playbook

    mgr = SessionManager(home=tmp_path)
    sess = mgr.create(
        owner="api:default",
        playbook=Playbook(id="pb_request_fulfillment_en", version="1.0.0"),
        model=Model(provider_id="anthropic", kind="anthropic", name="m", version="1", params={}),
    )
    j = Judgment("d2", "d2-v1", "service_request", 0.93, "typesafe:jev-test", 140, 0.00002)
    _trace_judgment(SimpleNamespace(session_mgr=mgr), sess.id, {"judgment": j.as_trace()})

    lines = (mgr.session_dir(sess.id) / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    [event] = [json.loads(line) for line in lines]
    assert event["type"] == "system" and event["event"] == "judgment"
    assert event["details"] == j.as_trace()
