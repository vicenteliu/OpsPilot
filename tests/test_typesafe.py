"""The ``typesafe`` engine: a thin client for Jev, and the Judgment it makes (ADR-0040).

The wire shapes follow typesafe-sdk 0.7.2, whose models are generated from
https://api.typesafe.ai/openapi.json. Every call here goes through
``httpx.MockTransport``; nothing reaches the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from opspilot import judgment
from opspilot.errors import ProviderError
from opspilot.judgment import (
    DECISIONS_DIR,
    JudgmentError,
    Question,
    TypeSafeJudge,
    load_question,
)
from opspilot.providers import pricing
from opspilot.providers.typesafe import DEFAULT_MODEL, TypeSafeClient

REPO_ROOT = Path(__file__).resolve().parents[1]
D2 = REPO_ROOT / DECISIONS_DIR / "d2.yaml"


def _client(handler: Any) -> TypeSafeClient:
    return TypeSafeClient(
        api_key="ts-test",
        client=httpx.Client(
            base_url="https://api.typesafe.ai", transport=httpx.MockTransport(handler)
        ),
    )


def _answer(choice: str = "service_request", **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "jev-1",
        "answers": {
            "d2": {
                "type": "choice",
                "choice": choice,
                "confidence": 0.88,
                "probabilities": {"incident": 0.09, "service_request": 0.91},
            }
        },
        "usage": {"input_tokens": 2_000, "output_tokens": 1},
    }
    body.update(over)
    return body


class _Recorder:
    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status, self.body = status, _answer() if body is None else body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body)


class TestClient:
    def test_system_one_posts_the_body_the_api_takes_with_a_bearer_key(self) -> None:
        rec = _Recorder()
        questions = {"d2": {"type": "choice", "instructions": "q?", "criteria": {"a": "x"}}}
        data = _client(rec).system_one("the state", questions, model="jev-latest", timeout_s=3)
        assert data == _answer()
        [req] = rec.requests
        assert (req.method, req.url.path) == ("POST", "/v1/systemone")
        assert req.headers["authorization"] == "Bearer ts-test"
        assert json.loads(req.content) == {
            "state": "the state",
            "model": "jev-latest",
            "questions": questions,
        }
        assert req.extensions["timeout"]["read"] == 3

    def test_models_lists_the_names_the_account_may_ask_for(self) -> None:
        body = {
            "models": [{"name": "jev-latest", "description": "d", "release_date": "2026-09-19"}]
        }
        rec = _Recorder(body=body)
        assert _client(rec).models() == ["jev-latest"]
        [req] = rec.requests
        assert (req.method, req.url.path) == ("GET", "/v1/models")

    def test_the_defaults_are_the_sdks(self) -> None:
        assert DEFAULT_MODEL == "jev-latest"
        c = TypeSafeClient(api_key="k")
        assert c.timeout_s == 10.0 and str(c.base_url) == "https://api.typesafe.ai"

    def test_an_error_status_is_a_provider_error_that_never_echoes_the_key(self) -> None:
        rec = _Recorder(status=401, body={"error": "bad key"})
        with pytest.raises(ProviderError, match="HTTP 401") as e:
            _client(rec).models()
        assert "ts-test" not in str(e.value)

    def test_a_timeout_is_a_provider_error(self) -> None:
        def slow(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        with pytest.raises(ProviderError, match=r"timed out after 2\.5s"):
            _client(slow).system_one("s", {}, model="jev-latest", timeout_s=2.5)

    def test_a_network_failure_is_a_provider_error(self) -> None:
        def down(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        with pytest.raises(ProviderError, match="network error"):
            _client(down).models()

    def test_a_body_that_is_not_json_is_a_provider_error(self) -> None:
        def html(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>")

        with pytest.raises(ProviderError, match="not JSON"):
            _client(html).models()


@pytest.fixture
def verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the two facts docs.typesafe.ai has not yet been read for."""
    monkeypatch.setattr(judgment, "JEV_PROBABILITY_FIELD", "probabilities")
    monkeypatch.setitem(pricing._USD_PER_MILLION, "jev", (0.5, 0.0))


def _judge(rec: Any) -> TypeSafeJudge:
    return TypeSafeJudge(_client(rec))


