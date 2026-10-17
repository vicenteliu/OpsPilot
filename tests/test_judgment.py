"""Judgments: the decision file, the baseline engine, and the fallback (ADR-0040)."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest

from opspilot.errors import ConfigError, ProviderError
from opspilot.judgment import (
    DECISIONS_DIR,
    ClassificationJudge,
    Decision,
    Judgment,
    JudgmentError,
    Question,
    QuestionJudge,
    Severity,
    Stage,
    TypeSafeJudge,
    build_stage,
    judge_with_fallback,
    load_question,
    load_severity_table,
)
from opspilot.label_set import ANSWER_SPACE
from opspilot.orchestrator.classify import VALID_TYPES
from opspilot.orchestrator.types import load_playbook
from opspilot.providers.types import ChatResponse, Usage

REPO_ROOT = Path(__file__).resolve().parents[1]
D2 = REPO_ROOT / DECISIONS_DIR / "d2.yaml"
D1 = REPO_ROOT / DECISIONS_DIR / "d1.yaml"
D7 = REPO_ROOT / DECISIONS_DIR / "d7.yaml"
D8 = REPO_ROOT / DECISIONS_DIR / "d8.yaml"
D6 = REPO_ROOT / DECISIONS_DIR / "d6.yaml"
D4 = REPO_ROOT / DECISIONS_DIR / "d4.yaml"
SEVERITY = REPO_ROOT / DECISIONS_DIR / "severity.yaml"


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
        # Measured on the label set (judgments/label_set/report_v1.md), never guessed,
        # and only for the engine it was measured on.
        assert q.thresholds == {
            "typesafe:jev-1.13.0": 0.94,
            "playbook:anthropic/claude-haiku-5-5": 0.70,
        }

    def test_d1_is_the_security_answer_space_the_label_set_is_labelled_against(self) -> None:
        q = load_question(REPO_ROOT / DECISIONS_DIR / "d1.yaml")
        assert (q.id, q.kind, q.version) == ("d1", "noul", ANSWER_SPACE["d1"])
        assert set(q.answers) == {"yes", "no"}  # quoted in the file, not YAML booleans
        assert "When in doubt about compromise or exposure, yes." in q.answers["yes"]
        assert "routine request" in q.answers["no"]  # d1-v2: routine asks are not security
        # Measured on the label set (judgments/label_set/report_d1_v2.md, #281), never guessed.
        assert q.thresholds == {
            "typesafe:jev-1.13.0": 0.10,
            "playbook:anthropic/claude-haiku-5-5": 0.30,
        }

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ("kind: verdict", "kind must be one of"),
            ("kind: noul\nanswers: {yes: a, maybe: b}", "answers yes or no"),
            ("kind: choice\nanswers: {only: a}", "at least two answers"),
            ("kind: choice\nanswers: {a: x, b: y}\nthresholds: {e: 1.5}", "between 0 and 1"),
            ("kind: choice\nanswers: {a: x, b: y}\nthresholds: [0.9]", "keyed by engine"),
            ("kind: choice\nanswers: {a: x, b: y}\nthreshold: 0.9", "now `thresholds`"),
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
        assert j.engine == "playbook:anthropic/claude-haiku-5-5"
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


# ── Jev, through the typesafe provider kind ─────────────────────────────────

_JEV_ANSWER = {
    "model": "jev-1.13.0",
    "answers": {
        "d2": {
            "type": "choice",
            "choice": "service_request",
            "probabilities": {"incident": 0.09, "service_request": 0.91},
            "confidence": 0.82,
        }
    },
    "usage": {"input_tokens": 312, "output_tokens": 20},
}


def _jev(handler: Callable[[httpx.Request], httpx.Response]) -> TypeSafeJudge:
    return TypeSafeJudge("ts-test-key", client=httpx.Client(transport=httpx.MockTransport(handler)))


class TestTypeSafeJudge:
    def test_asks_the_question_as_its_file_states_it_and_reads_the_answer(self) -> None:
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(200, json=_JEV_ANSWER)

        q = load_question(D2)
        j = _jev(handler).judge(q, "VPN access for a new starter", timeout_s=7.5)

        [request] = sent
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["Authorization"] == "Bearer ts-test-key"
        assert request.extensions["timeout"]["read"] == 7.5
        assert json.loads(request.content) == {
            "state": "VPN access for a new starter",
            "model": "jev-1.13.0",  # pinned: the threshold is measured on one version
            "questions": {"d2": {"type": "choice", "instructions": q.text, "criteria": q.answers}},
        }
        assert (j.question, j.version, j.answer, j.engine) == (
            "d2",
            "d2-v1",
            "service_request",
            "typesafe:jev-1.13.0",
        )
        # The chosen answer's probability, not `confidence` (2p − 1 for two answers).
        assert j.probability == 0.91
        assert j.cost_usd == pytest.approx(312 * 0.042 / 1_000_000)  # input tokens only
        assert j.latency_ms >= 0 and j.fallback is None

    @pytest.mark.parametrize(
        ("respond", "message"),
        [
            (httpx.ReadTimeout("slow"), r"timed out after 7\.5s"),
            (httpx.ConnectError("refused"), "unreachable"),
            (httpx.Response(429, text="slow down"), "HTTP 429: slow down"),
            (httpx.Response(200, json={"answers": {}}), "unexpected response"),
            (
                httpx.Response(
                    200,
                    json={
                        **_JEV_ANSWER,
                        "answers": {
                            # Named before its probability is looked for, so an
                            # answer with none is still reported as outside.
                            "d2": {"type": "choice", "choice": "task", "probabilities": {}}
                        },
                    },
                ),
                "'task', outside the answer space of d2-v1",
            ),
        ],
    )
    def test_every_failure_is_one_the_fallback_catches(
        self, respond: httpx.Response | Exception, message: str
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if isinstance(respond, Exception):
                raise respond
            return respond

        with pytest.raises(JudgmentError, match=message):
            _jev(handler).judge(load_question(D2), "s", timeout_s=7.5)

    @pytest.mark.parametrize(
        ("p_yes", "answer", "probability"), [(0.93, "yes", 0.93), (0.2, "no", 0.8)]
    )
    def test_asks_a_noul_with_its_meanings_as_criteria(
        self, p_yes: float, answer: str, probability: float
    ) -> None:
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            body = {
                "model": "jev-1.13.0",
                "answers": {"d1": {"type": "noul", "noul": p_yes}},
                "usage": {"input_tokens": 200, "output_tokens": 20},
            }
            return httpx.Response(200, json=body)

        q = load_question(D1)
        j = _jev(handler).judge(q, "Lost my laptop on the train", timeout_s=5)
        assert json.loads(sent[0].content)["questions"] == {
            "d1": {
                "type": "noul",
                "instructions": q.text,
                "criteria": {"true": q.answers["yes"], "false": q.answers["no"]},
            }
        }
        # The answer the probability leans to, and that answer's probability.
        assert (j.answer, j.probability) == pytest.approx((answer, probability))  # type: ignore[comparison-overlap]

    def test_impact_and_urgency_are_scores_whose_levels_rise_in_file_order(self) -> None:
        assert (load_question(D7).kind, list(load_question(D7).answers)) == (
            "score",
            ["single_user", "multiple_users", "site_wide"],
        )
        assert (load_question(D8).kind, list(load_question(D8).answers)) == (
            "score",
            ["worked_around", "slowed", "stopped"],
        )

    def test_asks_a_score_with_its_levels_in_order_and_takes_the_likeliest(self) -> None:
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            body = {
                "model": "jev-1.13.0",
                "answers": {
                    "d7": {
                        "type": "score",
                        "score": 0.9,  # probability-weighted: between two levels
                        "legend": {"0": "one", "1": "some", "2": "all"},
                        "probabilities": {"0": 0.3, "1": 0.5, "2": 0.2},
                        "confidence": 0.4,
                    }
                },
                "usage": {"input_tokens": 250, "output_tokens": 20},
            }
            return httpx.Response(200, json=body)

        q = load_question(D7)
        j = _jev(handler).judge(q, "The printer on floor 3 is jammed for everyone", timeout_s=5)
        assert json.loads(sent[0].content)["questions"] == {
            "d7": {"type": "score", "instructions": q.text, "criteria": list(q.answers.values())}
        }
        assert (j.answer, j.probability) == ("multiple_users", 0.5)

    def test_a_score_level_outside_the_answer_space_is_a_failure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            answer = {"type": "score", "score": 3.0, "probabilities": {"3": 1.0}}
            return httpx.Response(200, json={**_JEV_ANSWER, "answers": {"d7": answer}})

        with pytest.raises(JudgmentError, match="level 3, outside the answer space of d7-v1"):
            _jev(handler).judge(load_question(D7), "s", timeout_s=5)


# ── The Playbook's model, asked a Question in its file's words ──────────────


class TestQuestionJudge:
    def _judge(self, content: str, **kw: Any) -> tuple[QuestionJudge, _Classifier]:
        provider = _Classifier(content, **kw)
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        return QuestionJudge(playbook, provider), provider  # type: ignore[arg-type]

    def test_asks_the_question_and_its_answers_and_reads_the_json(self) -> None:
        judge, provider = self._judge('{"answer": "yes", "probability": 0.9}')
        q = load_question(D1)
        j = judge.judge(q, "Lost my laptop on the train", timeout_s=7.5)
        assert (j.question, j.version, j.answer, j.probability) == ("d1", q.version, "yes", 0.9)
        assert j.engine == judge.name and j.engine.startswith("playbook:")
        assert j.cost_usd == 0.00027  # what the call cost, kept
        [call] = provider.calls
        system, user = call["messages"]
        assert q.text in system.content and q.answers["yes"] in system.content
        assert user.content == "Lost my laptop on the train"
        assert call["timeout_ms"] == 7500

    @pytest.mark.parametrize(
        ("content", "message"),
        [
            ("not json", "unreadable answer"),
            ('{"answer": "maybe", "probability": 0.5}', "'maybe', outside the answer space"),
            ('{"answer": "yes", "probability": 1.4}', "probability must be between 0 and 1"),
            ('["yes", 0.9]', "unreadable answer"),
        ],
    )
    def test_an_answer_it_cannot_use_is_an_engine_failure(self, content: str, message: str) -> None:
        judge, _ = self._judge(content)
        with pytest.raises(JudgmentError, match=message):
            judge.judge(load_question(D1), "s", timeout_s=5)


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

    def test_a_failed_primary_hands_over_and_the_judgment_and_the_log_say_why(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        baseline, _ = _baseline(_REQUEST)
        with caplog.at_level(logging.WARNING, logger="opspilot.judgment"):
            j = judge_with_fallback(_Down(), baseline, load_question(D2), "s", timeout_s=2)
        assert j.engine == baseline.name and j.answer == "service_request"
        assert j.fallback == "typesafe:jev-test: timed out after 2.0s"
        assert j.as_trace()["fallback"] == j.fallback
        # A run that waits for a person has no Session, so the log is the record.
        assert "typesafe:jev-test could not decide d2" in caplog.text
        assert "timed out after 2.0s" in caplog.text

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


JEV = "typesafe:jev-1.13.0"
PLAYBOOK = "playbook:anthropic/claude-haiku-5-5"
_MEASURED = {JEV: 0.07, PLAYBOOK: 0.07}


def _with_thresholds(src: Path, dest: Path, thresholds: dict[str, float]) -> None:
    """A decision file as committed, with its thresholds replaced."""
    text = src.read_text(encoding="utf-8")
    head = text[: re.search(r"^thresholds?:", text, flags=re.M).start()]  # type: ignore[union-attr]
    body = "".join(f'  "{engine}": {cut}\n' for engine, cut in thresholds.items())
    dest.write_text(
        head + ("thresholds:\n" + body if thresholds else "thresholds: {}\n"), encoding="utf-8"
    )


def _incident_decision_files(tmp_path: Path) -> None:
    """The decisions after d1 and d2, their tables and the catalog, as committed."""
    for name in (
        "d3.yaml",
        "d4.yaml",
        "d6.yaml",
        "d7.yaml",
        "d8.yaml",
        "severity.yaml",
        "r1.yaml",
        "r2.yaml",
        "r3.yaml",
        "d9.yaml",
        "catalog.yaml",
    ):
        (tmp_path / name).write_text((D2.parent / name).read_text(encoding="utf-8"))


def _decisions(
    tmp_path: Path, thresholds: dict[str, float], security: dict[str, float] | None = None
) -> Path:
    """d2.yaml with ``thresholds`` and d1.yaml with ``security`` (both engines measured by default)."""
    _with_thresholds(D2, tmp_path / "d2.yaml", thresholds)
    _with_thresholds(D1, tmp_path / "d1.yaml", _MEASURED if security is None else security)
    _incident_decision_files(tmp_path)
    return tmp_path


class TestBuildStage:
    def test_refuses_to_start_until_a_threshold_is_measured(self, tmp_path: Path) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        with pytest.raises(
            ConfigError, match=rf"d2\.yaml has no threshold for {PLAYBOOK}\. Measure"
        ):
            build_stage(_decisions(tmp_path, {}), playbook, _Classifier(""))  # type: ignore[arg-type]

    def test_refuses_to_start_until_decision_1_is_measured(self, tmp_path: Path) -> None:
        """#301: like decision 2's; a security issue unstopped is the mistake not undone."""
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        with pytest.raises(
            ConfigError, match=rf"d1\.yaml has no threshold for {PLAYBOOK}\. Measure"
        ):
            build_stage(_decisions(tmp_path, _MEASURED, security={}), playbook, _Classifier(""))  # type: ignore[arg-type]

    def test_the_committed_files_run_decision_1_first_at_its_own_cut(self) -> None:
        """#281: d1 is measured for the Playbook's model, which decides without a Jev key."""
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        stage = build_stage(REPO_ROOT / DECISIONS_DIR, playbook, _Classifier(_REQUEST))  # type: ignore[arg-type]
        assert (stage.security.primary.name, stage.security.threshold) == (PLAYBOOK, 0.30)
        assert stage.work_item_type.threshold == 0.70

    def test_with_decision_1_measured_the_committed_d2_runs_the_playbook_model_at_its_cut(
        self, tmp_path: Path
    ) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        (tmp_path / "d2.yaml").write_text(D2.read_text(encoding="utf-8"), encoding="utf-8")
        _with_thresholds(D1, tmp_path / "d1.yaml", _MEASURED)
        _incident_decision_files(tmp_path)
        stage = build_stage(tmp_path, playbook, _Classifier(_REQUEST))  # type: ignore[arg-type]
        assert stage.work_item_type.primary.name == PLAYBOOK
        assert stage.work_item_type.threshold == 0.70

    def test_without_a_key_jev_s_threshold_is_not_lent_to_the_playbook_model(
        self, tmp_path: Path
    ) -> None:
        """#274: a cut measured on Jev's probability says nothing about another engine's."""
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        with pytest.raises(ConfigError, match=rf"no threshold for {PLAYBOOK}"):
            build_stage(_decisions(tmp_path, {JEV: 0.94}), playbook, _Classifier(_REQUEST))  # type: ignore[arg-type]

    def test_with_a_key_the_playbook_model_s_threshold_is_not_lent_to_jev(
        self, tmp_path: Path
    ) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        with pytest.raises(ConfigError, match=rf"no threshold for {JEV}"):
            build_stage(
                _decisions(tmp_path, {PLAYBOOK: 0.75}),
                playbook,
                _Classifier(_REQUEST),  # type: ignore[arg-type]
                typesafe_api_key="ts-test-key",
            )

    def test_decision_1_s_cut_for_jev_is_not_lent_to_the_playbook_model(
        self, tmp_path: Path
    ) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        with pytest.raises(ConfigError, match=rf"d1\.yaml has no threshold for {PLAYBOOK}"):
            build_stage(
                _decisions(tmp_path, {JEV: 0.94, PLAYBOOK: 0.7}, security={JEV: 0.07}),
                playbook,
                _Classifier(""),  # type: ignore[arg-type]
            )

    def test_without_a_typesafe_key_the_playbook_model_decides_alone_and_the_log_says_so(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        with caplog.at_level(logging.WARNING, logger="opspilot.judgment"):
            stage = build_stage(
                _decisions(tmp_path, {JEV: 0.94, PLAYBOOK: 0.82}),
                playbook,
                _Classifier(_REQUEST),  # type: ignore[arg-type]
            )
        d2 = stage.work_item_type
        assert d2.threshold == 0.82 and d2.fallback is None
        assert isinstance(d2.primary, ClassificationJudge)
        assert stage.security.threshold == 0.07 and stage.security.fallback is None
        assert isinstance(stage.security.primary, QuestionJudge)
        assert "without TYPESAFE_API_KEY" in caplog.text
        j = d2.decide("state")
        assert (j.answer, j.probability, j.fallback) == ("service_request", 0.58, None)

    def test_with_a_typesafe_key_jev_decides_and_the_playbook_model_falls_back(
        self, tmp_path: Path
    ) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        stage = build_stage(
            _decisions(tmp_path, {JEV: 0.94, PLAYBOOK: 0.82}),
            playbook,
            _Classifier(_REQUEST),  # type: ignore[arg-type]
            typesafe_api_key=" ts-test-key\n",  # as a key file pastes it
        )
        assert stage.work_item_type.threshold == 0.94  # Jev's own, not the fallback's
        assert stage.security.threshold == 0.07
        for decision, baseline in (
            (stage.work_item_type, ClassificationJudge),
            (stage.security, QuestionJudge),
        ):
            assert isinstance(decision.primary, TypeSafeJudge)
            assert decision.primary.name == JEV
            assert isinstance(decision.fallback, baseline)

    @pytest.mark.parametrize("key", ["ts test key", "ts-test-’key", "ts-\x00-key"])
    def test_a_malformed_typesafe_key_stops_the_start(self, tmp_path: Path, key: str) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        with pytest.raises(ConfigError, match="TYPESAFE_API_KEY is malformed"):
            build_stage(
                _decisions(tmp_path, {JEV: 0.94}),
                playbook,
                _Classifier(_REQUEST),  # type: ignore[arg-type]
                typesafe_api_key=key,
            )

    def test_with_a_fallback_a_decision_hands_over_on_failure(self) -> None:
        baseline, _ = _baseline(_REQUEST)
        decision = Decision(load_question(D2), 0.8, primary=_Down(), fallback=baseline)
        assert decision.decide("s").fallback == "typesafe:jev-test: timed out after 2.0s"


def _stage(threshold: float = 0.8, security_threshold: float = 0.1) -> Stage:
    return Stage(
        security=Decision(load_question(D1), security_threshold, primary=_Up()),
        work_item_type=Decision(load_question(D2), threshold, primary=_Up()),
    )


class TestNeedsAPerson:
    def _judgment(self, probability: float, fallback: str | None = None) -> Judgment:
        return Judgment("d2", "d2-v1", "incident", probability, "e", 1, 0.0, fallback)

    def test_at_or_above_the_threshold_the_primary_s_answer_routes(self) -> None:
        assert not _stage().needs_a_person(self._judgment(0.8))

    def test_below_the_threshold_a_person_picks(self) -> None:
        assert _stage().needs_a_person(self._judgment(0.79))

    def test_a_fallback_s_answer_goes_to_a_person_however_sure_it_is(self) -> None:
        # The threshold was measured on the primary's probability, not the fallback's.
        assert _stage().needs_a_person(self._judgment(0.99, fallback="typesafe:jev: HTTP 529"))


class TestStopsForSecurity:
    def _says(self, answer: str, probability: float, fallback: str | None = None) -> Judgment:
        return Judgment("d1", "d1-v1", answer, probability, "e", 1, 0.0, fallback)

    def test_stops_at_or_above_the_threshold_on_the_probability_of_yes(self) -> None:
        stage = _stage(security_threshold=0.1)
        assert stage.stops_for_security(self._says("yes", 0.6))
        assert stage.stops_for_security(self._says("no", 0.9))  # P(yes) 0.1, on the cut
        assert not stage.stops_for_security(self._says("no", 0.95))  # P(yes) 0.05

    def test_a_fallback_s_answer_stops_however_sure_it_is_of_no(self) -> None:
        # The one mistake the next step cannot undo is a wrong "not security".
        assert _stage().stops_for_security(
            self._says("no", 0.99, fallback="typesafe:jev: HTTP 529")
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


def _app_with_stage(
    engine: _Engine | _Down,
    fallback: _Engine | None = None,
    *,
    security: _Engine | _Down | None = None,
    security_fallback: _Engine | None = None,
    severity: Severity | None = None,
    team: Decision | None = None,
    enough: Decision | None = None,
    ask_provider: Any = None,
    already_open: Decision | None = None,
    catalog: Any = None,
    really: Decision | None = None,
    fulfil: Decision | None = None,
) -> Any:
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
        app.state.judgments = Stage(
            security=Decision(
                load_question(D1),
                0.1,
                primary=security or _Engine("no", 0.97),
                fallback=security_fallback,
            ),
            work_item_type=Decision(load_question(D2), 0.8, primary=engine, fallback=fallback),
            severity=severity,
            team=team,
            enough=enough,
            already_open=already_open,
            catalog=catalog,
            really=really,
            fulfil=fulfil,
        )
        app.state.inventory = MagicMock()
        app.state.inventory.list.return_value = [
            {"category": "Laptop", "status": "in_stock"},
            {"category": "laptop", "status": "in_stock"},
            {"category": "monitor", "status": "in_stock"},
        ]
        app.state.ask_pb = load_playbook(REPO_ROOT / "playbooks" / "pb_ask_en")
        app.state.ask_provider = ask_provider or _Classifier(_ASK)
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
        assert data["security"]["question"] == "d1" and data["security"]["stops"] is False
        # Both Judgments land on the Session's trace, security first.
        writes = app.state.session_mgr.trace.return_value.__enter__.return_value.write
        events = [c.args[0].payload for c in writes.call_args_list]
        assert [e["event"] for e in events] == ["judgment", "judgment"]
        assert [e["details"]["question"] for e in events] == ["d1", "d2"]
        assert events[1]["details"]["probability"] == 0.93
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

    def test_a_fallback_s_answer_waits_for_a_person_and_says_why(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        app = _app_with_stage(_Down(), fallback=_Engine("service_request", 0.99))
        with (
            patch("opspilot.api.routes.run.run_ticket_summary") as run,
            TestClient(app) as client,
        ):
            data = client.post("/api/run", json={"input": _UNTYPED}).json()

        run.assert_not_called()
        assert data["needs_confirmation"] is True
        # The fallback's answer still preselects the person's pick.
        assert data["classification"]["work_item_type"] == "service_request"
        assert data["classification"]["judgment"]["fallback"] == (
            "typesafe:jev-test: timed out after 2.0s"
        )

    def test_a_declared_type_skips_decision_2_and_not_decision_1(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        engine, security = _Engine("service_request", 0.99), _Engine("no", 0.97)
        app = _app_with_stage(engine, security=security)
        declared = {**_UNTYPED, "work_item_type": "incident"}
        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()) as run,
            TestClient(app) as client,
        ):
            data = client.post("/api/run/stream", json={"input": declared})

        assert data.status_code == 200
        assert engine.states == [] and len(security.states) == 1
        assert run.call_args.args[0].playbook is app.state.playbook

    @pytest.mark.parametrize(
        "extra",
        [{}, {"work_item_type": "service_request"}, {"playbook_id": "pb_request_fulfillment_en"}],
        ids=["untyped", "declared type", "explicit playbook"],
    )
    @pytest.mark.parametrize("path", ["/api/run", "/api/run/stream"])
    def test_a_security_yes_stops_the_run_whatever_was_declared(
        self, extra: dict[str, str], path: str
    ) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        engine = _Engine("service_request", 0.99)
        app = _app_with_stage(engine, security=_Engine("yes", 0.62))
        body: dict[str, Any] = {"input": {**_UNTYPED, **extra}}
        if "playbook_id" in extra:
            body = {"input": _UNTYPED, "playbook_id": extra["playbook_id"]}
        with (
            patch("opspilot.api.routes.run.classify_work_item") as classify,
            patch("opspilot.api.routes.run.run_ticket_summary") as run,
            TestClient(app) as client,
        ):
            res = client.post(path, json=body)
        data = res.json() if path == "/api/run" else _stream_result(res.text)

        run.assert_not_called()
        classify.assert_not_called()
        assert engine.states == []  # nothing after decision 1 is asked
        assert data["needs_confirmation"] is True and data["session_id"] == ""
        assert data["classification"] is None
        assert data["security"]["stops"] is True and data["security"]["answer"] == "yes"
        assert data["security"]["p_yes"] == 0.62  # the value the stage cut on

    def test_when_jev_cannot_answer_security_the_run_stops_for_a_person(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        app = _app_with_stage(
            _Engine("service_request", 0.99),
            security=_Down(),
            security_fallback=_Engine("no", 0.99),
        )
        with (
            patch("opspilot.api.routes.run.run_ticket_summary") as run,
            TestClient(app) as client,
        ):
            data = client.post("/api/run", json={"input": _UNTYPED}).json()

        run.assert_not_called()
        assert data["security"]["stops"] is True
        assert data["security"]["fallback"] == "typesafe:jev-test: timed out after 2.0s"

    def test_when_no_engine_can_answer_security_the_run_stops_rather_than_fails(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        class _AlsoDown(_Down):
            name = "playbook:test"

        app = _app_with_stage(
            _Engine("service_request", 0.99),
            security=_Down(),
            security_fallback=_AlsoDown(),  # type: ignore[arg-type]
        )
        with (
            patch("opspilot.api.routes.run.run_ticket_summary") as run,
            TestClient(app) as client,
        ):
            res = client.post("/api/run", json={"input": _UNTYPED})

        assert res.status_code == 200
        run.assert_not_called()
        data = res.json()
        assert data["needs_confirmation"] is True
        assert data["security"]["stops"] is True and data["security"]["answer"] is None
        assert data["security"]["fallback"].startswith("no engine could answer")

    def test_the_work_item_is_rendered_once_for_both_decisions(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from opspilot.api.routes.run import render_state

        app = _app_with_stage(_Engine("service_request", 0.93))
        with (
            patch("opspilot.api.routes.run.render_state", wraps=render_state) as rendered,
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()),
            TestClient(app) as client,
        ):
            client.post("/api/run", json={"input": _UNTYPED})
        assert rendered.call_count == 1


def _stream_result(text: str) -> dict[str, Any]:
    """The `result` event's payload from an SSE body."""
    for block in text.split("\n\n"):
        if "event: result" in block or '"type": "result"' in block:
            data = next(line[5:].strip() for line in block.splitlines() if line.startswith("data:"))
            payload = json.loads(data)
            return dict(payload.get("data", payload))
    raise AssertionError(f"no result event in {text!r}")


# ── Severity: Impact × Urgency read off a table (#227) ─────────────────────


class _Says:
    """Answers each question from a table keyed by its id, and counts what it was asked."""

    name = "typesafe:jev-test"

    def __init__(self, answers: dict[str, tuple[str, float]]) -> None:
        self.answers, self.asked = answers, []

    def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
        self.asked.append(question.id)
        answer, probability = self.answers[question.id]
        return Judgment(question.id, question.version, answer, probability, self.name, 90, 2e-05)


def _severity(engine: Any, fallback: Any = None) -> Severity:
    impact, urgency = load_question(D7), load_question(D8)
    return Severity(
        Decision(impact, 0.7, primary=engine, fallback=fallback),
        Decision(urgency, 0.93, primary=engine, fallback=fallback),
        load_severity_table(SEVERITY, impact, urgency),
    )


_SURE = {"d7": ("multiple_users", 0.9), "d8": ("stopped", 0.95)}


class TestSeverity:
    def test_the_committed_table_gives_every_pair_a_severity(self) -> None:
        table = load_severity_table(SEVERITY, load_question(D7), load_question(D8))
        assert len(table.cells) == 9
        assert table.read("single_user", "worked_around") == "P4"
        assert table.read("multiple_users", "stopped") == "P1"
        assert table.read("site_wide", "stopped") == "P0"

    @pytest.mark.parametrize(
        ("old", "new", "message"),
        [
            ("    stopped: P0", "    stopped: P5", "site_wide × stopped must be one of P0–P4"),
            ("    slowed: P1\n", "", "site_wide needs a value for each urgency"),
            ("  site_wide:", "  everyone:", "a row for each impact"),
        ],
    )
    def test_a_table_that_misses_a_pair_or_a_level_is_refused(
        self, tmp_path: Path, old: str, new: str, message: str
    ) -> None:
        path = tmp_path / "severity.yaml"
        path.write_text(SEVERITY.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
        with pytest.raises(JudgmentError, match=message):
            load_severity_table(path, load_question(D7), load_question(D8))

    def test_both_judgments_at_their_cuts_read_severity_off_the_table(self) -> None:
        severity, judged = _severity(_Says(_SURE)).decide("s")
        assert severity == "P1"
        assert [(j.question, j.answer) for j in judged] == [
            ("d7", "multiple_users"),
            ("d8", "stopped"),
        ]

    def test_below_either_cut_the_table_is_not_read(self) -> None:
        unsure = {**_SURE, "d8": ("stopped", 0.92)}
        severity, judged = _severity(_Says(unsure)).decide("s")
        assert severity is None and [j.question for j in judged] == ["d7", "d8"]

    def test_a_fallback_s_answer_is_not_read_off_the_table_however_sure(self) -> None:
        severity, judged = _severity(_Down(), fallback=_Says(_SURE)).decide("s")
        assert severity is None and all(j.fallback for j in judged)

    def test_the_committed_files_read_severity_at_the_playbook_model_s_cuts(self) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        stage = build_stage(REPO_ROOT / DECISIONS_DIR, playbook, _Classifier(_REQUEST))  # type: ignore[arg-type]
        assert stage.severity is not None
        assert (stage.severity.impact.threshold, stage.severity.urgency.threshold) == (0.45, 0.70)
        assert stage.severity.impact.primary.name == PLAYBOOK

    def test_unmeasured_the_stage_runs_without_severity_and_says_so(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        decisions = _decisions(tmp_path, {JEV: 0.94, PLAYBOOK: 0.7})
        _with_thresholds(D8, tmp_path / "d8.yaml", {JEV: 0.93})
        with caplog.at_level(logging.WARNING, logger="opspilot.judgment"):
            stage = build_stage(decisions, playbook, _Classifier(""))  # type: ignore[arg-type]
        assert stage.severity is None
        assert "runs WITHOUT Severity" in caplog.text and "d8.yaml" in caplog.text


_INCIDENT = {**_UNTYPED, "work_item_type": "incident"}


def _events(app: Any) -> list[dict[str, Any]]:
    writes = app.state.session_mgr.trace.return_value.__enter__.return_value.write
    return [c.args[0].payload for c in writes.call_args_list]


class TestSeverityInTheRun:
    @pytest.mark.parametrize("path", ["/api/run", "/api/run/stream"])
    def test_an_incident_s_summary_is_given_the_severity_its_judgments_read(
        self, path: str
    ) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        app = _app_with_stage(_Engine("incident", 0.99), severity=_severity(_Says(_SURE)))
        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()) as run,
            TestClient(app) as client,
        ):
            app.state.playbook.output_schema = "incident_summary_v1"
            assert client.post(path, json={"input": _INCIDENT}).status_code == 200

        assert run.call_args.kwargs["decided"] == {"severity_suggested": "P1"}
        events = _events(app)
        assert [e["details"]["question"] for e in events] == ["d1", "d7", "d8"]
        assert events[2]["details"]["severity"] == "P1"

    def test_below_a_cut_the_summary_suggests_its_own_and_both_are_traced(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        unsure = _Says({**_SURE, "d8": ("slowed", 0.5)})
        app = _app_with_stage(_Engine("incident", 0.99), severity=_severity(unsure))
        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()) as run,
            TestClient(app) as client,
        ):
            app.state.playbook.output_schema = "incident_summary_v1"
            client.post("/api/run", json={"input": _INCIDENT})

        assert run.call_args.kwargs["decided"] is None
        events = _events(app)
        assert [e["details"]["question"] for e in events] == ["d1", "d7", "d8"]
        assert events[1]["details"]["severity"] is None

    def test_a_request_s_playbook_is_not_asked_impact_or_urgency(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        says = _Says(_SURE)
        app = _app_with_stage(_Engine("incident", 0.99), severity=_severity(says))
        request = {**_UNTYPED, "work_item_type": "service_request"}
        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()) as run,
            TestClient(app) as client,
        ):
            app.state.request_fulfillment_pb.output_schema = "request_fulfillment_v1"
            client.post("/api/run", json={"input": request})

        assert says.asked == [] and run.call_args.kwargs["decided"] is None

    def test_when_no_engine_can_answer_the_summary_suggests_and_the_run_goes_on(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        app = _app_with_stage(_Engine("incident", 0.99), severity=_severity(_Down()))
        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()) as run,
            TestClient(app) as client,
        ):
            app.state.playbook.output_schema = "incident_summary_v1"
            data = client.post("/api/run", json={"input": _INCIDENT}).json()

        assert data["session_id"] == "sess_J1" and run.call_args.kwargs["decided"] is None


# ── Decision 6: the team an Incident escalates to (#228) ────────────────────


def _team(engine: Any, fallback: Any = None) -> Decision:
    return Decision(load_question(D6), 0.8, primary=engine, fallback=fallback)


def _escalation(team: Decision, severity: Severity | None = None) -> tuple[Any, Any]:
    """Run an Incident with the stage on; return the summary's run call and the trace events."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    app = _app_with_stage(_Engine("incident", 0.99), severity=severity, team=team)
    with (
        patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()) as run,
        TestClient(app) as client,
    ):
        app.state.playbook.output_schema = "incident_summary_v1"
        assert client.post("/api/run", json={"input": _INCIDENT}).status_code == 200
    return run, _events(app)


class TestTeam:
    def test_measured_the_stage_asks_it_at_its_engine_s_cut(self, tmp_path: Path) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        decisions = _decisions(tmp_path, {JEV: 0.94, PLAYBOOK: 0.7})
        _with_thresholds(D6, tmp_path / "d6.yaml", {PLAYBOOK: 0.8})
        stage = build_stage(decisions, playbook, _Classifier(""))  # type: ignore[arg-type]
        assert stage.team is not None and stage.team.threshold == 0.8
        assert stage.team.primary.name == PLAYBOOK

    def test_unmeasured_the_stage_runs_without_decision_6_and_says_so(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        decisions = _decisions(tmp_path, {JEV: 0.94, PLAYBOOK: 0.7})
        _with_thresholds(D6, tmp_path / "d6.yaml", {})
        with caplog.at_level(logging.WARNING, logger="opspilot.judgment"):
            stage = build_stage(decisions, playbook, _Classifier(""))  # type: ignore[arg-type]
        assert stage.team is None and "runs WITHOUT decision 6" in caplog.text

    def test_a_team_that_stands_is_the_escalation_hint(self) -> None:
        run, events = _escalation(_team(_Says({"d6": ("network", 0.9)})))
        assert run.call_args.kwargs["decided"] == {"escalation_hint": "network"}
        assert [e["details"]["question"] for e in events] == ["d1", "d6"]
        assert events[1]["details"]["escalation_hint"] == "network"

    def test_below_its_cut_the_hint_says_a_person_picks(self) -> None:
        run, _ = _escalation(_team(_Says({"d6": ("network", 0.62)})))
        assert run.call_args.kwargs["decided"] == {
            "escalation_hint": "A person picks the team: network at 0.62 is below its cut."
        }

    def test_a_fallback_s_team_is_not_trusted_however_sure(self) -> None:
        run, events = _escalation(_team(_Down(), fallback=_Says({"d6": ("systems", 0.99)})))
        hint = "A person picks the team: systems came from the fallback engine."
        assert run.call_args.kwargs["decided"] == {"escalation_hint": hint}
        assert events[1]["details"]["fallback"]

    def test_with_no_engine_to_answer_a_person_picks_and_the_run_goes_on(self) -> None:
        run, events = _escalation(_team(_Down()))
        assert run.call_args.kwargs["decided"] == {
            "escalation_hint": "A person picks the team: no engine could answer."
        }
        assert [e["details"]["question"] for e in events] == ["d1", "d6"]
        assert events[1]["details"]["answer"] is None
        assert "no engine could answer" in events[1]["details"]["fallback"]

    def test_severity_and_team_are_given_together(self) -> None:
        says = _Says({**_SURE, "d6": ("systems", 0.95)})
        run, events = _escalation(_team(says), severity=_severity(says))
        assert run.call_args.kwargs["decided"] == {
            "severity_suggested": "P1",
            "escalation_hint": "systems",
        }
        assert [e["details"]["question"] for e in events] == ["d1", "d7", "d8", "d6"]


# ── Decisions 4 and 5: enough to act on, and the ask (#229) ─────────────────

_ASK = json.dumps({"ask": "Since when has it failed, and what does the screen say?"})


def _enough(engine: Any, fallback: Any = None) -> Decision:
    return Decision(load_question(D4), 0.64, primary=engine, fallback=fallback)


def _post(app: Any, body: dict[str, Any], path: str = "/api/run") -> tuple[Any, Any]:
    """Post an Incident with the stage on; return the summary's run mock and the response."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    with (
        patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()) as run,
        TestClient(app) as client,
    ):
        app.state.playbook.output_schema = "incident_summary_v1"
        response = client.post(path, json=body)
    return run, response


