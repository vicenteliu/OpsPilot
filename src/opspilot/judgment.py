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
from .orchestrator.ticket_summary import _parse_summary_json
from .orchestrator.types import PlaybookSpec
from .providers.base import ProviderProtocol
from .providers.pricing import estimate_cost_usd
from .providers.types import Message, SamplingParams

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
    # Engine name → its cut, set from the label set. A probability is on its
    # engine's own scale, so a cut means nothing for any other engine (#274).
    thresholds: dict[str, float]


def load_question(path: Path) -> Question:
    """Read a decision file; refuse one an engine could not be asked."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    kind = data.get("kind")
    answers = data.get("answers") or {}
    thresholds = data.get("thresholds") or {}
    if "threshold" in data:
        raise JudgmentError(
            f"{path}: `threshold` is now `thresholds`, keyed by the engine it was measured on"
        )
    if not isinstance(thresholds, dict):
        raise JudgmentError(f"{path}: thresholds must be keyed by engine, not {thresholds!r}")
    if kind not in _KINDS:
        raise JudgmentError(f"{path}: kind must be one of {', '.join(_KINDS)}, not {kind!r}")
    if kind == "noul" and set(answers) != {"yes", "no"}:
        raise JudgmentError(f"{path}: a noul question answers yes or no")
    if len(answers) < 2:
        raise JudgmentError(f"{path}: a question needs at least two answers")
    for engine, cut in thresholds.items():
        if not 0 <= float(cut) <= 1:
            raise JudgmentError(f"{path}: {engine}'s threshold must be between 0 and 1, not {cut}")
    return Question(
        id=str(data["id"]),
        version=str(data["version"]),
        kind=kind,
        text=str(data["question"]),
        answers={str(k): str(v) for k, v in answers.items()},
        thresholds={str(k): float(v) for k, v in thresholds.items()},
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
        if question.kind == "choice":
            criteria: dict[str, str] = question.answers
        elif question.kind == "noul":
            criteria = {"true": question.answers["yes"], "false": question.answers["no"]}
        else:
            raise JudgmentError(f"{self.name} does not ask {question.kind} questions yet")
        body = {
            "state": state,
            "model": JEV_MODEL,
            "questions": {
                question.id: {
                    "type": question.kind,
                    "instructions": question.text,
                    "criteria": criteria,
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
            if question.kind == "noul":
                # A Noul is P(yes); the Judgment is the answer it leans to, with that
                # answer's probability, the same shape a Choice gives.
                p_yes = float(answer["noul"])
                choice = "yes" if p_yes >= 0.5 else "no"
                probability = p_yes if choice == "yes" else 1 - p_yes
            else:
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


_QUESTION_PROMPT: Final = """\
You answer one question about an IT Work item, and nothing else: no advice, no reasons.

Question: {question}

Answer with exactly one of these, as each is defined:
{answers}

Reply with JSON only:
{{"answer": "<one of: {keys}>", "probability": <a number from 0 to 1: how likely your answer is right>}}
"""


class QuestionJudge:
    """The Playbook's model, asked any Question in its file's own words (ADR-0040).

    The baseline a Judgment without a Classification of its own is measured
    against, and Jev's fallback for it. Its probability is the one the model
    scores itself, which the label set exists to test.
    """

    def __init__(self, playbook: PlaybookSpec, provider: ProviderProtocol) -> None:
        self._playbook = playbook
        self._provider = provider
        self.name = f"playbook:{playbook.model.provider_id}/{playbook.model.name}"

    def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
        prompt = _QUESTION_PROMPT.format(
            question=question.text,
            answers="\n".join(f"- {k}: {v}" for k, v in question.answers.items()),
            keys=", ".join(question.answers),
        )
        params = self._playbook.model.params
        started = time.monotonic()
        resp = self._provider.chat(
            [Message(role="system", content=prompt), Message(role="user", content=state)],
            model=self._playbook.model.name,
            params=SamplingParams(
                temperature=params.get("temperature"),
                top_p=params.get("top_p"),
                max_tokens=params.get("max_tokens", 512),
                thinking=params.get("thinking"),
                effort=params.get("effort"),
            ),
            timeout_ms=int(timeout_s * 1000),
        )
        parsed, err = _parse_summary_json(resp.content)
        if err is not None or not isinstance(parsed, dict):
            raise JudgmentError(f"{self.name} gave an unreadable answer: {err or parsed!r}")
        answer = str(parsed.get("answer"))
        if answer not in question.answers:
            raise JudgmentError(
                f"{self.name} answered {answer!r}, outside the answer space of {question.version}"
            )
        try:
            probability = float(parsed["probability"])
        except (KeyError, TypeError, ValueError) as e:
            raise JudgmentError(f"{self.name} gave no probability: {e!r}") from e
        if not 0 <= probability <= 1:
            raise JudgmentError(f"probability must be between 0 and 1, not {probability}")
        return Judgment(
            question=question.id,
            version=question.version,
            answer=answer,
            probability=probability,
            engine=self.name,
            latency_ms=int((time.monotonic() - started) * 1000),
            cost_usd=resp.usage.cost_usd,
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
SECURITY_FILE: Final = "d1.yaml"
WORK_ITEM_TYPE_FILE: Final = "d2.yaml"


@dataclass(frozen=True)
class Decision:
    """One decision as the stage asks it: its Question, its measured cut, its engines.

    ``threshold`` is measured on the primary engine's probability, which is
    why an answer from the fallback always goes to a person.
    """

    question: Question
    threshold: float
    primary: JudgmentEngine
    fallback: JudgmentEngine | None = None
    timeout_s: float = JUDGMENT_TIMEOUT_S

    def decide(self, state: str) -> Judgment:
        if self.fallback is None:
            return self.primary.judge(self.question, state, timeout_s=self.timeout_s)
        return judge_with_fallback(
            self.primary, self.fallback, self.question, state, timeout_s=self.timeout_s
        )


def p_yes_of(answer: str, probability: float) -> float:
    """The probability of yes behind a Noul's answer, whichever way it leaned.

    Rounded, because 1 - 0.9 is 0.0999…98 in floating point, and an item on
    decision 1's cut must stop, not slip under it by a rounding error. The
    report measures the cut with this same function.
    """
    return round(probability if answer == "yes" else 1 - probability, 9)


def p_yes(judgment: Judgment) -> float:
    """The probability of yes behind a Noul's Judgment, as the stage cuts on it."""
    return p_yes_of(judgment.answer, judgment.probability)