class TestTypeSafeJudge:
    def test_asks_decision_2_as_a_choice_over_its_written_answers(self, verified: None) -> None:
        rec = _Recorder()
        _judge(rec).judge(load_question(D2), "VPN for a new starter", timeout_s=4)
        [req] = rec.requests
        q = load_question(D2)
        assert json.loads(req.content) == {
            "state": "VPN for a new starter",
            "model": "jev-latest",
            "questions": {"d2": {"type": "choice", "instructions": q.text, "criteria": q.answers}},
        }

    def test_returns_the_answer_with_its_engine_latency_and_cost(self, verified: None) -> None:
        j = _judge(_Recorder()).judge(load_question(D2), "s", timeout_s=4)
        assert (j.question, j.version, j.answer) == ("d2", "d2-v1", "service_request")
        assert j.engine == "typesafe:jev-latest" and j.fallback is None
        assert j.latency_ms >= 0
        assert j.cost_usd == pytest.approx(2_000 * 0.5 / 1_000_000)  # input tokens only

    @pytest.mark.parametrize(("field", "expected"), [("confidence", 0.88), ("probabilities", 0.91)])
    def test_the_probability_is_read_from_the_field_the_docs_name(
        self, monkeypatch: pytest.MonkeyPatch, field: str, expected: float
    ) -> None:
        monkeypatch.setattr(judgment, "JEV_PROBABILITY_FIELD", field)
        j = _judge(_Recorder()).judge(load_question(D2), "s", timeout_s=4)
        assert j.probability == expected

    def test_until_the_field_is_verified_jev_does_not_decide_or_bill(self) -> None:
        # Unverified, the judge refuses before a paid call, so the stage's
        # fallback decides and says why.
        assert judgment.JEV_PROBABILITY_FIELD is None
        rec = _Recorder()
        with pytest.raises(JudgmentError, match="unverified"):
            _judge(rec).judge(load_question(D2), "s", timeout_s=4)
        assert rec.requests == []

    def test_an_unpriced_model_costs_nothing_rather_than_a_guess(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(judgment, "JEV_PROBABILITY_FIELD", "confidence")
        j = _judge(_Recorder()).judge(load_question(D2), "s", timeout_s=4)
        assert j.cost_usd == 0.0

    def test_unreported_usage_costs_nothing(self, verified: None) -> None:
        rec = _Recorder(body=_answer(usage={"input_tokens": None, "output_tokens": None}))
        assert _judge(rec).judge(load_question(D2), "s", timeout_s=4).cost_usd == 0.0

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            (_answer(choice="problem"), "not one of d2's answers"),
            (_answer(answers={}), "no answer to d2"),
            (_answer(answers={"d2": {"type": "noul", "probability": 0.9}}), "not a choice"),
            (_answer(answers={"d2": {"type": "choice", "choice": "incident"}}), "malformed"),
            ({"detail": "?"}, "malformed"),
            (_answer(usage=None), "malformed"),
        ],
    )
    def test_an_answer_outside_the_question_is_an_engine_failure(
        self, verified: None, body: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(JudgmentError, match=message):
            _judge(_Recorder(body=body)).judge(load_question(D2), "s", timeout_s=4)

    def test_a_probability_outside_0_and_1_is_refused(self, verified: None) -> None:
        body = _answer()
        body["answers"]["d2"]["probabilities"]["service_request"] = 1.4
        with pytest.raises(JudgmentError, match="between 0 and 1"):
            _judge(_Recorder(body=body)).judge(load_question(D2), "s", timeout_s=4)

    def test_refuses_a_kind_it_does_not_ask_yet(self, verified: None) -> None:
        rec = _Recorder()
        security = Question("d1", "d1-v1", "noul", "Security?", {"yes": "", "no": ""}, None)
        with pytest.raises(JudgmentError, match="asks only choice"):
            _judge(rec).judge(security, "s", timeout_s=4)
        assert rec.requests == []

    def test_the_timeout_it_is_given_reaches_the_request(self, verified: None) -> None:
        rec = _Recorder()
        _judge(rec).judge(load_question(D2), "s", timeout_s=6.5)
        assert rec.requests[0].extensions["timeout"]["read"] == 6.5