def test_write_ask_returns_the_message_and_what_it_cost() -> None:
    from opspilot.orchestrator.ask import write_ask

    provider = _Classifier(_ASK)
    playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_ask_en")
    ask = write_ask("Printer broken", playbook=playbook, provider=provider)  # type: ignore[arg-type]
    assert ask.text == "Since when has it failed, and what does the screen say?"
    assert ask.usage.cost_usd == 0.00027
    [call] = provider.calls
    assert call["messages"][0].content == playbook.system_prompt


@pytest.mark.parametrize("content", ["not json", '{"ask": ""}', '{"answer": "x"}'])
def test_write_ask_refuses_anything_but_one_message(content: str) -> None:
    from opspilot.errors import OpsPilotError
    from opspilot.orchestrator.ask import write_ask

    playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_ask_en")
    with pytest.raises(OpsPilotError):
        write_ask("Printer broken", playbook=playbook, provider=_Classifier(content))  # type: ignore[arg-type]


class TestEnoughAndTheAsk:
    def test_a_no_that_stands_asks_the_reporter_and_runs_no_summary(self) -> None:
        provider = _Classifier(_ASK)
        app = _app_with_stage(
            _Engine("incident", 0.99),
            enough=_enough(_Says({"d4": ("no", 0.9)})),
            ask_provider=provider,
        )
        run, response = _post(app, {"input": _INCIDENT})
        data = response.json()
        run.assert_not_called()
        assert data["needs_confirmation"] is True and data["session_id"] == ""
        assert data["ask"]["text"] == "Since when has it failed, and what does the screen say?"
        assert (data["ask"]["question"], data["ask"]["answer"]) == ("d4", "no")
        # The ask writer sees the redacted Work item, as every Judgment does.
        [call] = provider.calls
        assert "Need Jira access" in call["messages"][1].content
        assert "jane.doe@example.com" not in call["messages"][1].content

    def test_the_stream_carries_the_ask_too(self) -> None:
        app = _app_with_stage(_Engine("incident", 0.99), enough=_enough(_Says({"d4": ("no", 0.9)})))
        run, response = _post(app, {"input": _INCIDENT}, "/api/run/stream")
        run.assert_not_called()
        assert '"ask": {' in response.text and "what does the screen say" in response.text

    @pytest.mark.parametrize(
        ("answer", "why"),
        [(("yes", 0.95), "enough"), (("no", 0.6), "a no below its cut")],
    )
    def test_otherwise_the_summary_runs_and_decision_4_is_traced(
        self, answer: tuple[str, float], why: str
    ) -> None:
        app = _app_with_stage(_Engine("incident", 0.99), enough=_enough(_Says({"d4": answer})))
        run, response = _post(app, {"input": _INCIDENT})
        assert response.json()["ask"] is None, why
        run.assert_called_once()
        assert [e["details"]["question"] for e in _events(app)] == ["d1", "d4"]

    def test_a_fallback_s_no_runs_the_summary_however_sure(self) -> None:
        app = _app_with_stage(
            _Engine("incident", 0.99),
            enough=_enough(_Down(), fallback=_Says({"d4": ("no", 0.99)})),
        )
        run, response = _post(app, {"input": _INCIDENT})
        assert response.json()["ask"] is None
        run.assert_called_once()

    def test_a_reporter_asked_once_is_not_asked_again(self) -> None:
        says = _Says({"d4": ("no", 0.99)})
        app = _app_with_stage(_Engine("incident", 0.99), enough=_enough(says))
        run, response = _post(app, {"input": _INCIDENT, "asked": True})
        assert says.asked == [] and response.json()["ask"] is None
        run.assert_called_once()

    def test_when_no_ask_can_be_written_the_summary_runs(self) -> None:
        app = _app_with_stage(
            _Engine("incident", 0.99),
            enough=_enough(_Says({"d4": ("no", 0.9)})),
            ask_provider=_Classifier("not json"),
        )
        run, response = _post(app, {"input": _INCIDENT})
        assert response.json()["ask"] is None
        run.assert_called_once()

    def test_a_request_is_not_asked_whether_it_is_enough(self) -> None:
        says = _Says({"d4": ("no", 0.99)})
        app = _app_with_stage(_Engine("incident", 0.99), enough=_enough(says))
        request = {**_UNTYPED, "work_item_type": "service_request"}
        run, _ = _post(app, {"input": request})
        assert says.asked == []
        run.assert_called_once()

    def test_measured_the_stage_asks_it_and_unmeasured_says_so(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        playbook = load_playbook(REPO_ROOT / "playbooks" / "pb_classify_work_item_en")
        decisions = _decisions(tmp_path, {JEV: 0.94, PLAYBOOK: 0.7})
        stage = build_stage(decisions, playbook, _Classifier(""))  # type: ignore[arg-type]
        assert stage.enough is not None and stage.enough.threshold == 0.77
        _with_thresholds(D4, tmp_path / "d4.yaml", {})
        with caplog.at_level(logging.WARNING, logger="opspilot.judgment"):
            stage = build_stage(decisions, playbook, _Classifier(""))  # type: ignore[arg-type]
        assert stage.enough is None and "runs WITHOUT decision 4" in caplog.text


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
    _trace_judgment(SimpleNamespace(session_mgr=mgr), sess.id, j.as_trace())

    lines = (mgr.session_dir(sess.id) / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    [event] = [json.loads(line) for line in lines]
    assert event["type"] == "system" and event["event"] == "judgment"
    assert event["details"] == j.as_trace()


# ── Decision 3: a Choice over the open Work items found for it (#230) ────────


def test_d3_is_a_choice_whose_open_items_come_first_and_none_last() -> None:
    from opspilot.judgment import with_candidates

    d3 = load_question(REPO_ROOT / DECISIONS_DIR / "d3.yaml")
    assert (d3.kind, list(d3.answers)) == ("choice", ["none"])
    asked = with_candidates(d3, {"IT-1": "VPN down for the floor", "IT-2": "printer jam"})
    assert list(asked.answers) == ["IT-1", "IT-2", "none"]
    assert (
        asked.answers["IT-1"] == "The same problem as this open Work item: VPN down for the floor"
    )
    assert asked.answers["none"] == d3.answers["none"] and asked.version == d3.version


def test_with_candidates_refuses_a_key_named_like_an_answer_and_a_question_without() -> None:
    from opspilot.judgment import with_candidates

    d3 = load_question(REPO_ROOT / DECISIONS_DIR / "d3.yaml")
    with pytest.raises(JudgmentError, match="named like an answer"):
        with_candidates(d3, {"none": "x"})
    with pytest.raises(JudgmentError, match="takes no candidates"):
        with_candidates(load_question(D2), {"IT-1": "x"})


def test_only_a_choice_has_candidates(tmp_path: Path) -> None:
    path = tmp_path / "d9.yaml"
    path.write_text(
        "id: d9\nversion: d9-x\nkind: noul\nquestion: q\ncandidates: 'x {text}'\n"
        'answers:\n  "yes": a\n  "no": b\n',
        encoding="utf-8",
    )
    with pytest.raises(JudgmentError, match="only a choice has candidates"):
        load_question(path)


_OPEN = [
    {
        "key": "IT-7",
        "subject": "Printer on 3 jammed",
        "body": "Paper jam, mail me at a@example.com",
    },
    {"key": "IT-8", "subject": "VPN slow", "body": "since 9"},
]


def _already_open(engine: Any, fallback: Any = None) -> Decision:
    d3 = load_question(REPO_ROOT / DECISIONS_DIR / "d3.yaml")
    return Decision(d3, 0.79, primary=engine, fallback=fallback)


class _Picks:
    """Answers a Choice over found answers as told, and keeps the answers it was offered."""

    name = "typesafe:jev-test"

    def __init__(self, answer: str, probability: float) -> None:
        self.answer, self.probability = answer, probability
        self.offered: list[dict[str, str]] = []

    def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
        self.offered.append(dict(question.answers))
        return Judgment(
            question.id, question.version, self.answer, self.probability, self.name, 80, 2e-05
        )


class TestAlreadyOpen:
    def test_a_match_that_stands_is_named_and_traced_and_the_run_goes_on(self) -> None:
        picks = _Picks("IT-7", 0.9)
        app = _app_with_stage(_Engine("incident", 0.99), already_open=_already_open(picks))
        run, response = _post(app, {"input": _INCIDENT, "open_items": _OPEN})
        data = response.json()
        run.assert_called_once()
        assert (data["already_open"]["key"], data["already_open"]["probability"]) == ("IT-7", 0.9)
        assert [e["details"]["question"] for e in _events(app)] == ["d1", "d3"]
        # The open Work items are offered redacted, keyed by their keys, then none.
        [offered] = picks.offered
        assert list(offered) == ["IT-7", "IT-8", "none"]
        assert "Printer on 3 jammed" in offered["IT-7"] and "a@example.com" not in offered["IT-7"]

    @pytest.mark.parametrize(
        "picks", [_Picks("IT-7", 0.6), _Picks("none", 0.95)], ids=["below its cut", "none"]
    )
    def test_otherwise_nothing_is_named(self, picks: _Picks) -> None:
        app = _app_with_stage(_Engine("incident", 0.99), already_open=_already_open(picks))
        _, response = _post(app, {"input": _INCIDENT, "open_items": _OPEN})
        assert response.json()["already_open"] is None
        assert [e["details"]["question"] for e in _events(app)] == ["d1", "d3"]

    def test_a_fallback_s_match_is_not_named(self) -> None:
        decision = _already_open(_Down(), fallback=_Picks("IT-7", 0.99))
        app = _app_with_stage(_Engine("incident", 0.99), already_open=decision)
        _, response = _post(app, {"input": _INCIDENT, "open_items": _OPEN})
        assert response.json()["already_open"] is None

    def test_without_open_items_it_is_not_asked(self) -> None:
        picks = _Picks("IT-7", 0.9)
        app = _app_with_stage(_Engine("incident", 0.99), already_open=_already_open(picks))
        _post(app, {"input": _INCIDENT})
        assert picks.offered == []

    def test_an_ask_carries_the_match_too(self) -> None:
        app = _app_with_stage(
            _Engine("incident", 0.99),
            already_open=_already_open(_Picks("IT-7", 0.9)),
            enough=_enough(_Says({"d4": ("no", 0.9)})),
        )
        run, response = _post(app, {"input": _INCIDENT, "open_items": _OPEN}, "/api/run/stream")
        run.assert_not_called()
        assert '"ask": {' in response.text and '"already_open": {' in response.text


def test_an_open_work_item_is_offered_at_most_its_first_thousand_characters() -> None:
    from opspilot.judgment import OPEN_ITEM_CHARS, open_items_question
    from opspilot.redaction import Redactor

    d3 = load_question(REPO_ROOT / DECISIONS_DIR / "d3.yaml")
    long = [{"key": "IT-7", "subject": "log", "body": "x" * 5000}]
    meaning = open_items_question(d3, long, Redactor.from_yaml()).answers["IT-7"]
    assert len(meaning) == len(d3.candidates.format(text="")) + OPEN_ITEM_CHARS  # type: ignore[union-attr]


# ── The request path: which catalog item, then Lookups (#231) ───────────────


def _catalog(engine: Any, fallback: Any = None) -> Any:
    from opspilot.catalog import CatalogDecision, catalog_question, load_catalog

    catalog = load_catalog(REPO_ROOT / DECISIONS_DIR / "catalog.yaml")
    question = catalog_question(REPO_ROOT / DECISIONS_DIR / "r1.yaml", catalog)
    return CatalogDecision(Decision(question, 0.6, primary=engine, fallback=fallback), catalog)


def _request_run(item: tuple[str, float], **work_item: Any) -> tuple[Any, Any, Any]:
    """Run a declared request with the catalog on; the summary's run mock, the response, the app."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    app = _app_with_stage(_Engine("service_request", 0.99), catalog=_catalog(_Picks(*item)))
    request = {**_UNTYPED, "work_item_type": "service_request", **work_item}
    result = replace(
        _run_result(),
        summary={"summary": "ok", "asset_draft": {"category": "monitor", "quantity": 1}},
    )
    with (
        patch("opspilot.api.routes.run.run_ticket_summary", return_value=result) as run,
        TestClient(app) as client,
    ):
        app.state.request_fulfillment_pb.output_schema = "request_fulfillment_v1"
        response = client.post("/api/run", json={"input": request})
    return run, response.json(), app


class TestCatalog:
    def test_an_item_that_stands_is_looked_up_and_no_model_decides_its_approval(self) -> None:
        run, data, app = _request_run(("vpn_access", 0.9))
        assert run.call_args.kwargs["decided"] == {
            "requested_item": "VPN access",
            "approval_needed": True,
        }
        catalog = data["catalog"]
        assert (catalog["item"], catalog["approval"], catalog["entitled"]) == (
            "vpn_access",
            "manager",
            True,
        )
        assert catalog["automated"] is False and catalog["fields"] == ["who needs it", "why"]
        assert [e["details"]["question"] for e in _events(app)] == ["d1", "r1"]

    def test_an_automated_item_runs_no_playbook(self) -> None:
        run, data, _ = _request_run(("password_reset", 0.9))
        run.assert_not_called()
        assert data["needs_confirmation"] is True and data["session_id"] == ""
        assert data["catalog"]["automated"] is True

    @pytest.mark.parametrize("item", [("none", 0.95), ("vpn_access", 0.4)], ids=["none", "unsure"])
    def test_otherwise_the_playbook_runs_and_a_person_checks_the_item(
        self, item: tuple[str, float]
    ) -> None:
        run, data, _ = _request_run(item)
        assert run.call_args.kwargs["decided"] is None
        assert data["catalog"]["item"] is None

    def test_an_item_s_category_is_counted_in_stock(self) -> None:
        _, data, _ = _request_run(("loaner", 0.9))
        assert (data["catalog"]["stock_category"], data["catalog"]["in_stock"]) == ("laptop", 2)

    def test_the_requested_category_is_counted_once_the_artifact_names_it(self) -> None:
        _, data, _ = _request_run(("new_hardware", 0.9))
        assert (data["catalog"]["stock_category"], data["catalog"]["in_stock"]) == ("monitor", 1)

    @pytest.mark.parametrize(("role", "entitled"), [("engineering", True), ("finance", False)])
    def test_entitlement_is_looked_up_from_the_submitter_s_role(
        self, role: str, entitled: bool
    ) -> None:
        _, data, _ = _request_run(("admin_rights", 0.9), submitter_role=role)
        assert data["catalog"]["entitled"] is entitled


# ── r2: is what was filed as a request really one? (#293) ────────────────────


def _really(engine: Any, fallback: Any = None) -> Decision:
    return Decision(load_question(REPO_ROOT / DECISIONS_DIR / "r2.yaml"), 0.8, engine, fallback)


def _filed_as_request(answer: tuple[str, float], **stage: Any) -> tuple[Any, Any, Any]:
    """Run a Work item declared a request, with r2 on; the run mock, the response, the app."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    app = _app_with_stage(
        _Engine("service_request", 0.99), really=_really(_Picks(*answer)), **stage
    )
    request = {**_UNTYPED, "work_item_type": "service_request"}
    with (
        patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()) as run,
        TestClient(app) as client,
    ):
        app.state.request_fulfillment_pb.output_schema = "request_fulfillment_v1"
        app.state.playbook.output_schema = "incident_summary_v1"
        response = client.post("/api/run", json={"input": request})
    return run, response.json(), app


