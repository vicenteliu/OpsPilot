"""Tests for ``opspilot.orchestrator`` (PR-7).

Uses a scripted :class:`_ScriptedProvider` to drive the orchestrator
loop deterministically — the LLM "decides" tool-calls and final JSON
according to a queue of canned :class:`ChatResponse` objects.

Covers the **PR-7 exit criterion** from
``IMPLEMENTATION_STAGE_1.md §763``: a full ``opspilot run`` against
``pb_ticket_summary_zh`` ends with a session whose artifact validates
against ``ticket_summary_v1``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from opspilot.memory.lance_store import LanceStore, VectorRecord
from opspilot.memory.sqlite_store import SqliteStore
from opspilot.memory.storage_init import init_sqlite
from opspilot.orchestrator import RunRequest, load_playbook, run_ticket_summary
from opspilot.providers.types import (
    ChatResponse,
    Message,
    SamplingParams,
    ToolCall,
    ToolDef,
    Usage,
)
from opspilot.redaction import Redactor
from opspilot.session import SessionManager

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK_DIR = REPO_ROOT / "playbooks" / "pb_ticket_summary_zh"
EXAMPLES_DIR = REPO_ROOT / "examples" / "scn_ticket_summary_zh"
SAMPLE_TICKET = EXAMPLES_DIR / "session" / "inputs" / "ticket.json"
SAMPLE_KB_DOC = EXAMPLES_DIR / "kb" / "doc-meta.json"
SAMPLE_KB_CHUNKS = EXAMPLES_DIR / "kb" / "chunks.jsonl"

DIM = 768
EMBED_MODEL = "ollama-local/test-embed@2026-04"


# ── Mock embedder + scripted provider ───────────────────────────────


_AUTH = ("认证", "鉴权", "auth", "authentication", "RADIUS", "LDAP")
_NETWORK = ("隧道", "网络", "MTU", "NAT", "ESP", "tunnel", "ping")


def _topic_embed(text: str) -> list[float]:
    lo = text.lower()
    a = sum(1.0 for t in _AUTH if t.lower() in lo)
    n = sum(1.0 for t in _NETWORK if t.lower() in lo)
    base = [a + 0.05, 0.30, n + 0.05]
    norm = math.sqrt(sum(x * x for x in base))
    head = [x / norm for x in base]
    return head + [0.0] * (DIM - 3)


class _ScriptedProvider:
    """Implements ProviderProtocol with a pre-set queue of ChatResponses."""

    provider_id = "scripted-test"
    kind = "ollama"

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._queue = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[Message],
        *,
        model: str,
        params: SamplingParams,
        tools: list[ToolDef] | None = None,
        timeout_ms: int = 90_000,
    ) -> ChatResponse:
        self.calls.append(
            {
                "messages": [m.role for m in messages],
                "tools": [t.name for t in (tools or [])],
            }
        )
        if not self._queue:
            raise AssertionError("scripted provider exhausted; loop ran longer than expected")
        return self._queue.pop(0)

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        return [_topic_embed(t) for t in texts]

    def health_probe(self) -> bool:
        return True


# ── Common fixtures ──────────────────────────────────────────────────


@pytest.fixture
def populated_kb(tmp_path: Path) -> tuple[SqliteStore, LanceStore]:
    """Load examples KB into fresh stores."""
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)
    doc = json.loads(SAMPLE_KB_DOC.read_text(encoding="utf-8"))
    doc.pop("_comment", None)
    sqlite.upsert_document(doc)

    chunks: list[dict[str, Any]] = []
    for line in SAMPLE_KB_CHUNKS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            c.pop("_comment", None)
            chunks.append(c)
    sqlite.upsert_chunks(chunks)

    records = []
    for c in chunks:
        md = c["metadata"]
        records.append(
            VectorRecord(
                vector_id=c["vector_id"],
                embedding=_topic_embed(c["content"] or ""),
                document_id=c["document_id"],
                chunk_id=c["id"],
                namespace=md["namespace"],
                classification=md["classification"],
                language=md.get("language", "zh-CN"),
                tags=md.get("tags", []),
                embedding_model=EMBED_MODEL,
            )
        )
    lance.upsert_vectors(records)
    return sqlite, lance


@pytest.fixture
def session_manager(tmp_path: Path) -> SessionManager:
    return SessionManager(home=tmp_path)


@pytest.fixture
def redactor() -> Redactor:
    return Redactor.from_yaml()


# ── Helpers ──────────────────────────────────────────────────────────


def _good_summary_json() -> dict[str, Any]:
    """Hand-crafted summary that satisfies ticket_summary_v1."""
    return {
        "schema_version": "ticket_summary_v1",
        "ticket_ref": "T-XXXX",
        "summary": (
            "上午 10:00 起多名用户 VPN 认证失败；终端/网络已交叉验证可排除；"
            "建议优先排查 VPN 网关与认证后端。"
        ),
        "symptoms": ["authentication failed", "ike sa establishment failed"],
        "scope": "multiple_users",
        "tried_steps": ["重启客户端", "更换网络（4G 热点）"],
        "missing_fields": ["VPN 客户端版本", "受影响账号"],
        "next_actions": [
            {
                "action": "确认 VPN 网关 / 认证服务（RADIUS / AD LDAP）健康",
                "rationale": "多人同时认证失败基本指向服务端鉴权链路",
                "citations": ["kb-1"],
            },
            {
                "action": "向用户索取客户端版本与受影响账号清单",
                "rationale": "缺失字段会阻碍 L2 复现",
                "citations": [],
            },
            {
                "action": "检查 10:00 前后是否有变更窗口（DNS / 证书 / 防火墙）",
                "rationale": "证书过期或时间不同步会引发认证失败",
                "citations": ["kb-1"],
            },
        ],
        "severity_suggested": "P2",
        "escalation_hint": "L2 网络组",
        "citations": [
            {
                "id": "kb-1",
                "chunk_id": "chk_0cf89826",
                "document_id": "doc_88a277cf",
                "source_path": "examples/scn_ticket_summary_zh/kb/sop_vpn_zh.md",
                "line_start": 37,
                "line_end": 46,
            }
        ],
    }


def _scripted_two_round() -> list[ChatResponse]:
    """Round 1: tool_call kb_search. Round 2: final JSON."""
    return [
        ChatResponse(
            content="",
            finish_reason="tool_call",
            tool_calls=[
                ToolCall(
                    id="call_001",
                    name="kb_search",
                    arguments={"query": "VPN 认证失败"},
                )
            ],
            usage=Usage(input_tokens=120, output_tokens=20, cost_usd=0.0),
        ),
        ChatResponse(
            content=json.dumps(_good_summary_json(), ensure_ascii=False),
            finish_reason="stop",
            tool_calls=None,
            usage=Usage(input_tokens=600, output_tokens=400, cost_usd=0.0),
        ),
    ]


def _request(input_path: Path) -> RunRequest:
    pb = load_playbook(PLAYBOOK_DIR)
    return RunRequest(
        playbook=pb,
        input_path=input_path,
        owner="vicente@example.com",
    )


# ── Exit-criterion test ──────────────────────────────────────────────


def test_exit_criterion_run_produces_valid_artifact(
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
) -> None:
    sqlite, lance = populated_kb
    provider = _ScriptedProvider(_scripted_two_round())

    result = run_ticket_summary(
        _request(SAMPLE_TICKET),
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
    )

    assert result.schema_valid is True
    assert result.error is None
    assert result.artifact_id is not None and result.artifact_id.startswith("art_")
    assert result.summary["schema_version"] == "ticket_summary_v1"
    assert result.summary["scope"] == "multiple_users"

    # Two chat rounds expected: tool_call + final.
    assert len(provider.calls) == 2

    # Session moved to archived; trace.jsonl validates row-by-row (TraceWriter
    # already does this on write, so just sanity-check the file exists).
    sdir = session_manager.session_dir(result.session_id)
    trace_path = sdir / "trace.jsonl"
    audit_path = sdir / "audit.log"
    art_path = sdir / "artifacts" / f"{result.artifact_id}.json"

    assert trace_path.is_file()
    assert audit_path.is_file()
    assert art_path.is_file()
    assert session_manager.load(result.session_id).status == "archived"


def test_run_writes_expected_trace_event_types(
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
) -> None:
    sqlite, lance = populated_kb
    provider = _ScriptedProvider(_scripted_two_round())
    result = run_ticket_summary(
        _request(SAMPLE_TICKET),
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
    )
    rows = [
        json.loads(line)
        for line in (session_manager.session_dir(result.session_id) / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    types = [r["type"] for r in rows]
    assert "system" in types
    assert types.count("prompt") >= 2  # system + user
    assert "tool_call" in types
    assert "tool_result" in types
    assert "response" in types
    assert "user_action" in types  # final approve


def test_run_redacts_user_input(
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    tmp_path: Path,
) -> None:
    """Email in raw input must be replaced before reaching the trace."""
    sqlite, lance = populated_kb
    raw = {
        "ticket_id": "T-XYZ",
        "channel": "service-desk",
        "submitted_at": "2026-04-30T10:00:00Z",
        "subject": "test",
        "body": "Contact me at user@example.com about VPN 认证失败",
        "attachments": [],
    }
    p = tmp_path / "ticket.json"
    p.write_text(json.dumps(raw), encoding="utf-8")

    provider = _ScriptedProvider(_scripted_two_round())
    result = run_ticket_summary(
        _request(p),
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
    )
    user_prompt = next(
        json.loads(line)
        for line in (session_manager.session_dir(result.session_id) / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if json.loads(line).get("type") == "prompt" and json.loads(line).get("role") == "user"
    )
    assert "user@example.com" not in user_prompt["content"]
    assert "[REDACTED:email" in user_prompt["content"]


def test_run_aborts_on_invalid_json(
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
) -> None:
    sqlite, lance = populated_kb
    provider = _ScriptedProvider(
        [
            ChatResponse(
                content="not json at all",
                finish_reason="stop",
                tool_calls=None,
                usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
            ),
        ]
    )
    result = run_ticket_summary(
        _request(SAMPLE_TICKET),
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
    )
    assert result.schema_valid is False
    assert result.error is not None and "JSON parse" in result.error
    assert session_manager.load(result.session_id).status == "aborted"


def test_run_strips_markdown_fences_around_json(
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
) -> None:
    """Model wrapped JSON in ```json fences — orchestrator should still parse."""
    sqlite, lance = populated_kb
    fenced = "```json\n" + json.dumps(_good_summary_json(), ensure_ascii=False) + "\n```"
    provider = _ScriptedProvider(
        [
            ChatResponse(
                content=fenced,
                finish_reason="stop",
                tool_calls=None,
                usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
            ),
        ]
    )
    result = run_ticket_summary(
        _request(SAMPLE_TICKET),
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
    )
    assert result.schema_valid is True


def test_run_schema_check_failure_aborts(
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
) -> None:
    """A response that's valid JSON but missing required fields should abort."""
    sqlite, lance = populated_kb
    bad = {"schema_version": "ticket_summary_v1", "ticket_ref": "T-X"}  # too thin
    provider = _ScriptedProvider(
        [
            ChatResponse(
                content=json.dumps(bad),
                finish_reason="stop",
                tool_calls=None,
                usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
            ),
        ]
    )
    result = run_ticket_summary(
        _request(SAMPLE_TICKET),
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
    )
    assert result.schema_valid is False
    assert result.error is not None and "schema_check" in result.error


def test_run_max_turns_exhausted(
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
) -> None:
    """Tool-call loop never converges → aborts with max_turns_exhausted."""
    sqlite, lance = populated_kb
    # Always return tool_call; never a final stop.
    forever_tool_call = ChatResponse(
        content="",
        finish_reason="tool_call",
        tool_calls=[ToolCall(id="call_x", name="kb_search", arguments={"query": "noop"})],
        usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
    )
    # Playbook says max_turns=8. Provide 9 to ensure we hit the limit.
    provider = _ScriptedProvider([forever_tool_call] * 9)
    result = run_ticket_summary(
        _request(SAMPLE_TICKET),
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
    )
    assert result.schema_valid is False
    assert result.error is not None and "max_turns" in result.error


def test_run_kb_search_handler_returns_hits(
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
) -> None:
    """tool_result.stdout_ref should contain JSON with hits[]."""
    sqlite, lance = populated_kb
    provider = _ScriptedProvider(_scripted_two_round())
    result = run_ticket_summary(
        _request(SAMPLE_TICKET),
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
    )
    rows = [
        json.loads(line)
        for line in (session_manager.session_dir(result.session_id) / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    tr = next(r for r in rows if r["type"] == "tool_result")
    payload = json.loads(tr["stdout_ref"])
    assert "hits" in payload
    assert isinstance(payload["hits"], list)
    assert payload["hits"]  # at least one hit
    assert "chunk_id" in payload["hits"][0]
    assert "citation" in payload["hits"][0]


def test_run_unknown_tool_records_failed_result(
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
) -> None:
    sqlite, lance = populated_kb
    provider = _ScriptedProvider(
        [
            ChatResponse(
                content="",
                finish_reason="tool_call",
                tool_calls=[ToolCall(id="c1", name="bogus_tool", arguments={})],
                usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
            ),
            ChatResponse(
                content=json.dumps(_good_summary_json(), ensure_ascii=False),
                finish_reason="stop",
                tool_calls=None,
                usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
            ),
        ]
    )
    result = run_ticket_summary(
        _request(SAMPLE_TICKET),
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
    )
    rows = [
        json.loads(line)
        for line in (session_manager.session_dir(result.session_id) / "trace.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    failed = next(r for r in rows if r["type"] == "tool_result" and r["status"] == "failed")
    assert "unknown tool" in failed["stdout_ref"]
    # Despite the failed tool, final round still works → schema valid.
    assert result.schema_valid is True


def test_load_playbook_reads_yaml_and_prompt() -> None:
    pb = load_playbook(PLAYBOOK_DIR)
    assert pb.id == "pb_ticket_summary_zh"
    assert pb.output_schema == "ticket_summary_v1"
    assert pb.tools[0].name == "kb_search"
    assert "OpsPilot" in pb.system_prompt


def test_load_playbook_missing_file(tmp_path: Path) -> None:
    from opspilot.orchestrator.errors import PlaybookError

    with pytest.raises(PlaybookError, match="playbook.yaml not found"):
        load_playbook(tmp_path)


def test_load_playbook_missing_required_field(tmp_path: Path) -> None:
    from opspilot.orchestrator.errors import PlaybookError

    bad = tmp_path / "playbook.yaml"
    bad.write_text("id: pb_x\nversion: 1.0.0\n", encoding="utf-8")  # missing model etc.
    with pytest.raises(PlaybookError, match="missing required field"):
        load_playbook(tmp_path)
