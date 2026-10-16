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
import re
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol

import httpx
import yaml

from .errors import ConfigError, OpsPilotError
from .orchestrator.classify import VALID_TYPES, classify_state
from .orchestrator.ticket_summary import _parse_summary_json
from .orchestrator.types import PlaybookSpec
from .providers.base import ProviderProtocol
from .providers.pricing import estimate_cost_usd
from .providers.types import Message, SamplingParams
from .redaction import Redactor

if TYPE_CHECKING:
    from .catalog import CatalogDecision

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
    # A Choice whose answers are found per Work item (decision 3, #230): what
    # each found answer means, "{text}" standing for what it says. The file's
    # own answers, such as "none", follow them.
    candidates: str | None = None


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
    candidates = data.get("candidates")
    if candidates is not None and (kind != "choice" or "{text}" not in str(candidates)):
        raise JudgmentError(f"{path}: only a choice has candidates, and their meaning has {{text}}")
    # A Choice over candidates has its own answers as well, found per Work item.
    if len(answers) < (1 if candidates else 2):
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
        candidates=str(candidates) if candidates is not None else None,
    )


def with_candidates(question: Question, found: dict[str, str]) -> Question:
    """A Choice over the answers found for one Work item, then the file's own (#230).

    ``found`` maps each answer, e.g. an open Work item's key, to what it says.
    """
    if question.candidates is None:
        raise JudgmentError(f"{question.version} takes no candidates")
    if clash := sorted(found.keys() & question.answers.keys()):
        raise JudgmentError(f"a candidate is named like an answer of its own: {', '.join(clash)}")
    meaning = question.candidates
    return replace(
        question,
        answers={**{k: meaning.format(text=t) for k, t in found.items()}, **question.answers},
    )


# What an open Work item says, at most, as an answer to decision 3: the label
# set's items run to 150 words, and a pasted log should not cost a call more.
OPEN_ITEM_CHARS: Final = 1000


def open_items_question(
    question: Question, open_items: list[dict[str, Any]], redactor: Redactor
) -> Question:
    """Decision 3 asked of one Work item: its open Work items, redacted, then `none` (#230).

    Each open Work item is an answer keyed by its key, meaning its subject and
    body, cut at ``OPEN_ITEM_CHARS``; the label set and the run build it here,
    so both ask the same thing.
    """
    found = {}
    for o in open_items:
        text = f"{o.get('subject') or ''}\n{o.get('body') or ''}".strip()
        found[str(o["key"])] = redactor.redact(text[:OPEN_ITEM_CHARS]).text
    return with_candidates(question, found)


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
    is, and the threshold and the Brier score are both stated on p. A Score's
    answer is its likeliest level, not the response's ``score``: that is the
    probability-weighted level, which can fall between two of them.

    One attempt and no retries: a failure is what the fallback is for, and a
    retry spends time a person is waiting through.
    """

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client()
        self.name = f"typesafe:{JEV_MODEL}"

    def judge(self, question: Question, state: str, *, timeout_s: float) -> Judgment:
        criteria: dict[str, str] | list[str]
        if question.kind == "choice":
            criteria = question.answers
        elif question.kind == "noul":
            criteria = {"true": question.answers["yes"], "false": question.answers["no"]}
        else:
            # A Score's levels are its answers' meanings in the file's order,
            # which Jev numbers from 0.
            criteria = list(question.answers.values())
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
            elif question.kind == "score":
                levels = list(question.answers)
                by_level = {int(n): float(p) for n, p in answer["probabilities"].items()}
                level = max(by_level, key=by_level.__getitem__)
                if not 0 <= level < len(levels):
                    raise JudgmentError(
                        f"answered level {level}, outside the answer space of {question.version}"
                    )
                choice, probability = levels[level], by_level[level]
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
REALLY_FILE: Final = "r2.yaml"
ALREADY_OPEN_FILE: Final = "d3.yaml"
ENOUGH_FILE: Final = "d4.yaml"
TEAM_FILE: Final = "d6.yaml"
IMPACT_FILE: Final = "d7.yaml"
URGENCY_FILE: Final = "d8.yaml"
# A Lookup, not a Question, kept beside the decisions it reads (ADR-0040).
SEVERITY_FILE: Final = "severity.yaml"


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

    def decide(self, state: str, question: Question | None = None) -> Judgment:
        """Ask the decision's question, or ``question``: the same one over found answers (#230)."""
        asked = question or self.question
        if self.fallback is None:
            return self.primary.judge(asked, state, timeout_s=self.timeout_s)
        return judge_with_fallback(
            self.primary, self.fallback, asked, state, timeout_s=self.timeout_s
        )

    def stands(self, judgment: Judgment) -> bool:
        """At or above the cut, from the primary engine: the answer stands without a person."""
        return judgment.fallback is None and judgment.probability >= self.threshold