@dataclass(frozen=True)
class Stage:
    """The Judgments stage as the server runs it; it exists only when it is on.

    Decision 1 runs first on every Work item, declared or not (ADR-0040);
    decision 2 runs only when nothing declared the type.
    """

    # None until decision 1 is measured for the engine that would decide it:
    # measured on the label set, it is not ready to be automated (#225).
    security: Decision | None
    work_item_type: Decision

    def stops_for_security(self, judgment: Judgment) -> bool:
        """At or above decision 1's cut on P(yes), or answered by the fallback: stop.

        The cut is set so every labelled security item reaches a person; a wrong
        "not security" is the one mistake the next step cannot undo, so a
        fallback's "no" is not trusted either.
        """
        assert self.security is not None, "decision 1 is not asked while it is unmeasured"
        return judgment.fallback is not None or p_yes(judgment) >= self.security.threshold

    def needs_a_person(self, judgment: Judgment) -> bool:
        """Decision 2 below its cut, or answered by the fallback: a person picks the type."""
        return judgment.fallback is not None or judgment.probability < self.work_item_type.threshold


def _decision(
    decisions_dir: Path, name: str, primary: JudgmentEngine, fallback: JudgmentEngine | None
) -> Decision:
    """A decision at the threshold measured for the engine that decides it; refused without one.

    A probability is on its engine's own scale, so another engine's cut says
    nothing about this one (#274).
    """
    path = decisions_dir / name
    question = load_question(path)
    threshold = question.thresholds.get(primary.name)
    if threshold is None:
        raise ConfigError(
            f"the Judgments stage is on but {path} has no threshold for {primary.name}. "
            "Measure it on the label set first (judgments/label_set/SPEC.md §7); it is never "
            "guessed, and one measured on another engine says nothing about this one."
        )
    return Decision(question, threshold, primary=primary, fallback=fallback)


def _security(
    decisions_dir: Path, primary: JudgmentEngine, fallback: JudgmentEngine | None
) -> Decision | None:
    """Decision 1 at its engine's measured cut, or None while it has none, and the log says so.

    Unlike decision 2, an unmeasured decision 1 does not stop the stage: on the
    label set no cut stopped the labelled security items without stopping
    nearly every Work item, so it is not ready to be automated (#225). Running
    without it is said loudly, because a security issue then goes unstopped.
    """
    path = decisions_dir / SECURITY_FILE
    question = load_question(path)
    threshold = question.thresholds.get(primary.name)
    if threshold is None:
        logger.warning(
            "The Judgments stage runs WITHOUT decision 1: %s has no threshold for %s, so a "
            "possible security issue is not stopped (#225).",
            path,
            primary.name,
        )
        return None
    return Decision(question, threshold, primary=primary, fallback=fallback)


def build_stage(
    decisions_dir: Path,
    classify_playbook: PlaybookSpec,
    provider: ProviderProtocol,
    *,
    typesafe_api_key: str | None = None,
) -> Stage:
    """The stage with the engines there are; refuse it until decision 2's engine is measured.

    With a TypeSafe key, Jev decides both and the Playbook's model is its
    fallback: Classification for decision 2, the Question asked as written for
    decision 1. Without one, the Playbook's model decides alone, and the log
    says so. Decision 1 runs only once it is measured for its engine.
    """
    asked = QuestionJudge(classify_playbook, provider)
    classified = ClassificationJudge(classify_playbook, provider)
    key = (typesafe_api_key or "").strip()
    if key:
        # Refused here rather than on the first Work item, where it would cost a
        # failed call per item or, outside ASCII, fail the run outright.
        if not (key.isascii() and key.isprintable()) or " " in key:
            raise ConfigError("TYPESAFE_API_KEY is malformed: it holds whitespace or non-ASCII.")
        jev = TypeSafeJudge(key)
        return Stage(
            security=_security(decisions_dir, jev, asked),
            work_item_type=_decision(decisions_dir, WORK_ITEM_TYPE_FILE, jev, classified),
        )
    stage = Stage(
        security=_security(decisions_dir, asked, None),
        work_item_type=_decision(decisions_dir, WORK_ITEM_TYPE_FILE, classified, None),
    )
    logger.warning(
        "The Judgments stage is on without TYPESAFE_API_KEY: %s decides alone.", classified.name
    )
    return stage
