"""Judgments: one answer, picked from a set written down in the repo (ADR-0040).

A Judgment takes a state (the redacted rendering of a Work item) and a
Question whose answer space lives in ``judgments/decisions/``, and returns one
of those answers with a probability. It writes nothing else: no reply, no
reasoning.

Two engines can answer. Jev, through the ``typesafe`` provider kind, returns a
probability calibrated against outcomes, by its vendor's account. The
Playbook's own model is the baseline every Judgment is measured against and the
fallback when Jev cannot be reached; its probability is the confidence it
scores itself, which is exactly what the label set exists to test. Each
Judgment carries the engine that decided, its latency and its price, and why
the primary engine did not decide when it did not, because the trace has to
say all of it.

This is not the chat ``ProviderProtocol``: that carries no probabilities, and
stretching it to fit would make every chat provider pretend to have one.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Final, Literal, Protocol

import httpx
import yaml

from .errors import ConfigError, OpsPilotError
from .orchestrator.classify import VALID_TYPES, classify_state
from .orchestrator.types import PlaybookSpec
from .providers.base import ProviderProtocol
from .providers.pricing import estimate_cost_usd

logger = logging.getLogger("opspilot.judgment")

DECISIONS_DIR: Final = Path("judgments/decisions")

Kind = Literal["noul", "choice", "score"]
_KINDS: Final[tuple[str, ...]] = ("noul", "choice", "score")


class JudgmentError(OpsPilotError):
    """An engine could not answer a Question."""


@dataclass(frozen=True)
class Question:
    """One decision as its file states it."""

    id: str  # "d2"
    version: str  # "d2-v1"; a label records the version it was labelled against
    kind: Kind
    text: str
    answers: dict[str, str]  # answer → what it means, in order for a Score
    threshold: float | None  # set from the label set; None until measured


def load_question(path: Path) -> Question:
    """Read a decision file; refuse one an engine could not be asked."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    kind = data.get("kind")
    answers = data.get("answers") or {}
    threshold = data.get("threshold")
    if kind not in _KINDS:
        raise JudgmentError(f"{path}: kind must be one of {', '.join(_KINDS)}, not {kind!r}")
    if kind == "noul" and set(answers) != {"yes", "no"}:
        raise JudgmentError(f"{path}: a noul question answers yes or no")
    if len(answers) < 2:
        raise JudgmentError(f"{path}: a question needs at least two answers")
    if threshold is not None and not 0 <= float(threshold) <= 1:
        raise JudgmentError(f"{path}: threshold must be between 0 and 1, not {threshold}")
    return Question(
        id=str(data["id"]),
        version=str(data["version"]),
        kind=kind,
        text=str(data["question"]),
        answers={str(k): str(v) for k, v in answers.items()},
        threshold=None if threshold is None else float(threshold),
    )


@dataclass(frozen=True)
class Judgment:
    """What one engine answered, and what it took to answer."""

    question: str  # the Question's id
    version: str
    answer: str
    probability: float
    engine: str  # e.g. "playbook:anthropic/claude-haiku-4-5-20251001"
    latency_ms: int
    cost_usd: float
    fallback: str | None = None  # why the primary engine did not decide

    def as_trace(self) -> dict[str, Any]:
        return asdict(self)


class JudgmentEngine(Protocol):
    """Anything that can pick one answer from a Question's answer space."""

    name: str

    def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment: ...


class ClassificationJudge:
    """The Playbook's model, answering decision 2 the way Classification does today.

    It asks the classification Playbook's own prompt, not the Question's text:
    the baseline is the system as it stands, so it is measured as it stands.
    """

    def __init__(self, playbook: PlaybookSpec, provider: ProviderProtocol) -> None:
        self._playbook = playbook
        self._provider = provider
        self.name = f"playbook:{playbook.model.provider_id}/{playbook.model.name}"

    def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
        if set(question.answers) != set(VALID_TYPES):
            raise JudgmentError(f"{self.name} answers only incident or request, not {question.id}")
        started = time.monotonic()
        result = classify_state(
            state,
            playbook=self._playbook,
            provider=self._provider,
            timeout_ms=int(timeout_s * 1000),
        )
        return Judgment(
            question=question.id,
            version=question.version,
            answer=result.work_item_type,
            probability=result.confidence,
            engine=self.name,
            latency_ms=int((time.monotonic() - started) * 1000),
            cost_usd=result.usage.cost_usd,
        )


TYPESAFE_URL: Final = "https://api.typesafe.ai/v1/systemone"
# Pinned, not `jev-latest`: a threshold is measured against one version, and an
# alias moves under it when a new one ships (docs.typesafe.ai/models).
JEV_MODEL: Final = "jev-1.13.0"


