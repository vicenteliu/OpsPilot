"""Distilling a closed Working set into a Skill (ADR-0026, revised by ADR-0036).

ADR-0026 asked for a **loop-shaped** resolution — one converged on by repeated
attempts — and hung it on a **Session**. A Session is one playbook run over one
input producing one artifact; it is harness-shaped by construction. The loop is a
**Working set**: a problem opened, worked across several Consultations, and
closed by the person who decided it was finished.

Two things this deliberately will not do.

**It will not guess the stopping condition or ``allowed_tools``.** ADR-0027 is
specific that those are a Skill's load-bearing content, that a run which went
well never exercised either, and that a Skill whose procedure is excellent and
whose stopping condition is absent is *rejected, not merged with a follow-up
issue*. A guessed stopping condition reads perfectly well, gets skimmed, and gets
merged. **A blank field cannot be rubber-stamped; a filled one can.** So both are
left as placeholders the review cannot miss.

**It will not create a new Skill by default.** One Skill covers a subsystem, not
a single failure: fragmenting the bank is a named failure mode, and the
``load_skill`` catalog rides in context, so a long catalog spends the tokens
progressive disclosure was meant to save. The normal outcome is an *amendment* to
an existing Skill — which is also the more reviewable one, because an amendment
is a diff and a new file has to be read whole.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..providers.types import Message, SamplingParams
from ..skills import Skill, parse_skill_md, write_skill_md

MIN_CONSULTATIONS = 2

TODO_STOP = "<!-- TODO(review): when does this procedure stop? -->"
TODO_TOOLS = "<!-- TODO(review): which tools may this Skill use? -->"
TODO_TRIGGER = "<!-- TODO(review): name the SUBSYSTEM, not this one failure -->"

_STOP_SECTION = f"""## When to stop

{TODO_STOP}
{TODO_TOOLS}

This section is deliberately empty. A transcript of a problem that was solved
never exercised the boundary, so nothing above could have supplied it. Write what
this procedure must **not** do on its own, and where it hands back to a person.
"""

_SYSTEM = """You turn a record of how someone actually worked a problem into a reusable
troubleshooting procedure.

Rules you must follow:

1. Write the PROCEDURE only. Do not invent a stopping condition, and do not
   invent a tools list. Those are supplied by a human reviewer, and a plausible
   guess is worse than a blank.
2. Keep the dead ends. What was ruled out, and in what order, is the most useful
   part of a procedure — a version containing only the steps that worked reads
   like documentation nobody can reproduce.
3. One Skill covers a SUBSYSTEM, not one failure. Write at the level of "storage
   path and array faults", never "the array dropped a path on 2026-08-18".
4. Markdown body only. No YAML frontmatter, no ``allowed_tools``, no
   "When to stop" section — those are added around your output.

Return only the markdown body."""

_AMEND_SYSTEM = """You are revising an existing troubleshooting Skill using a record of how
someone recently worked a problem in the same subsystem.

Rules you must follow:

1. Return the COMPLETE revised markdown body. It will be diffed against the
   current one, so change what should change and leave the rest byte-identical.
2. Prefer correcting or sharpening an existing step over appending a new
   section. A Skill that only ever grows by accretion becomes unreadable.
3. Do not touch the stopping condition or the tools list; they are not yours.
4. Keep the dead ends the record shows — knowing what to rule out is the point.

