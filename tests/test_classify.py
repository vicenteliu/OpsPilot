"""Tests for opspilot.orchestrator.classify (#6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from opspilot.errors import SchemaError
from opspilot.orchestrator.classify import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    classify_work_item,
    declared_type,
)
from opspilot.orchestrator.types import load_playbook
from opspilot.providers.types import ChatResponse, Usage
from opspilot.redaction import Redactor

REPO_ROOT = Path(__file__).resolve().parents[1]
CLASSIFY_PB = REPO_ROOT / "playbooks" / "pb_classify_work_item_zh"


class _FakeProvider:
    provider_id = "fake"
    kind = "fake"

    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[Any] = []

    def chat(self, messages: Any, *, model: str, params: Any, tools: Any = None,
             timeout_ms: int = 90_000) -> ChatResponse:
        self.calls.append(messages)
        return ChatResponse(
            content=self._content,
            finish_reason="stop",
            tool_calls=None,
            usage=Usage(input_tokens=50, output_tokens=20, cost_usd=0.0),
        )

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        return [[0.0]]

    def health_probe(self) -> bool:
        return True


def _ticket(tmp_path: Path, **extra: Any) -> Path:
    t = {"ticket_id": "T-1", "subject": "VPN 连不上",
         "body": "上午起多人无法连接 VPN", **extra}
    p = tmp_path / "ticket.json"
    p.write_text(json.dumps(t), encoding="utf-8")
    return p


def _classify(tmp_path: Path, content: str):
    provider = _FakeProvider(content)
    pb = load_playbook(CLASSIFY_PB)
    return classify_work_item(
        _ticket(tmp_path), playbook=pb, provider=provider, redactor=Redactor.from_yaml()
    )


def test_classify_incident_high_confidence(tmp_path: Path) -> None:
    res = _classify(tmp_path, json.dumps(
        {"work_item_type": "incident", "confidence": 0.9, "rationale": "服务中断"}))
    assert res.work_item_type == "incident"
    assert res.confidence == 0.9
    assert res.confidence >= DEFAULT_CONFIDENCE_THRESHOLD


def test_classify_service_request_low_confidence(tmp_path: Path) -> None:
    res = _classify(tmp_path, json.dumps(
        {"work_item_type": "service_request", "confidence": 0.4, "rationale": "申请权限"}))
    assert res.work_item_type == "service_request"
    assert res.confidence < DEFAULT_CONFIDENCE_THRESHOLD


def test_classify_rejects_unknown_type(tmp_path: Path) -> None:
    with pytest.raises(SchemaError):
        _classify(tmp_path, json.dumps(
            {"work_item_type": "problem", "confidence": 0.9, "rationale": "x"}))


def test_declared_type() -> None:
    assert declared_type({"work_item_type": "incident"}) == "incident"
    assert declared_type({"work_item_type": "service_request"}) == "service_request"
    assert declared_type({"work_item_type": "problem"}) is None
    assert declared_type({}) is None