class TestReally:
    def test_a_change_stops_for_a_person(self) -> None:
        run, data, _ = _filed_as_request(("change", 0.9))
        run.assert_not_called()
        assert data["needs_confirmation"] is True
        assert (data["really"]["answer"], data["really"]["probability"]) == ("change", 0.9)

    def test_an_incident_takes_the_incident_path(self) -> None:
        severity = _severity(_Says(_SURE))
        run, data, app = _filed_as_request(("incident", 0.9), severity=severity)
        assert run.call_args.args[0].playbook is app.state.playbook  # the incident summary
        assert run.call_args.kwargs["decided"] == {"severity_suggested": "P1"}
        assert data["really"]["answer"] == "incident"
        assert [e["details"]["question"] for e in _events(app)] == ["d1", "r2", "d7", "d8"]

    @pytest.mark.parametrize(
        "answer", [("request", 0.95), ("incident", 0.6)], ids=["request", "below its cut"]
    )
    def test_otherwise_it_stays_on_the_request_path(self, answer: tuple[str, float]) -> None:
        run, data, app = _filed_as_request(answer)
        assert run.call_args.args[0].playbook is app.state.request_fulfillment_pb
        assert data["really"] is None


# ── r3: enough to fulfil, and the ask for what the item needs (#294) ─────────