class TypeSafeJudge:
    """Jev, through the ``typesafe`` provider kind (docs.typesafe.ai/api).

    The Question goes out as its file states it: its text as the instructions,
    its answers and their meanings as the criteria. Nothing is reworded for
    Jev, so it is asked the answer space the label set was labelled against.

    The probability is the chosen answer's, not the response's ``confidence``:
    for two answers that is 2p − 1, a measure of how peaked the distribution
    is, and the threshold and the Brier score are both stated on p.

    One attempt and no retries: a failure is what the fallback is for, and a
    retry spends time a person is waiting through.
    """

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client()
        self.name = f"typesafe:{JEV_MODEL}"

    def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
        if question.kind != "choice":
            raise JudgmentError(
                f"{self.name} asks only choice questions so far, not {question.kind} "
                f"({question.id})"
            )
        body = {
            "state": state,
            "model": JEV_MODEL,
            "questions": {
                question.id: {
                    "type": "choice",
                    "instructions": question.text,
                    "criteria": question.answers,
                }
            },
        }
        started = time.monotonic()
        try:
            r = self._client.post(
                TYPESAFE_URL,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=timeout_s,
            )
        except httpx.TimeoutException as e:
            raise JudgmentError(f"timed out after {timeout_s}s") from e
        except httpx.RequestError as e:
            raise JudgmentError(f"unreachable: {e}") from e
        latency_ms = int((time.monotonic() - started) * 1000)
        if not r.is_success:
            raise JudgmentError(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
            answer = data["answers"][question.id]
            choice = str(answer["choice"])
            if choice not in question.answers:
                raise JudgmentError(
                    f"answered {choice!r}, outside the answer space of {question.version}"
                )
            probability = float(answer["probabilities"][choice])
            input_tokens = int(data["usage"]["input_tokens"])
        except (ValueError, KeyError, TypeError) as e:
            raise JudgmentError(f"unexpected response: {e!r}") from e
        return Judgment(
            question=question.id,
            version=question.version,
            answer=choice,
            probability=probability,
            engine=self.name,
            latency_ms=latency_ms,
            cost_usd=estimate_cost_usd(JEV_MODEL, input_tokens, 0),  # output is free
        )


def judge_with_fallback(
    primary: JudgmentEngine,
    fallback: JudgmentEngine,
    question: Question,
    state: str,
    *,
    timeout_s: float,
) -> Judgment:
    """Ask the primary engine; when it fails or times out, ask the fallback and say why.

    Only engine failures fall back. A bug in the caller is not a reason to
    quietly hand the decision to another model.
    """
    try:
        return primary.judge(question, state, timeout_s=timeout_s)
    except OpsPilotError as e:
        # Logged as well as recorded: an answer from the fallback goes to a
        # person, and a run that never starts has no Session to trace it on.
        logger.warning(
            "%s could not decide %s, so %s did: %s", primary.name, question.id, fallback.name, e
        )
        answer = fallback.judge(question, state, timeout_s=timeout_s)
        return replace(answer, fallback=f"{primary.name}: {e}")


JUDGMENT_TIMEOUT_S: Final = 20.0
WORK_ITEM_TYPE_FILE: Final = "d2.yaml"


@dataclass(frozen=True)
class Stage:
    """The Judgments stage as the server runs it; it exists only when it is on.

    ``threshold`` is the measured cut for decision 2, on the primary engine's
    probability: below it the outcome is *needs a person*, the same path
    Classification's own cut takes today.
    """

    work_item_type: Question
    threshold: float
    primary: JudgmentEngine
    fallback: JudgmentEngine | None = None
    timeout_s: float = JUDGMENT_TIMEOUT_S

    def decide(self, question: Question, state: str) -> Judgment:
        if self.fallback is None:
            return self.primary.judge(question, state, timeout_s=self.timeout_s)
        return judge_with_fallback(
            self.primary, self.fallback, question, state, timeout_s=self.timeout_s
        )

    def needs_a_person(self, judgment: Judgment) -> bool:
        """Below the threshold, or answered by the fallback: either way a person picks.

        The threshold was measured on the primary's probability, so it says
        nothing about how far to trust the fallback's, however high.
        """
        return judgment.fallback is not None or judgment.probability < self.threshold


def build_stage(
    decisions_dir: Path,
    classify_playbook: PlaybookSpec,
    provider: ProviderProtocol,
    *,
    typesafe_api_key: str | None = None,
) -> Stage:
    """The stage with the engines there are; refuse it until its threshold is measured.

    With a TypeSafe key, Jev decides and the Playbook's model is its fallback.
    Without one, the Playbook's model decides alone, and the log says so.
    """
    path = decisions_dir / WORK_ITEM_TYPE_FILE
    question = load_question(path)
    if question.threshold is None:
        raise ConfigError(
            f"the Judgments stage is on but {path} has no threshold. Measure it on the "
            "label set first (judgments/label_set/SPEC.md §7); it is never guessed."
        )
    baseline = ClassificationJudge(classify_playbook, provider)
    key = (typesafe_api_key or "").strip()
    if not key:
        logger.warning(
            "The Judgments stage is on without TYPESAFE_API_KEY: %s decides alone.",
            baseline.name,
        )
        return Stage(work_item_type=question, threshold=question.threshold, primary=baseline)
    # Refused here rather than on the first Work item, where it would cost a
    # failed call per item or, outside ASCII, fail the run outright.
    if not (key.isascii() and key.isprintable()) or " " in key:
        raise ConfigError("TYPESAFE_API_KEY is malformed: it holds whitespace or non-ASCII.")
    return Stage(
        work_item_type=question,
        threshold=question.threshold,
        primary=TypeSafeJudge(key),
        fallback=baseline,
    )
