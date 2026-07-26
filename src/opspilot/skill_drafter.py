"""Draft a SKILL.md from a problem description with the LLM (ADR-0022, #123).

The admin describes a common problem (optionally with a resolved conversation)
and the assistant drafts a Skill — id, name, "use-when" trigger, allowed tools,
and a procedure body. The draft is *never* written to disk here: it pre-fills
the admin skill editor for review and save (via the existing PUT). See ADR-0022.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .providers.base import ProviderProtocol
from .providers.types import Message, SamplingParams
from .skills import Skill


class SkillDraftError(Exception):
    """The model did not return a usable skill draft."""


_DRAFT_SYSTEM = (
    "You are OpsPilot's skill author. Given an IT problem, draft a reusable "
    "troubleshooting skill. Reply with ONLY a JSON object, no prose, with keys:\n"
    '  "id": a short kebab-case slug (a-z, 0-9, hyphens),\n'
    '  "name": a short human title,\n'
    '  "trigger": one sentence describing when to use this skill,\n'
    '  "allowed_tools": an array drawn only from the allowed tools given below,\n'
    '  "body": a Markdown numbered troubleshooting procedure.\n'
    "The procedure should suggest, not decide — a human operator stays in control."
)

_FENCE_RE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(raw: str, *, fallback: str) -> str:
    s = _SLUG_RE.sub("-", raw.strip().lower()).strip("-")
    return (s or _SLUG_RE.sub("-", fallback.strip().lower()).strip("-") or "new-skill")[:64]


def _extract_json(content: str) -> dict[str, Any]:
    text = _FENCE_RE.sub("", content or "").strip()
    if not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            text = m.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise SkillDraftError(f"model did not return valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise SkillDraftError("model returned non-object JSON")
    return data


def _render_conversation(messages: list[dict[str, str]]) -> str:
    lines = [
        f"{m.get('role', '?')}: {m.get('content', '')}"
        for m in messages
        if m.get("role") in ("user", "assistant")
    ]
    return "\n".join(lines)


def draft_skill(
    provider: ProviderProtocol,
    *,
    model_name: str,
    description: str,
    allowed_tools: list[str],
    conversation: list[dict[str, str]] | None = None,
) -> Skill:
    """Ask *provider* to draft a Skill. Raises SkillDraftError on bad output.

    ``allowed_tools`` is the set the draft may reference; anything the model
    invents outside it is dropped. The returned Skill is a draft (trust
    ``internal``) for the editor — nothing is written to disk.
    """
    user = f"Problem description:\n{description.strip()}\n"
    if conversation:
        rendered = _render_conversation(conversation)
        if rendered:
            user += f"\nRelevant conversation:\n{rendered}\n"
    user += (
        f"\nAllowed tools (use only these in allowed_tools): {', '.join(allowed_tools) or 'none'}."
    )

    resp = provider.chat(
        [Message(role="system", content=_DRAFT_SYSTEM), Message(role="user", content=user)],
        model=model_name,
        params=SamplingParams(temperature=0.3, max_tokens=1500),
    )
    data = _extract_json(resp.content)

    body = str(data.get("body") or "").strip()
    if not body:
        raise SkillDraftError("draft is missing a procedure body")
    name = str(data.get("name") or "").strip() or "Untitled skill"
    tools = [t for t in (data.get("allowed_tools") or []) if t in allowed_tools]
    return Skill(
        id=_slug(str(data.get("id") or ""), fallback=name),
        name=name,
        trigger=str(data.get("trigger") or "").strip(),
        body=body,
        allowed_tools=tools,
        trust="internal",
    )