def _fulfil(engine: Any) -> Decision:
    return Decision(load_question(REPO_ROOT / DECISIONS_DIR / "r3.yaml"), 0.51, primary=engine)


def _request_with_item(
    item: tuple[str, float], enough: tuple[str, float], **body: Any
) -> tuple[Any, Any, Any, Any]:
    """A request whose item stands, with r3 on: the run mock, the response, the app, the asker."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    says = _Says({"r3": enough})
    asker = _Classifier(_ASK)
    app = _app_with_stage(
        _Engine("service_request", 0.99),
        catalog=_catalog(_Picks(*item)),
        fulfil=_fulfil(says),
        ask_provider=asker,
    )
    request = {**_UNTYPED, "work_item_type": "service_request"}
    with (
        patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()) as run,
        TestClient(app) as client,
    ):
        app.state.request_fulfillment_pb.output_schema = "request_fulfillment_v1"
        response = client.post("/api/run", json={"input": request, **body})
    return run, response.json(), app, (says, asker)


class TestEnoughToFulfil:
    def test_a_request_missing_what_its_item_needs_is_asked_for_it(self) -> None:
        run, data, _, (says, asker) = _request_with_item(("vpn_access", 0.9), ("no", 0.8))
        run.assert_not_called()
        assert data["needs_confirmation"] is True and data["catalog"]["item"] == "vpn_access"
        assert data["ask"]["work_item_type"] == "service_request"
        [call] = asker.calls
        assert call["messages"][1].content.endswith("What fulfilling it needs: who needs it, why")

    def test_it_is_asked_against_the_item_s_fields(self) -> None:
        offered: list[str] = []

        class Reads(_Says):
            def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
                offered.append(question.text)
                return super().judge(question, state, timeout_s=timeout_s)

        from unittest.mock import patch

        from fastapi.testclient import TestClient

        app = _app_with_stage(
            _Engine("service_request", 0.99),
            catalog=_catalog(_Picks("loaner", 0.9)),
            fulfil=_fulfil(Reads({"r3": ("yes", 0.9)})),
        )
        with (
            patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()),
            TestClient(app) as client,
        ):
            app.state.request_fulfillment_pb.output_schema = "request_fulfillment_v1"
            client.post(
                "/api/run", json={"input": {**_UNTYPED, "work_item_type": "service_request"}}
            )
        assert offered == [
            "Does this request give what fulfilling a Loaner device needs: who, from when, until when?"
        ]

    @pytest.mark.parametrize(
        ("enough", "body"),
        [(("yes", 0.9), {}), (("no", 0.4), {}), (("no", 0.9), {"asked": True})],
        ids=["yes", "below its cut", "already asked"],
    )
    def test_otherwise_it_is_fulfilled_as_before(
        self, enough: tuple[str, float], body: dict[str, Any]
    ) -> None:
        run, data, _, _ = _request_with_item(("vpn_access", 0.9), enough, **body)
        run.assert_called_once()
        assert data["ask"] is None

    def test_an_automated_item_is_not_asked(self) -> None:
        run, data, _, (says, _) = _request_with_item(("password_reset", 0.9), ("no", 0.9))
        assert says.asked == [] and data["catalog"]["automated"] is True


def test_an_item_that_lists_no_fields_is_not_asked_r3() -> None:
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from opspilot.catalog import CatalogDecision

    decision = _catalog(_Picks("vpn_access", 0.9))
    vpn = replace(decision.catalog.items["vpn_access"], fields=())
    catalog = replace(decision.catalog, items={**decision.catalog.items, "vpn_access": vpn})
    says = _Says({"r3": ("no", 0.9)})
    app = _app_with_stage(
        _Engine("service_request", 0.99),
        catalog=CatalogDecision(decision.decision, catalog),
        fulfil=_fulfil(says),
    )
    with (
        patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()) as run,
        TestClient(app) as client,
    ):
        app.state.request_fulfillment_pb.output_schema = "request_fulfillment_v1"
        client.post("/api/run", json={"input": {**_UNTYPED, "work_item_type": "service_request"}})
    assert says.asked == []
    run.assert_called_once()


# ── The handbook pages, ordered by decision 9 for the person (#286) ─────────


class _ByPage:
    """Scores each page by its path in the state; ``fail_on`` raises on that page."""

    name = "typesafe:jev-test"

    def __init__(self, p_yes: dict[str, float], fail_on: str | None = None) -> None:
        self.p_yes, self.fail_on = p_yes, fail_on

    def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
        page = next(k for k in self.p_yes if f"({k})" in state)
        if page == self.fail_on:
            raise ProviderError("timed out")
        p = self.p_yes[page]
        answer = "yes" if p >= 0.5 else "no"
        return Judgment(
            "d9", question.version, answer, p if answer == "yes" else 1 - p, self.name, 9, 2e-05
        )


def _ordered_run(engine: Any) -> tuple[Any, Any]:
    """An Incident run with the pages ordered; the response, and the run mock."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from opspilot.judgment import Ordering

    app = _app_with_stage(_Engine("incident", 0.99))
    hits = [
        SimpleNamespace(document_id=d, content=f"best of {d}")
        for d in ("doc_a", "doc_b", "doc_a", "doc_c")
    ]
    with (
        patch("opspilot.api.routes.run.run_ticket_summary", return_value=_run_result()) as run,
        patch("opspilot.api.routes.run.kb_search", return_value=hits) as search,
        TestClient(app) as client,
    ):
        app.state.judgments = replace(
            app.state.judgments,
            page_order=Ordering(load_question(REPO_ROOT / DECISIONS_DIR / "d9.yaml"), engine),
        )
        app.state.sqlite = MagicMock()
        app.state.sqlite.get_document.side_effect = lambda d: {
            "source_path": f"{d}.md",
            "title": d.upper(),
        }
        app.state.playbook.retrieval.prefetch.query_fields = None
        app.state.playbook.retrieval.prefetch.top_k = 5
        app.state.playbook.defaults.kb_id = "opspilot:public-kb"
        data = client.post("/api/run", json={"input": _INCIDENT}).json()
    assert search.call_args.kwargs["namespace"] == "opspilot:public-kb"
    assert search.call_args.kwargs["top_k"] == 5
    assert "jane.doe@example.com" not in search.call_args.args[0]  # the query is redacted
    return data, run


