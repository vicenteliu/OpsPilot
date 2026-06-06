"""Tests for ``opspilot.orchestrator`` (PR-7).

Uses a scripted :class:`_ScriptedProvider` to drive the orchestrator
loop deterministically — the LLM "decides" tool-calls and final JSON
according to a queue of canned :class:`ChatResponse` objects.

Covers the **PR-7 exit criterion** from
``IMPLEMENTATION_STAGE_1.md §763``: a full ``opspilot run`` against
``pb_ticket_summary_zh`` ends with a session whose artifact validates
against ``incident_summary_v1``.
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path
from typing import Any

import pytest

from opspilot.memory.lance_store import LanceStore, VectorRecord
from opspilot.memory.sqlite_store import SqliteStore
from opspilot.memory.storage_init import init_sqlite
from opspilot.orchestrator import RunRequest, load_playbook, run_ticket_summary
from opspilot.orchestrator.types import PlaybookRetrieval, PlaybookRetrievalPrefetch
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
    """Hand-crafted summary that satisfies incident_summary_v1."""
    return {
        "schema_version": "incident_summary_v1",
        "work_item_ref": "T-XXXX",
        "work_item_type": "incident",
        "summary": (
            "上午 10:00 起多名用户 VPN 认证失败；终端/网络已交叉验证可排除；"
            "建议优先排查 VPN 网关与认证后端。"
        ),
        "symptoms": ["authentication failed", "ike sa establishment failed"],
        "scope": "multiple_users",
        "tried_steps": ["重启客户端", "更换网络（4G 热点）"],
        "missing_fields": ["VPN 客户端版本", "受影响账号"],
        "tasks": [
            {
                "ref": "task-1",
                "action": "确认 VPN 网关 / 认证服务（RADIUS / AD LDAP）健康",
                "rationale": "多人同时认证失败基本指向服务端鉴权链路",
                "tier": "L2",
                "citations": ["kb-1"],
            },
            {
                "ref": "task-2",
                "action": "向用户索取客户端版本与受影响账号清单",
                "rationale": "缺失字段会阻碍 L2 复现",
                "tier": "L1",
                "citations": [],
            },
            {
                "ref": "task-3",
                "action": "检查 10:00 前后是否有变更窗口（DNS / 证书 / 防火墙）",
                "rationale": "证书过期或时间不同步会引发认证失败",
                "tier": "L2",
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


def _request(input_path: Path, *, mode: str = "tool") -> RunRequest:
    """Load the playbook and pin retrieval.mode for the test.

    Default ``mode='tool'`` keeps the legacy PR-7 tests deterministic
    even though the on-disk playbook now ships ``mode=prefetch`` (PR-8.5).
    Prefetch tests pass ``mode='prefetch'`` explicitly.
    """
    pb = load_playbook(PLAYBOOK_DIR)
    if pb.retrieval.mode != mode:
        pb = dataclasses.replace(
            pb,
            retrieval=PlaybookRetrieval(
                mode=mode,
                prefetch=pb.retrieval.prefetch,
            ),
        )
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
    assert result.summary["schema_version"] == "incident_summary_v1"
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


# ── Service Request fulfillment (#5) ─────────────────────────────────


REQUEST_PLAYBOOK_DIR = REPO_ROOT / "playbooks" / "pb_request_fulfillment_zh"


def _good_request_json() -> dict[str, Any]:
    """Hand-crafted artifact that satisfies request_fulfillment_v1."""
    return {
        "schema_version": "request_fulfillment_v1",
        "work_item_ref": "REQ-1001",
        "work_item_type": "service_request",
        "summary": "新员工申请 VPN 权限，需经理审批后由一线开通。",
        "requested_item": "新员工 VPN 权限开通",
        "approval_needed": True,
        "missing_fields": ["经理审批人"],
        "tasks": [
            {
                "ref": "task-1",
                "action": "确认经理审批",
                "rationale": "特权资源需签核",
                "tier": "L2",
                "citations": ["kb-1"],
            },
            {
                "ref": "task-2",
                "action": "在 VPN 网关创建账号并分组",
                "rationale": "按开通 SOP 操作",
                "tier": "L1",
                "citations": ["kb-1"],
            },
        ],
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


def test_request_fulfillment_run_produces_valid_artifact(
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
) -> None:
    sqlite, lance = populated_kb
    provider = _ScriptedProvider(
        [
            ChatResponse(
                content=json.dumps(_good_request_json(), ensure_ascii=False),
                finish_reason="stop",
                tool_calls=None,
                usage=Usage(input_tokens=300, output_tokens=200, cost_usd=0.0),
            )
        ]
    )
    pb = load_playbook(REQUEST_PLAYBOOK_DIR)
    pb = dataclasses.replace(
        pb, retrieval=PlaybookRetrieval(mode="tool", prefetch=pb.retrieval.prefetch)
    )
    req = RunRequest(playbook=pb, input_path=SAMPLE_TICKET, owner="vicente@example.com")

    result = run_ticket_summary(
        req,
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
    )

    assert result.schema_valid is True
    assert result.error is None
    assert result.summary["schema_version"] == "request_fulfillment_v1"
    assert result.summary["work_item_type"] == "service_request"
    assert result.summary["approval_needed"] is True
    assert len(result.summary["tasks"]) == 2
    assert result.summary["tasks"][0]["tier"] == "L2"


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
    bad = {"schema_version": "incident_summary_v1", "work_item_ref": "T-X"}  # too thin
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
    assert pb.output_schema == "incident_summary_v1"
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


# ── PR-8.5: retrieval.mode = prefetch ───────────────────────────────


def _scripted_prefetch_one_round() -> list[ChatResponse]:
    """Single chat response: model returns final JSON directly.

    In prefetch mode the orchestrator runs kb_search BEFORE the chat
    loop and folds chunks into the system prompt, so the model has
    everything it needs in one round and never emits a tool_call.
    """
    return [
        ChatResponse(
            content=json.dumps(_good_summary_json(), ensure_ascii=False),
            finish_reason="stop",
            tool_calls=None,
            usage=Usage(input_tokens=900, output_tokens=400, cost_usd=0.0),
        ),
    ]


def test_prefetch_happy_path_runs_kb_search_before_chat(
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
) -> None:
    """PR-8.5 exit criterion: prefetch mode produces a valid artifact in one round."""
    sqlite, lance = populated_kb
    provider = _ScriptedProvider(_scripted_prefetch_one_round())

    result = run_ticket_summary(
        _request(SAMPLE_TICKET, mode="prefetch"),
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
    )

    # Artifact validates and the chat ran exactly once.
    assert result.schema_valid is True
    assert result.error is None
    assert result.artifact_id is not None
    assert len(provider.calls) == 1, "prefetch mode must NOT loop tool-calls"
    # tools=[] was actually handed to the provider (otherwise gemma4 would
    # be tempted to ignore the prefetched chunks and call kb_search again).
    assert provider.calls[0]["tools"] == []

    # Trace shows the orchestrator-driven tool_call/tool_result pair
    # (so harness's _retrieved_chunks() walker continues to work).
    sdir = session_manager.session_dir(result.session_id)
    rows = [
        json.loads(line) for line in (sdir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    tool_calls = [r for r in rows if r["type"] == "tool_call"]
    tool_results = [r for r in rows if r["type"] == "tool_result"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["tool"] == "kb_search"
    assert tool_calls[0]["actor"] == "system"  # orchestrator-driven, not model
    assert len(tool_results) == 1
    assert tool_results[0]["status"] == "ok"

    # System prompt fed to the model must contain the prefetch addendum.
    sys_prompts = [r for r in rows if r["type"] == "prompt" and r["role"] == "system"]
    assert sys_prompts and "Prefetched KB chunks" in sys_prompts[0]["content"]


def test_prefetch_query_fallback_when_fields_missing(
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
) -> None:
    """If query_fields point at fields the ticket doesn't have, fall back to
    the rendered ticket so prefetch still issues a non-empty kb_search."""
    sqlite, lance = populated_kb
    provider = _ScriptedProvider(_scripted_prefetch_one_round())

    pb = load_playbook(PLAYBOOK_DIR)
    pb = dataclasses.replace(
        pb,
        retrieval=PlaybookRetrieval(
            mode="prefetch",
            prefetch=PlaybookRetrievalPrefetch(query_fields=["zzz_nonexistent"]),
        ),
    )
    request = RunRequest(playbook=pb, input_path=SAMPLE_TICKET, owner="vicente@example.com")
    result = run_ticket_summary(
        request,
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
    )

    # Run still succeeds; query was the rendered-ticket fallback (non-empty),
    # not a literal "" that would have errored in the kb_search handler.
    assert result.error is None
    assert result.schema_valid is True
    sdir = session_manager.session_dir(result.session_id)
    rows = [
        json.loads(line) for line in (sdir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    tool_calls = [r for r in rows if r["type"] == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["args"]["query"]  # non-empty


def test_correct_citation_chunk_ids_fixes_typo() -> None:
    """gemma4:e4b drops a hex digit when copying chunk_ids out of the
    prefetch addendum (observed on host: chk_0cf89826 → chk_0cf8926).
    PR-8.5 hotfix-5 fuzzy-corrects within edit distance 1."""
    from opspilot.orchestrator.ticket_summary import _correct_citation_chunk_ids

    valid = {"chk_0cf89826", "chk_ea5a0261"}
    summary = {
        "citations": [
            {"id": "kb-1", "chunk_id": "chk_0cf8926"},  # 1 digit dropped
            {"id": "kb-2", "chunk_id": "chk_ea5a0261"},  # already correct
        ]
    }
    _correct_citation_chunk_ids(summary, valid)
    assert summary["citations"][0]["chunk_id"] == "chk_0cf89826"
    assert summary["citations"][1]["chunk_id"] == "chk_ea5a0261"


def test_correct_citation_chunk_ids_does_not_overreach() -> None:
    """Edit distance > 1 must NOT auto-correct — that masks real bugs."""
    from opspilot.orchestrator.ticket_summary import _correct_citation_chunk_ids

    valid = {"chk_0cf89826"}
    summary = {"citations": [{"chunk_id": "chk_999999"}]}  # totally different
    _correct_citation_chunk_ids(summary, valid)
    assert summary["citations"][0]["chunk_id"] == "chk_999999"


def test_correct_citation_chunk_ids_handles_malformed_input() -> None:
    """Robust against missing/non-string citations fields."""
    from opspilot.orchestrator.ticket_summary import _correct_citation_chunk_ids

    valid = {"chk_x"}
    # No citations key
    s1: dict = {"summary": "x"}
    _correct_citation_chunk_ids(s1, valid)
    assert s1 == {"summary": "x"}
    # citations is not a list
    s2 = {"citations": "oops"}
    _correct_citation_chunk_ids(s2, valid)
    assert s2 == {"citations": "oops"}


def test_parse_summary_json_balances_dropped_outer_brace() -> None:
    """gemma4:e4b reliably forgets the outermost `}` after closing all
    nested arrays/objects. _try_balance_brackets must salvage it.
    See: PR-8.5 hotfix-4 — host run sess_01KQKYQVKVZFPPQ24S6RBXFDHR
    finished with finish_reason=stop but ended `...]}]\\n` (1 missing `}`)."""
    from opspilot.orchestrator.ticket_summary import _parse_summary_json

    # Mirror the actual broken shape: well-formed JSON minus the final `}`.
    truncated = (
        '{"schema_version":"incident_summary_v1","work_item_ref":"T-1",'
        '"work_item_type":"incident",'
        '"summary":"x","symptoms":["a"],"scope":"single_user",'
        '"tried_steps":[],"missing_fields":[],'
        '"tasks":[{"ref":"task-1","action":"a","rationale":"r","tier":"L1","citations":[]}],'
        '"severity_suggested":"P3",'
        '"citations":[{"id":"kb-1","chunk_id":"chk_x","document_id":"doc_x",'
        '"source_path":"x","line_start":1,"line_end":2}]'
    )  # ← outermost `}` deliberately missing

    parsed, err = _parse_summary_json(truncated)
    assert err is None
    assert parsed["schema_version"] == "incident_summary_v1"
    assert parsed["work_item_ref"] == "T-1"


def test_parse_summary_json_does_not_pad_grossly_broken_output() -> None:
    """If the deficit is > 3 closers we leave it broken — autopadding
    arbitrary tokens would mask genuine model failures."""
    from opspilot.orchestrator.ticket_summary import _parse_summary_json

    parsed, err = _parse_summary_json('{{{{ "a": 1')  # 4-deep, never balances
    assert parsed == {}
    assert err is not None and "JSON parse error" in err


def test_strip_redaction_placeholders_removes_nested() -> None:
    """The prefetch query must not carry [REDACTED:...] placeholder noise
    into FTS5 — those tokens crater implicit-AND recall (PR-8.5 hotfix)."""
    from opspilot.orchestrator.ticket_summary import _strip_redaction_placeholders

    assert _strip_redaction_placeholders("[REDACTED:role:11111111]") == ""
    assert (
        _strip_redaction_placeholders("VPN [REDACTED:hostname:[REDACTED:phone:33a7d3da]] 重启过")
        == "VPN 重启过"
    )
    assert _strip_redaction_placeholders("a [REDACTED:x:1] b [REDACTED:y:2] c") == "a b c"
    assert _strip_redaction_placeholders("plain text") == "plain text"