Return only the markdown body."""


@dataclass(frozen=True)
class DistillationInput:
    """A closed Working set and the conversations worked under it."""

    working_set_id: str
    title: str
    scope: str | None
    transcript: str
    consultations: int


class NotDistillableError(Exception):
    """The Working set does not describe a converged loop."""


def gather(working_sets: Any, consultations: Any, working_set_id: str) -> DistillationInput:
    """Collect the chain, refusing anything that was not converged on.

    A set closed by the **inactivity fallback** was abandoned, not solved, and an
    abandoned investigation has no procedure in it. A chain shorter than
    ``MIN_CONSULTATIONS`` was a question, not a loop.
    """
    ws = working_sets.get(working_set_id)
    if ws is None:
        raise KeyError(f"working set {working_set_id!r} not found")
    if ws.is_open:
        raise NotDistillableError("still open — close it when the problem is done")
    if ws.closed_reason != "manual":
        raise NotDistillableError(
            "closed by the inactivity fallback, which means abandoned rather than solved"
        )
    chain = consultations.for_working_set(working_set_id)
    if len(chain) < MIN_CONSULTATIONS:
        raise NotDistillableError(
            f"{len(chain)} conversation(s) — a loop needs at least {MIN_CONSULTATIONS}"
        )

    parts: list[str] = []
    for con in chain:
        parts.append(f"### Conversation: {con.title or con.id}")
        for msg in consultations.messages(con.id):
            who = "Operator" if msg.role == "user" else "Assistant"
            parts.append(f"{who}: {msg.content}")
    return DistillationInput(
        working_set_id=working_set_id,
        title=ws.title,
        scope=ws.scope,
        transcript="\n\n".join(parts),
        consultations=len(chain),
    )


def draft(
    provider: Any,
    source: DistillationInput,
    *,
    model_name: str,
    amends: Skill | None = None,
) -> Skill:
    """Draft a Skill — new, or a full revision of *amends* — with blanks intact.

    The most judgement-heavy generation this product does: its output is not a
    summary for a person but text that will steer another agent. It runs once per
    closed Working set, so the model is chosen for judgement rather than cost.
    """
    if amends is not None:
        user = (
            f"Current Skill body:\n\n{amends.body}\n\n"
            f"---\n\nRecord of the problem just worked "
            f"(working set: {source.title}"
            + (f", at {source.scope}" if source.scope else "")
            + f"):\n\n{source.transcript}"
        )
        system = _AMEND_SYSTEM
    else:
        user = (
            f"Working set: {source.title}"
            + (f" (at {source.scope})" if source.scope else "")
            + f"\n\nRecord of how it was worked:\n\n{source.transcript}"
        )
        system = _SYSTEM

    resp = provider.chat(
        [Message(role="system", content=system), Message(role="user", content=user)],
        model=model_name,
        params=SamplingParams(max_tokens=4000),
    )
    body = str(resp.content or "").strip()
    if not body:
        raise NotDistillableError("the model returned nothing")

    if amends is not None:
        return Skill(
            id=amends.id,
            name=amends.name,
            trigger=amends.trigger,
            body=body,
            # Untouched: an amendment does not get to widen what the Skill may do.
            allowed_tools=list(amends.allowed_tools),
            trust=amends.trust,
        )
    return Skill(
        id=_slug(source.title),
        name=source.title,
        # The title came from a Working set, which names one investigation. A
        # Skill covers a subsystem, so both the name and the trigger are the
        # reviewer's to widen — the draft says so rather than guessing.
        trigger=f"{TODO_TRIGGER} Drafted from the working set “{source.title}”.",
        body=f"{body}\n\n{_STOP_SECTION}",
        allowed_tools=[],
        trust="internal",
    )


def stage(skill: Skill, staging_dir: Path) -> Path:
    """Write the draft where a human picks it up. Writing is not admitting.

    A file on disk produces no commit and no diff; moving it into
    ``agent_skills/`` is the commit, and that commit is the admission (ADR-0027).
    """
    staging_dir.mkdir(parents=True, exist_ok=True)
    return write_skill_md(staging_dir, skill)


def load_existing(skills_dir: Path, skill_id: str) -> Skill:
    path = skills_dir / skill_id / "SKILL.md"
    if not path.is_file():
        raise KeyError(f"no Skill {skill_id!r} in {skills_dir}")
    return parse_skill_md(path.read_text(encoding="utf-8"), fallback_id=skill_id)


def _slug(raw: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in raw.strip()]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:60] or "untitled-skill"