@dataclass(frozen=True)
class SeverityTable:
    """Severity as a Lookup over Impact × Urgency, P0–P4 (ADR-0040).

    Its values are policy, so they live in the file, not in code.
    """

    cells: dict[tuple[str, str], str]  # (impact, urgency) → P0…P4

    def read(self, impact: str, urgency: str) -> str:
        return self.cells[(impact, urgency)]


_SEVERITY: Final = re.compile(r"P[0-4]")


def load_severity_table(path: Path, impact: Question, urgency: Question) -> SeverityTable:
    """Read the Severity table; refuse one that does not give every pair a P0–P4."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    table = data.get("severity") or {}
    if not isinstance(table, dict) or set(table) != set(impact.answers):
        raise JudgmentError(f"{path}: severity needs a row for each impact: {list(impact.answers)}")
    cells: dict[tuple[str, str], str] = {}
    for i in impact.answers:
        row = table[i] or {}
        if not isinstance(row, dict) or set(row) != set(urgency.answers):
            raise JudgmentError(
                f"{path}: {i} needs a value for each urgency: {list(urgency.answers)}"
            )
        for u in urgency.answers:
            if not (isinstance(row[u], str) and _SEVERITY.fullmatch(row[u])):
                raise JudgmentError(f"{path}: {i} × {u} must be one of P0–P4, not {row[u]!r}")
            cells[(i, u)] = row[u]
    return SeverityTable(cells)


@dataclass(frozen=True)
class Severity:
    """Impact (7) and Urgency (8), and the table that reads Severity off them (#227)."""

    impact: Decision
    urgency: Decision
    table: SeverityTable

    def decide(self, state: str) -> tuple[str | None, list[Judgment]]:
        """Severity from the table, or None when either Judgment cannot stand alone.

        Each must clear its cut and come from its primary engine, the rule a
        type follows. Below that, the summary Playbook suggests a Severity as it
        did before the stage, rather than the run waiting for a person.
        """
        judged = [(d, d.decide(state)) for d in (self.impact, self.urgency)]
        if not all(d.stands(j) for d, j in judged):
            return None, [j for _, j in judged]
        (_, impact), (_, urgency) = judged
        return self.table.read(impact.answer, urgency.answer), [impact, urgency]


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
    # Asked of an Incident before its summary; None until Impact and Urgency
    # are both measured for the engine that would decide them (#227).
    severity: Severity | None = None
    # Asked of an Incident before its summary; None until measured (#228).
    team: Decision | None = None
    # Asked of an Incident first, once: a `no` that stands means the reporter
    # is asked before any summary (decision 5); None until measured (#229).
    enough: Decision | None = None
    # Asked of an Incident a source offers open Work items for; a match that
    # stands is named for a person to link. None until measured (#230).
    already_open: Decision | None = None
    # The request path: which catalog item, over the catalog its Lookups read;
    # None until measured for its engine on this catalog (#231).
    catalog: CatalogDecision | None = None
    # The request path, then: is it really a request, or an incident or a
    # change filed as one? None until measured (#293).
    really: Decision | None = None

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


def _measured(
    decisions_dir: Path, name: str, primary: JudgmentEngine, fallback: JudgmentEngine | None
) -> Decision | None:
    """A decision at its engine's measured cut, or None while it has none."""
    question = load_question(decisions_dir / name)
    threshold = question.thresholds.get(primary.name)
    if threshold is None:
        return None
    return Decision(question, threshold, primary=primary, fallback=fallback)


def _severity(
    decisions_dir: Path, primary: JudgmentEngine, fallback: JudgmentEngine | None
) -> Severity | None:
    """Impact and Urgency at their engine's measured cuts, with the table; None while unmeasured.

    Like decision 1, an unmeasured Severity does not stop the stage: the
    summary Playbook suggests one, as it did before, and the log says so.
    """
    impact = _measured(decisions_dir, IMPACT_FILE, primary, fallback)
    urgency = _measured(decisions_dir, URGENCY_FILE, primary, fallback)
    if impact is None or urgency is None:
        logger.warning(
            "The Judgments stage runs WITHOUT Severity: %s has no threshold for %s, so the "
            "summary Playbook suggests one (#227).",
            decisions_dir / (IMPACT_FILE if impact is None else URGENCY_FILE),
            primary.name,
        )
        return None
    table = load_severity_table(decisions_dir / SEVERITY_FILE, impact.question, urgency.question)
    return Severity(impact, urgency, table)


def _already_open(
    decisions_dir: Path, primary: JudgmentEngine, fallback: JudgmentEngine | None
) -> Decision | None:
    """Decision 3 at its engine's measured cut, or None while it has none, and the log says so.

    Unmeasured, no Work item is named as already open.
    """
    already_open = _measured(decisions_dir, ALREADY_OPEN_FILE, primary, fallback)
    if already_open is None:
        logger.warning(
            "The Judgments stage runs WITHOUT decision 3: %s has no threshold for %s, so no "
            "open Work item is named as the same problem (#230).",
            decisions_dir / ALREADY_OPEN_FILE,
            primary.name,
        )
    return already_open


def _catalog(
    decisions_dir: Path, primary: JudgmentEngine, fallback: JudgmentEngine | None
) -> CatalogDecision | None:
    """Which catalog item at its engine's measured cut, or None, and the log says so (#231).

    Unmeasured, or measured on another catalog, every request runs its Playbook
    as before, and a person checks the item and its approval.
    """
    from .catalog import (
        CATALOG_FILE,
        CATALOG_ITEM_FILE,
        CatalogDecision,
        catalog_question,
        load_catalog,
    )

    try:
        catalog = load_catalog(decisions_dir / CATALOG_FILE)
        question = catalog_question(decisions_dir / CATALOG_ITEM_FILE, catalog)
    except JudgmentError as e:
        logger.warning("The Judgments stage runs WITHOUT the catalog: %s (#231).", e)
        return None
    threshold = question.thresholds.get(primary.name)
    if threshold is None:
        logger.warning(
            "The Judgments stage runs WITHOUT the catalog: %s has no threshold for %s, so a "
            "person checks each request's item and approval (#231).",
            decisions_dir / CATALOG_ITEM_FILE,
            primary.name,
        )
        return None
    return CatalogDecision(
        Decision(question, threshold, primary=primary, fallback=fallback), catalog
    )


def _really(
    decisions_dir: Path, primary: JudgmentEngine, fallback: JudgmentEngine | None
) -> Decision | None:
    """r2 at its engine's measured cut, or None while it has none, and the log says so (#293).

    Unmeasured, whatever is filed as a request stays on the request path.
    """
    really = _measured(decisions_dir, REALLY_FILE, primary, fallback)
    if really is None:
        logger.warning(
            "The Judgments stage runs WITHOUT r2: %s has no threshold for %s, so whatever is "
            "filed as a request stays one (#293).",
            decisions_dir / REALLY_FILE,
            primary.name,
        )
    return really


def _enough(
    decisions_dir: Path, primary: JudgmentEngine, fallback: JudgmentEngine | None
) -> Decision | None:
    """Decision 4 at its engine's measured cut, or None while it has none, and the log says so.

    Unmeasured, no reporter is asked: every Incident goes straight to its summary.
    """
    enough = _measured(decisions_dir, ENOUGH_FILE, primary, fallback)
    if enough is None:
        logger.warning(
            "The Judgments stage runs WITHOUT decision 4: %s has no threshold for %s, so no "
            "reporter is asked for what is missing (#229).",
            decisions_dir / ENOUGH_FILE,
            primary.name,
        )
    return enough


def _team(
    decisions_dir: Path, primary: JudgmentEngine, fallback: JudgmentEngine | None
) -> Decision | None:
    """Decision 6 at its engine's measured cut, or None while it has none, and the log says so.

    Unmeasured, the summary Playbook writes its own escalation hint, as before.
    """
    team = _measured(decisions_dir, TEAM_FILE, primary, fallback)
    if team is None:
        logger.warning(
            "The Judgments stage runs WITHOUT decision 6: %s has no threshold for %s, so the "
            "summary Playbook writes its own escalation hint (#228).",
            decisions_dir / TEAM_FILE,
            primary.name,
        )
    return team


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
    says so. Decision 1, already open, enough to act on, the team, Impact and
    Urgency, the catalog item and really a request run only once they are
    measured for their engine.
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
            severity=_severity(decisions_dir, jev, asked),
            team=_team(decisions_dir, jev, asked),
            enough=_enough(decisions_dir, jev, asked),
            already_open=_already_open(decisions_dir, jev, asked),
            catalog=_catalog(decisions_dir, jev, asked),
            really=_really(decisions_dir, jev, asked),
        )
    stage = Stage(
        security=_security(decisions_dir, asked, None),
        work_item_type=_decision(decisions_dir, WORK_ITEM_TYPE_FILE, classified, None),
        severity=_severity(decisions_dir, asked, None),
        team=_team(decisions_dir, asked, None),
        enough=_enough(decisions_dir, asked, None),
        already_open=_already_open(decisions_dir, asked, None),
        catalog=_catalog(decisions_dir, asked, None),
        really=_really(decisions_dir, asked, None),
    )
    logger.warning(
        "The Judgments stage is on without TYPESAFE_API_KEY: %s decides alone.", classified.name
    )
    return stage
