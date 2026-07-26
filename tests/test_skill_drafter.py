"""AI skill drafting — draft a SKILL.md from a description (issue #123)."""

from __future__ import annotations

from typing import Any

import pytest

from opspilot.providers.types import ChatResponse, Usage
from opspilot.skill_drafter import SkillDraftError, draft_skill
from opspilot.skills import parse_skill_md, write_skill_md


class FakeProvider:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, *, model, params, tools=None, timeout_ms=90_000):  # type: ignore[no-untyped-def]
        self.calls.append({"messages": list(messages), "model": model})
        return ChatResponse(content=self._content, finish_reason="stop", usage=Usage())


_JSON = """```json
{
  "id": "VPN Auth!!",
  "name": "VPN authentication failures",
  "trigger": "A user cannot authenticate to the VPN.",
  "allowed_tools": ["kb_search", "rm_rf"],
  "body": "# Steps\\n\\n1. Check the account.\\n2. Check MFA."
}
```"""


def test_draft_parses_fenced_json_and_slugifies_id() -> None:
    p = FakeProvider(_JSON)
    skill = draft_skill(
        p, model_name="m", description="vpn login fails", allowed_tools=["kb_search"]
    )
    assert skill.id == "vpn-auth"  # slugified from "VPN Auth!!"
    assert skill.name == "VPN authentication failures"
    assert skill.trigger.startswith("A user cannot authenticate")
    assert skill.allowed_tools == ["kb_search"]  # "rm_rf" dropped (not allowed)
    assert "Check MFA" in skill.body
    assert skill.trust == "internal"


def test_draft_is_schema_valid_and_editable(tmp_path: Any) -> None:
    # The draft round-trips through the real SKILL.md serializer/parser →
    # it can be saved by the editor unchanged.
    p = FakeProvider(_JSON)
    skill = draft_skill(p, model_name="m", description="vpn", allowed_tools=["kb_search"])
    path = write_skill_md(tmp_path, skill)
    back = parse_skill_md(path.read_text(encoding="utf-8"), fallback_id=skill.id)
    assert back.id == skill.id
    assert back.allowed_tools == ["kb_search"]


def test_draft_includes_conversation_when_given() -> None:
    p = FakeProvider(_JSON)
    draft_skill(
        p,
        model_name="m",
        description="d",
        allowed_tools=["kb_search"],
        conversation=[
            {"role": "user", "content": "vpn broke"},
            {"role": "assistant", "content": "reset it"},
        ],
    )
    user_msg = p.calls[0]["messages"][1].content
    assert "vpn broke" in user_msg and "reset it" in user_msg


def test_draft_rejects_non_json() -> None:
    with pytest.raises(SkillDraftError):
        draft_skill(
            FakeProvider("sorry, I can't"), model_name="m", description="d", allowed_tools=[]
        )


def test_draft_rejects_missing_body() -> None:
    with pytest.raises(SkillDraftError):
        draft_skill(
            FakeProvider('{"id": "x", "name": "X", "trigger": "t", "allowed_tools": []}'),
            model_name="m",
            description="d",
            allowed_tools=[],
        )
