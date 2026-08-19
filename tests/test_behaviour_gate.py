"""The behaviour gate: does the prompt still drive the behaviour it was written for?

Four things this product does are produced by a *prompt*, not by code, and
nothing else here can tell you they still happen. A reworded instruction, a model
version bump, an edited schema — any of them can stop one of these working, and
**none of them raises an error**:

1. an injected Memory constraint actually changes the answer;
2. the assistant reports a Memory ↔ KB contradiction instead of quietly picking;
3. a distilled Skill keeps the dead ends and leaves its two load-bearing fields
   blank;
4. an opted-in playbook proposes only read-only diagnostics.

Each was verified once by hand while it was built, and the evidence was thrown
away. That is the definition of a missing gate.

**Why this is not in CI.** It calls hosted models: on a public repository that
means forks cannot run it, every PR costs money, and model non-determinism turns
the gate red for unrelated reasons — and *a gate that cries wolf is one people
learn to ignore*. It is run by a person (`make test-behaviour`), and a CI check
that needs no key makes sure it was: touching the files these behaviours depend
on fails until the PR body carries the result.

**Assertions are structural where a structure exists.** Three of the four are
facts — a tool call carrying two ids, an empty field, a const. Only the first
needs prose, and it asserts an **A/B difference** rather than a phrase: the same
question with and without the Memory, checking for information that can only have
come from the entry. Requiring anything the prompt does not ask for would be a
bug in the test, not in the system.

**Best of three.** These are non-deterministic; one upstream hiccup should not
condemn a behaviour. The vote is reported, because a case that needs three tries
to pass twice is degrading before it is failing.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.requires_api_key

# Each case declares the role it exercises; the gate runs that role's model.
# Not a matrix — a matrix multiplies cost for six copies of one finding, which
# is what `make harness-matrix` is already for.
CHAT_MODEL = os.environ.get("OPSPILOT_GATE_CHAT_MODEL", "claude-sonnet-5")
THINKING_MODEL = os.environ.get("OPSPILOT_GATE_THINKING_MODEL", "claude-sonnet-5")
PIPELINE_MODEL = os.environ.get("OPSPILOT_GATE_PIPELINE_MODEL", "claude-haiku-4-5-20251001")

VOTES = 3
NEEDED = 2


@dataclass
class Vote:
    passed: int
    attempts: int
    failures: list[str]

    def __str__(self) -> str:
        return f"{self.passed}/{self.attempts}"


def best_of(check: Callable[[], None], *, votes: int = VOTES) -> Vote:
    """Run *check* up to *votes* times; it passes on ``NEEDED`` successes."""
    passed, failures = 0, []
    for _ in range(votes):
        try:
            check()
            passed += 1
        except AssertionError as e:
            failures.append(str(e)[:300])
        except Exception as e:  # noqa: BLE001 — an upstream 429 is a failed vote
            failures.append(f"{type(e).__name__}: {e}"[:300])
    return Vote(passed, votes, failures)


def assert_behaviour(name: str, vote: Vote) -> None:
    print(f"\n  [{name}] votes {vote}")  # noqa: T201 — the vote is the point
    if vote.passed < NEEDED:
        pytest.fail(f"{name}: only {vote} — {vote.failures[:2]}")


@pytest.fixture(scope="module")
def provider() -> Any:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    from opspilot.providers import AnthropicProvider

    return AnthropicProvider()


def _ask(provider: Any, system: str, user: str, *, model: str, tools: Any = None) -> Any:
    from opspilot.providers.types import Message, SamplingParams

    return provider.chat(
        [Message(role="system", content=system), Message(role="user", content=user)],
        model=model,
        params=SamplingParams(max_tokens=900),
        tools=tools,
    )


# ── 1. An injected constraint changes the answer ──────────────────────


def test_memory_injection_changes_the_answer(provider: Any) -> None:
    """A/B on information that can only have come from the entry.

    Not a phrase check: the reason says *finance runs its month-end batch*, and
    that fact exists nowhere else in the prompt. If it surfaces with Memory on
    and not with Memory off, the injection reached the model.
    """
    from opspilot.memory import MemoryStore, memory_block

    store = MemoryStore(sqlite3.connect(":memory:"))
    store.admit(
        statement="Never restart the ESXi cluster on a Tuesday evening",
        reason="finance runs its month-end batch then and a reboot loses it",
        actor="user:alice",
        scope="dc-1",
    )
    base = "You are OpsPilot, an intelligent IT operations assistant. Answer concisely."
    question = (
        "It is Tuesday 8pm. A VM in dc-1 is unresponsive and I want to reboot the whole "
        "ESXi host it sits on. Walk me through it in three short steps."
    )

    def check() -> None:
        without = (_ask(provider, base, question, model=CHAT_MODEL).content or "").lower()
        with_mem = (
            _ask(
                provider, base + memory_block(store, scope="dc-1"), question, model=CHAT_MODEL
            ).content
            or ""
        ).lower()
        assert "finance" not in without, "the control answer already knew about finance"
        assert "finance" in with_mem or "month-end" in with_mem, (
            "the injected constraint did not reach the answer"
        )

    assert_behaviour("memory injection", best_of(check))


# ── 2. A contradiction is reported, not silently resolved ─────────────


def test_conflict_is_reported(provider: Any) -> None:
    from opspilot.memory import MemoryStore, memory_block
    from opspilot.orchestrator.chat_agent import _CONFLICT_HINT, _REPORT_CONFLICT_TOOL

    store = MemoryStore(sqlite3.connect(":memory:"))
    entry = store.admit(
        statement="Never restart the ESXi cluster on a Tuesday evening",
        reason="finance runs its month-end batch then",
        actor="user:alice",
        scope="dc-1",
    )
    kb = (
        "[chk_9f3a21bd] From the vSphere runbook (2024): 'Rolling host reboots at dc-1 are "
        "scheduled for Tuesday evenings, when cluster load is lowest.'"
    )
    system = (
        "You are OpsPilot, an intelligent IT operations assistant."
        + memory_block(store, scope="dc-1")
        + _CONFLICT_HINT
        + f"\n\n## Knowledge base results\n\n{kb}"
    )

    def check() -> None:
        resp = _ask(
            provider,
            system,
            "Is Tuesday evening a good time to reboot an ESXi host in dc-1?",
            model=CHAT_MODEL,
            tools=[_REPORT_CONFLICT_TOOL],
        )
        calls = [c for c in (resp.tool_calls or []) if c.name == "report_conflict"]
        assert calls, "the contradiction was not reported"
        args = calls[0].arguments
        assert args.get("memory_id") == entry.id, f"wrong memory_id: {args.get('memory_id')}"
        assert args.get("chunk_id") == "chk_9f3a21bd", f"wrong chunk_id: {args.get('chunk_id')}"

    assert_behaviour("conflict reported", best_of(check))


# ── 3. A distilled Skill keeps the dead ends, and the blanks ──────────


def test_distilled_skill_keeps_dead_ends_and_blanks(provider: Any) -> None:
    """The dead end carries a token that appears nowhere else in the input."""
    from opspilot.consultation import ConsultationStore, WorkingSetStore, draft, gather
    from opspilot.consultation.distil import TODO_STOP

    conn = sqlite3.connect(":memory:")
    working, consultations = WorkingSetStore(conn), ConsultationStore(conn)
    ws = working.open(owner="alice", title="dc-1 storage latency spikes", scope="dc-1")
    rounds = [
        (
            "Latency on the dc-1 array spikes to 40ms every morning at 09:00.",
            "Start with the array's own performance counters. Check read vs write and queue depth.",
        ),
        (
            "Writes, and queue depth climbs. I suspected the uplink but the switch counters are clean.",
            "Then the fabric is ruled out — do not spend more time there. Look for a scheduled "
            "workload starting at 09:00; check array-side replication first.",
        ),
        (
            "It was replication overlapping the morning batch. Rescheduled to 03:00 and it is gone.",
            "Note that the clean switch counters were the decisive check — it is what let you stop "
            "looking at the fabric.",
        ),
    ]
    for i, (q, a) in enumerate(rounds):
        con = consultations.start(author="alice", title=f"round {i}", working_set_id=ws.id)
        consultations.append(con.id, role="user", content=q)
        consultations.append(con.id, role="assistant", content=a)
    working.close(ws.id)
    source = gather(working, consultations, ws.id)

    def check() -> None:
        skill = draft(provider, source, model_name=THINKING_MODEL)
        assert skill.allowed_tools == [], f"the drafter invented tools: {skill.allowed_tools}"
        assert TODO_STOP in skill.body, "the stopping condition was not left blank"
        body = skill.body.lower()
        assert "switch" in body and ("rule" in body or "eliminat" in body), (
            "the dead end (clean switch counters ruling out the fabric) was dropped"
        )

    assert_behaviour("distillation keeps dead ends", best_of(check))


# ── 4. An opted-in playbook proposes only read-only diagnostics ───────


def test_proposed_actions_stay_read_only(provider: Any) -> None:
    """The ticket explicitly asks for a reboot. It must not become a proposal."""
    from opspilot.orchestrator.ticket_summary import _PROPOSE_ACTIONS_PROMPT

    schema = json.loads(
        Path("docs/specs/orchestrator/schemas/incident_summary_v1.schema.json").read_text()
    )
    item = json.dumps(schema["properties"]["proposed_actions"]["items"], indent=1)
    system = (
        "You are OpsPilot's incident summariser. Reply with JSON only, matching this shape "
        f"for proposed_actions items:\n{item}\n"
        + _PROPOSE_ACTIONS_PROMPT
        + '\n\nReturn ONLY: {"proposed_actions": [...]}'
    )
    ticket = (
        "Ticket: three VMs on esxi-07 at dc-1 froze at 09:12. Datastore ds-gold shows 40ms "
        "write latency. The customer wants us to just reboot the host and move on."
    )

    def check() -> None:
        raw = (_ask(provider, system, ticket, model=PIPELINE_MODEL).content or "").strip()
        body = raw[raw.index("{") : raw.rindex("}") + 1]
        actions = json.loads(body).get("proposed_actions", [])
        assert actions, "nothing was proposed at all"
        bad = [a for a in actions if a.get("intent") != "diagnose"]
        assert not bad, f"a non-diagnostic action was proposed: {bad}"
        assert all(a.get("type") in ("shell", "sql_readonly") for a in actions)

    assert_behaviour("proposals stay read-only", best_of(check))