class TestPageOrder:
    def test_the_pages_are_ordered_likeliest_fix_first(self) -> None:
        data, run = _ordered_run(_ByPage({"doc_a.md": 0.1, "doc_b.md": 0.4, "doc_c.md": 0.2}))
        run.assert_called_once()
        assert data["pages"]["ordered_by"] == "typesafe:jev-test"
        assert [p["source_path"] for p in data["pages"]["pages"]] == [
            "doc_b.md",
            "doc_c.md",
            "doc_a.md",
        ]

    def test_if_the_engine_fails_on_a_page_the_search_s_order_stands(self) -> None:
        data, _ = _ordered_run(
            _ByPage({"doc_a.md": 0.1, "doc_b.md": 0.4, "doc_c.md": 0.2}, fail_on="doc_c.md")
        )
        assert data["pages"]["ordered_by"] is None
        assert [p["source_path"] for p in data["pages"]["pages"]] == [
            "doc_a.md",
            "doc_b.md",
            "doc_c.md",
        ]


def test_ordering_scores_the_pages_at_once_and_in_their_order() -> None:
    import threading
    import time as clock

    from opspilot.judgment import Ordering

    seen: list[str] = []
    started = threading.Barrier(3, timeout=2)  # all three calls in flight together

    class Slow:
        name = "e"

        def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
            started.wait()
            seen.append(state)
            clock.sleep(0.01)
            return Judgment("d9", "d9-v1", "no", 1 - float(state), "e", 1, 0.0)

    judged = Ordering(load_question(REPO_ROOT / DECISIONS_DIR / "d9.yaml"), Slow()).score(
        ["0.1", "0.2", "0.3"]
    )
    assert [round(1 - j.probability, 2) for j in judged] == [0.1, 0.2, 0.3]  # in order
    assert sorted(seen) == ["0.1", "0.2", "0.3"]
