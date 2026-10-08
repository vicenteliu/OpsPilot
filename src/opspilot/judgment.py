"""Judgments: one answer, picked from a set written down in the repo (ADR-0040).

A Judgment takes a state (the redacted rendering of a Work item) and a
Question whose answer space lives in ``judgments/decisions/``, and returns one
of those answers with a probability. It writes nothing else: no reply, no
reasoning.

Two engines can answer. Jev, through the ``typesafe`` provider kind, returns a
probability calibrated against outcomes. The Playbook's own model is the
baseline every Judgment is measured against and the fallback when Jev cannot
be reached; its probability is the confidence it scores itself, which is
exactly what the label set exists to test. Each Judgment carries the engine
that decided, its latency and its price, and why the primary engine did not
decide when it did not, because the trace has to say all of it.

This is not the chat ``ProviderProtocol``: that carries no probabilities, and
stretching it to fit would make every chat provider pretend to have one.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Final, Literal, Protocol

import yaml

from .errors import OpsPilotError
from .orchestrator.classify import VALID_TYPES, classify_state
from .orchestrator.types import PlaybookSpec
from .providers.base import ProviderProtocol

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
        answer = fallback.judge(question, state, timeout_s=timeout_s)
        return replace(answer, fallback=f"{primary.name}: {e}")
