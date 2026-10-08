"""Judgments: the decision file, the baseline engine, and the fallback (ADR-0040)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from opspilot.errors import ProviderError
from opspilot.judgment import (
    DECISIONS_DIR,
    ClassificationJudge,
    Judgment,
    JudgmentError,
    Question,
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
