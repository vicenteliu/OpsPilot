"""Tests for ``opspilot.harness`` (PR-8).

Two layers:

* unit tests for the 6 evaluators (pure functions over EvalContext).
* integration tests for :func:`run_harness` using a scripted provider
  (mirrors ``test_orchestrator.py``).

The Stage 1 exit-criterion test asserts the harness against the spec
example produces a passing :class:`EvalResult` (weighted_score ≥ 0.85)
when the orchestrator emits the canonical ``ticket_summary_v1`` JSON.
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path
from typing import Any

import pytest

from opspilot.harness import EvalResult, load_fixture, load_golden, run_harness
from opspilot.harness.evaluators import (
    EvalContext,
    evaluate_must_contain,
    evaluate_must_not_contain,
    evaluate_rag_citation_validity,
    evaluate_rag_precision_at_k,
    evaluate_rag_recall_at_k,
    evaluate_schema_check,
    run_all_evaluators,
)
from opspilot.harness.types import (
    DEFAULT_EVALUATOR_WEIGHTS,
    Fixture,
    Golden,
)
from opspilot.memory.lance_store import LanceStore, VectorRecord
from opspilot.memory.sqlite_store import SqliteStore
from opspilot.memory.storage_init import init_sqlite
from opspilot.orchestrator import load_playbook
from opspilot.orchestrator.types import PlaybookRetrieval, PlaybookSpec
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
EXAMPLES = REPO_ROOT / "examples" / "scn_ticket_summary_zh"
FIXTURE_PATH = EXAMPLES / "harness" / "fixture.json"
GOLDEN_PATH = EXAMPLES / "harness" / "golden.json"
PLAYBOOK_DIR = REPO_ROOT / "playbooks" / "pb_ticket_summary_zh"
KB_DOC = EXAMPLES / "kb" / "doc-meta.json"
KB_CHUNKS = EXAMPLES / "kb" / "chunks.jsonl"

DIM = 768
EMBED_MODEL = "ollama-local/test-embed@2026-04"


# ── Mock embedder + scripted provider (reused from PR-7 style) ──────


_AUTH = ("认证", "鉴权", "auth", "authentication")
_NETWORK = ("隧道", "网络", "MTU", "NAT")


def _topic_embed(text: str) -> list[float]:
    lo = text.lower()
    a = sum(1.0 for t in _AUTH if t.lower() in lo)
    n = sum(1.0 for t in _NETWORK if t.lower() in lo)
    base = [a + 0.05, 0.30, n + 0.05]
    norm = math.sqrt(sum(x * x for x in base))
    head = [x / norm for x in base]
    return head + [0.0] * (DIM - 3)


class _ScriptedProvider:
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
        self.calls.append({"roles": [m.role for m in messages]})
        if not self._queue:
            raise AssertionError("scripted provider exhausted")
        return self._queue.pop(0)

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        return [_topic_embed(t) for t in texts]

    def health_probe(self) -> bool:
        return True


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def fixture() -> Fixture:
    return load_fixture(FIXTURE_PATH)


@pytest.fixture
def golden() -> Golden:
    return load_golden(GOLDEN_PATH)


@pytest.fixture
def populated_kb(tmp_path: Path) -> tuple[SqliteStore, LanceStore]:
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)
    doc = json.loads(KB_DOC.read_text(encoding="utf-8"))
    doc.pop("_comment", None)
    sqlite.upsert_document(doc)
    chunks: list[dict[str, Any]] = []
    for line in KB_CHUNKS.read_text(encoding="utf-8").splitlines():
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


# ── Helpers ─────────────────────────────────────────────────────────


def _good_summary() -> dict[str, Any]:
    """Hand-crafted artifact matching ticket_summary_v1 + golden assertions."""
    return {
        "schema_version": "ticket_summary_v1",
        "ticket_ref": "T-XXXX",
        "summary": (
            "上午 10:00 起多名用户 VPN 认证失败 (authentication failed)；"
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
                "action": "检查 10:00 前后是否有变更窗口",
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
    return [
        ChatResponse(
            content="",
            finish_reason="tool_call",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="kb_search",
                    arguments={"query": "VPN 认证失败"},
                )
            ],
            usage=Usage(input_tokens=100, output_tokens=10, cost_usd=0.0),
        ),
        ChatResponse(
            content=json.dumps(_good_summary(), ensure_ascii=False),
            finish_reason="stop",
            tool_calls=None,
            usage=Usage(input_tokens=500, output_tokens=400, cost_usd=0.0),
        ),
    ]


def _load_pb_tool_mode() -> PlaybookSpec:
    """Load the playbook and pin retrieval.mode='tool' for legacy harness tests.

    The on-disk playbook ships ``mode=prefetch`` (PR-8.5). The integration
    fixtures below script a 2-round tool-call loop, which only makes sense
    in tool mode, so we override.
    """
    pb = load_playbook(PLAYBOOK_DIR)
    if pb.retrieval.mode != "tool":
        pb = dataclasses.replace(
            pb,
            retrieval=PlaybookRetrieval(mode="tool", prefetch=pb.retrieval.prefetch),
        )
    return pb


# ── Evaluator unit tests ─────────────────────────────────────────────


def _ctx(
    *,
    artifact: dict[str, Any] | None = None,
    golden: Golden,
    retrieved: list[str] | None = None,
    kb_lookup: dict[str, dict[str, Any]] | None = None,
) -> EvalContext:
    return EvalContext(
        artifact=artifact if artifact is not None else _good_summary(),
        golden=golden,
        retrieved_chunk_ids=list(retrieved or []),
        kb_chunk_lookup=kb_lookup,
    )


def test_schema_check_pass(golden: Golden) -> None:
    r = evaluate_schema_check(_ctx(golden=golden))
    assert r.passed and r.score == 1.0


def test_schema_check_fail_on_missing_required(golden: Golden) -> None:
    bad = {"schema_version": "ticket_summary_v1"}  # too thin
    r = evaluate_schema_check(_ctx(artifact=bad, golden=golden))
    assert not r.passed and r.score == 0.0


def test_must_contain_pass(golden: Golden) -> None:
    r = evaluate_must_contain(_ctx(golden=golden))
    assert r.passed and r.score == 1.0
    assert not r.details["missing"]


def test_must_contain_partial(golden: Golden) -> None:
    bad = _good_summary()
    bad["summary"] = "VPN 网关 only"  # drops "authentication failed", "多名用户"
    r = evaluate_must_contain(_ctx(artifact=bad, golden=golden))
    assert not r.passed
    assert 0.0 < r.score < 1.0
    assert r.details["missing"]


def test_must_not_contain_pass(golden: Golden) -> None:
    r = evaluate_must_not_contain(_ctx(golden=golden))
    assert r.passed and r.score == 1.0


def test_must_not_contain_fail_on_leak(golden: Golden) -> None:
    bad = _good_summary()
    bad["summary"] = "raw [REDACTED:secret] leaked"
    r = evaluate_must_not_contain(_ctx(artifact=bad, golden=golden))
    assert not r.passed and r.score == 0.0


def test_rag_recall_at_k_hit(golden: Golden) -> None:
    r = evaluate_rag_recall_at_k(_ctx(golden=golden, retrieved=["chk_0cf89826", "chk_ea5a0261"]))
    assert r.passed and r.score == 1.0


def test_rag_recall_at_k_miss(golden: Golden) -> None:
    r = evaluate_rag_recall_at_k(_ctx(golden=golden, retrieved=["chk_unrelated"]))
    assert not r.passed and r.score == 0.0


def test_rag_precision_at_k(golden: Golden) -> None:
    r = evaluate_rag_precision_at_k(
        _ctx(
            golden=golden,
            retrieved=["chk_0cf89826", "chk_ea5a0261", "chk_0f674194"],
        )
    )
    # 2 of 3 relevant (chk_0cf89826 + chk_ea5a0261); chk_0f674194 is irrelevant
    assert 0.6 <= r.score <= 0.7
    assert r.passed


def test_rag_citation_validity_all_match(golden: Golden) -> None:
    kb = {
        "chk_0cf89826": {"line_start": 37, "line_end": 46},
    }
    r = evaluate_rag_citation_validity(_ctx(golden=golden, kb_lookup=kb))
    assert r.passed and r.score == 1.0


def test_rag_citation_validity_line_mismatch(golden: Golden) -> None:
    kb = {
        # KB has different line range than the artifact's citation.
        "chk_0cf89826": {"line_start": 99, "line_end": 100},
    }
    r = evaluate_rag_citation_validity(_ctx(golden=golden, kb_lookup=kb))
    assert not r.passed and r.score == 0.0


def test_rag_citation_validity_no_citations(golden: Golden) -> None:
    bad = _good_summary()
    bad["citations"] = []
    r = evaluate_rag_citation_validity(_ctx(artifact=bad, golden=golden))
    assert not r.passed


def test_run_all_evaluators_returns_six(golden: Golden) -> None:
    rs = run_all_evaluators(_ctx(golden=golden, retrieved=["chk_0cf89826"]))
    assert len(rs) == 6
    assert {r.id for r in rs} >= {"ev_schema_check", "ev_must_contain"}


# ── run_harness integration ─────────────────────────────────────────


def test_run_harness_full_pass(
    fixture: Fixture,
    golden: Golden,
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    tmp_path: Path,
) -> None:
    sqlite, lance = populated_kb
    pb = _load_pb_tool_mode()
    provider = _ScriptedProvider(_scripted_two_round())

    result = run_harness(
        fixture=fixture,
        golden=golden,
        playbook=pb,
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
        tmp_dir=tmp_path / "harness-tmp",
    )
    assert isinstance(result, EvalResult)
    assert result.passed is True
    assert result.weighted_score >= 0.85
    assert "by_type" in result.scores
    # All 6 evaluators ran.
    assert len(result.evaluators) == 6


def test_run_harness_emits_eval_result_schema_valid(
    fixture: Fixture,
    golden: Golden,
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    tmp_path: Path,
) -> None:
    """The emitted dict must validate against eval-result.schema.json."""
    from opspilot.schemas import validate as schema_validate

    sqlite, lance = populated_kb
    pb = _load_pb_tool_mode()
    provider = _ScriptedProvider(_scripted_two_round())

    result = run_harness(
        fixture=fixture,
        golden=golden,
        playbook=pb,
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
        tmp_dir=tmp_path / "harness-tmp",
    )
    schema_validate("eval-result", result.to_dict())  # should not raise


def test_run_harness_aborts_pass_when_artifact_invalid(
    fixture: Fixture,
    golden: Golden,
    session_manager: SessionManager,
    populated_kb: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    tmp_path: Path,
) -> None:
    """Orchestrator returns malformed JSON → schema_check fails → not passed."""
    sqlite, lance = populated_kb
    pb = _load_pb_tool_mode()
    provider = _ScriptedProvider(
        [
            ChatResponse(
                content="not json",
                finish_reason="stop",
                tool_calls=None,
                usage=Usage(input_tokens=0, output_tokens=0, cost_usd=0.0),
            ),
        ]
    )
    result = run_harness(
        fixture=fixture,
        golden=golden,
        playbook=pb,
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
        tmp_dir=tmp_path / "harness-tmp",
    )
    assert result.passed is False
    assert result.weighted_score < 0.85


def test_default_evaluator_weights_sum_to_one() -> None:
    total = sum(DEFAULT_EVALUATOR_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-6


def test_load_fixture_reads_spec_example() -> None:
    fx = load_fixture(FIXTURE_PATH)
    assert fx.id == "fix_a1b2c3d4"
    assert fx.scenario_id == "scn_ticket_summary_zh"
    assert "ticket" in fx.tags


def test_load_golden_reads_spec_example() -> None:
    g = load_golden(GOLDEN_PATH)
    assert g.fixture_id == "fix_a1b2c3d4"
    assert "authentication failed" in g.must_contain
    assert g.expected_chunk_id == "chk_0cf89826"


# ── Conflict-aware golden tests ───────────────────────────────────────

# Recording provider — records full message lists so we can inspect
# what the LLM sees in each round.
class _RecordingProvider(_ScriptedProvider):
    def __init__(self, responses: list[ChatResponse]) -> None:
        super().__init__(responses)
        self.all_messages: list[list[Message]] = []

    def chat(
        self,
        messages: list[Message],
        *,
        model: str,
        params: SamplingParams,
        tools: list[ToolDef] | None = None,
        timeout_ms: int = 90_000,
    ) -> ChatResponse:
        self.all_messages.append(list(messages))
        return super().chat(messages, model=model, params=params, tools=tools, timeout_ms=timeout_ms)


@pytest.fixture
def populated_kb_with_open_conflict(tmp_path: Path) -> tuple[SqliteStore, LanceStore]:
    """Standard KB + one open conflict record involving chk_0cf89826 / doc_88a277cf."""
    # Build standard KB (mirrors populated_kb fixture)
    sqlite = SqliteStore(init_sqlite(tmp_path / "kb.db"))
    lance = LanceStore.open_or_create(tmp_path / "lancedb", dim=DIM, embedding_model=EMBED_MODEL)
    doc = json.loads(KB_DOC.read_text(encoding="utf-8"))
    doc.pop("_comment", None)
    sqlite.upsert_document(doc)
    chunks: list[dict[str, Any]] = []
    for line in KB_CHUNKS.read_text(encoding="utf-8").splitlines():
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

    # Insert a second conflicting doc + chunk
    sqlite.upsert_document(
        {
            "id": "doc_bb000000",
            "source_path": "/kb/vpn_auth_alt.md",
            "title": "VPN Auth Alt",
            "classification": "internal",
            "content_hash": "sha256:" + "b" * 64,
            "ingested_at": "2026-05-01T00:00:00Z",
            "language": "zh-CN",
            "tags": [],
            "namespace": "opspilot:public-kb",
            "chunk_strategy": "headings_then_size",
            "chunk_count": 1,
            "embedding_model": EMBED_MODEL,
            "embedding_dim": DIM,
            "redaction_passed": True,
        }
    )
    sqlite.upsert_chunks(
        [
            {
                "id": "chk_bb000000",
                "document_id": "doc_bb000000",
                "seq": 0,
                "content": "VPN 认证失败时，请检查 RADIUS 服务器状态与 authentication 配置。",
                "content_hash": "sha256:" + "b" * 64,
                "char_start": 0,
                "char_end": 30,
                "line_start": 1,
                "line_end": 1,
                "embedding_model": EMBED_MODEL,
                "vector_id": "vec_chkbb0000",
                "metadata": {
                    "namespace": "opspilot:public-kb",
                    "classification": "internal",
                    "language": "zh-CN",
                    "tags": [],
                },
            }
        ]
    )

    # Open conflict between the two docs
    sqlite.upsert_conflict(
        {
            "id": "conf_a1b2c3d4",
            "chunk_a_id": "chk_0cf89826",
            "chunk_b_id": "chk_bb000000",
            "doc_a_id": "doc_88a277cf",
            "doc_b_id": "doc_bb000000",
            "conflict_type": "scope_overlap",
            "similarity": 0.92,
            "status": "open",
            "detected_at": "2026-05-06T00:00:00Z",
        }
    )
    return sqlite, lance


# ── Tool-handler unit tests ───────────────────────────────────────────


def test_kb_search_tool_conflict_warning_present_when_open(
    populated_kb_with_open_conflict: tuple[SqliteStore, LanceStore],
) -> None:
    """kb_search tool result contains _conflict_warning when KB has open conflicts."""
    from opspilot.orchestrator.tools import make_kb_search_tool

    sqlite, lance = populated_kb_with_open_conflict
    _, handler = make_kb_search_tool(sqlite=sqlite, lance=lance, embed_fn=_topic_embed)
    result = handler({"query": "VPN 认证失败"})
    assert "_conflict_warning" in result
    assert "source document" in result["_conflict_warning"]


def test_kb_search_tool_no_warning_after_resolve(
    populated_kb_with_open_conflict: tuple[SqliteStore, LanceStore],
) -> None:
    """After resolve(a_wins), _conflict_warning disappears from tool result."""
    from opspilot.memory.conflict import resolve_conflict
    from opspilot.orchestrator.tools import make_kb_search_tool

    sqlite, lance = populated_kb_with_open_conflict
    resolve_conflict("conf_a1b2c3d4", resolution="a_wins", resolved_by="tester", sqlite=sqlite)
    _, handler = make_kb_search_tool(sqlite=sqlite, lance=lance, embed_fn=_topic_embed)
    result = handler({"query": "VPN 认证失败"})
    assert "_conflict_warning" not in result


# ── Harness integration tests ─────────────────────────────────────────


def test_run_harness_conflict_warning_reaches_llm_context(
    fixture: Fixture,
    golden: Golden,
    session_manager: SessionManager,
    populated_kb_with_open_conflict: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    tmp_path: Path,
) -> None:
    """The _conflict_warning must appear in the tool-result message the LLM sees in round 2."""
    sqlite, lance = populated_kb_with_open_conflict
    pb = _load_pb_tool_mode()
    provider = _RecordingProvider(_scripted_two_round())

    run_harness(
        fixture=fixture,
        golden=golden,
        playbook=pb,
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
        tmp_dir=tmp_path / "harness-tmp",
    )

    assert len(provider.all_messages) >= 2, "expected at least 2 chat rounds"
    round2_msgs = provider.all_messages[1]
    tool_msgs = [m for m in round2_msgs if m.role == "tool"]
    assert any(
        "_conflict_warning" in (m.content or "") for m in tool_msgs
    ), "expected _conflict_warning in tool-result message of round-2 LLM context"


def test_run_harness_no_conflict_warning_after_resolve(
    fixture: Fixture,
    golden: Golden,
    session_manager: SessionManager,
    populated_kb_with_open_conflict: tuple[SqliteStore, LanceStore],
    redactor: Redactor,
    tmp_path: Path,
) -> None:
    """After resolving the conflict, no _conflict_warning appears in tool result."""
    from opspilot.memory.conflict import resolve_conflict

    sqlite, lance = populated_kb_with_open_conflict
    resolve_conflict("conf_a1b2c3d4", resolution="a_wins", resolved_by="tester", sqlite=sqlite)
    pb = _load_pb_tool_mode()
    provider = _RecordingProvider(_scripted_two_round())

    run_harness(
        fixture=fixture,
        golden=golden,
        playbook=pb,
        session_manager=session_manager,
        provider=provider,
        redactor=redactor,
        embed_fn=_topic_embed,
        sqlite_store=sqlite,
        lance_store=lance,
        tmp_dir=tmp_path / "harness-tmp",
    )

    assert len(provider.all_messages) >= 2
    round2_msgs = provider.all_messages[1]
    tool_msgs = [m for m in round2_msgs if m.role == "tool"]
    assert not any(
        "_conflict_warning" in (m.content or "") for m in tool_msgs
    ), "expected no _conflict_warning after conflict is resolved"
