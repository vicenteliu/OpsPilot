"""End-to-end ticket-summary orchestrator.

Connects PR-3 provider → PR-4 retrieval (via kb_search tool) → PR-5 redaction
→ PR-6 session/trace/artifact, producing a ``ticket_summary_v1`` artifact.

Loop shape::

    create session (draft → active)
    write system prompt event
    write user prompt event (redacted ticket)
    repeat (≤ max_turns):
        chat(messages, tools=[kb_search])
        if finish_reason == tool_call:
            handle each tool_call:
                execute kb_search handler
                write tool_call + tool_result events
                append tool message to messages
        elif finish_reason == stop:
            write response event
            break
    parse final content as JSON → schema_validate("ticket_summary_v1") →
    write artifact + final user_action(approve)
    transition session → archived

D6 fallback: if a chat round raises (provider / parsing) we still try
to record a system(error) event + transition to ``aborted``; the
:class:`RunResult.error` field surfaces the cause.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Callable
from typing import Any, Literal

from ..providers.base import ProviderProtocol
from ..providers.types import Message, SamplingParams
from ..redaction import Redactor
from ..schemas import validate as schema_validate
from ..session.manager import SessionManager
from ..session.types import TraceEvent
from .errors import OrchestratorError
from .tools import make_kb_search_tool, render_tool_result
from .types import RunRequest, RunResult

# ── Public API ───────────────────────────────────────────────────────


def run_ticket_summary(
    request: RunRequest,
    *,
    session_manager: SessionManager,
    provider: ProviderProtocol,
    redactor: Redactor,
    embed_fn: Callable[[str], list[float]],
    sqlite_store: Any,  # SqliteStore — typed Any to avoid PR-4 import cycle
    lance_store: Any,  # LanceStore
) -> RunResult:
    """Run the playbook end-to-end. Returns a :class:`RunResult`."""
    pb = request.playbook

    # ── 1. Load + redact input ──────────────────────────────────────
    ticket = _load_ticket(request.input_path)
    rendered_user_msg = _format_ticket(ticket)
    redaction = redactor.redact(rendered_user_msg)
    user_msg = redaction.text

    # ── 2. Create session ───────────────────────────────────────────
    sess = session_manager.create(
        owner=request.owner,
        playbook=pb.ref,
        model=pb.model,
        retention_class=pb.defaults.retention_class,
        sensitivity=request.classification or pb.defaults.sensitivity,
    )
    session_manager.transition(sess.id, "active")

    # ── 3. Build tools ──────────────────────────────────────────────
    namespace = request.namespace or request.kb_id or pb.defaults.kb_id
    tool_def, tool_handler = make_kb_search_tool(
        sqlite=sqlite_store,
        lance=lance_store,
        embed_fn=embed_fn,
        default_top_k=pb.limits.max_kb_search_results,
        namespace=namespace,
    )

    artifact_id: str | None = None
    summary: dict[str, Any] = {}
    schema_valid = False
    error: str | None = None

    try:
        with session_manager.trace(sess.id) as tw:
            # 3a. system event marking activation.
            tw.write(
                TraceEvent.system(
                    event="state_change",
                    details={"from": "draft", "to": "active", "reason": "redaction_passed"},
                    actor="system",
                )
            )

            # 3b. system + user prompts.
            tw.write(
                TraceEvent.prompt(
                    role="system",
                    content=pb.system_prompt,
                    actor="system",
                )
            )
            tw.write(
                TraceEvent.prompt(
                    role="user",
                    content=user_msg,
                    actor=f"user:{request.owner}",
                )
            )
            for hit in redaction.hits:
                tw.write(
                    TraceEvent.redaction(
                        pattern=hit.rule_id,
                        count=1,
                        placeholder_format=hit.placeholder,
                        actor="system",
                    )
                )

            # ── 4. Chat loop ─────────────────────────────────────────
            messages: list[Message] = [
                Message(role="system", content=pb.system_prompt),
                Message(role="user", content=user_msg),
            ]

            for _ in range(pb.limits.max_turns):
                resp = provider.chat(
                    messages,
                    model=pb.model.name,
                    params=SamplingParams(
                        temperature=pb.model.params.get("temperature", 0.2),
                        top_p=pb.model.params.get("top_p", 0.9),
                        max_tokens=pb.model.params.get("max_tokens", 1500),
                    ),
                    tools=[tool_def],
                )

                # tool_call branch
                if resp.finish_reason == "tool_call" and resp.tool_calls:
                    # Append the assistant turn with tool_calls so the
                    # model sees its own decision when we feed back.
                    messages.append(
                        Message(
                            role="assistant",
                            content=resp.content or "",
                            tool_calls=list(resp.tool_calls),
                        )
                    )
                    for tc in resp.tool_calls:
                        action_id = _normalise_action_id(tc.id)
                        tw.write(
                            TraceEvent.tool_call(
                                tool=tc.name,
                                args=tc.arguments,
                                action_id=action_id,
                                actor="model:assistant",
                            )
                        )
                        status: Literal["ok", "failed", "timeout", "aborted"]
                        if tc.name != "kb_search":
                            payload = {"_error": f"unknown tool: {tc.name}"}
                            status = "failed"
                        else:
                            try:
                                payload = tool_handler(tc.arguments)
                                status = "ok"
                            except Exception as e:  # noqa: BLE001 — surface tool errors
                                payload = {"_error": f"{type(e).__name__}: {e}"}
                                status = "failed"

                        rendered = render_tool_result(payload)
                        tw.write(
                            TraceEvent.tool_result(
                                tool=tc.name,
                                status=status,
                                action_id=action_id,
                                stdout_ref=rendered[:8000],
                                actor="tool:kb",
                            )
                        )
                        messages.append(
                            Message(
                                role="tool",
                                content=rendered,
                                tool_call_id=tc.id,
                                name=tc.name,
                            )
                        )
                    continue

                # final answer branch
                tw.write(
                    TraceEvent.response(
                        content=resp.content,
                        finish_reason=resp.finish_reason,
                        usage={
                            "input_tokens": resp.usage.input_tokens,
                            "output_tokens": resp.usage.output_tokens,
                            "cost_usd": resp.usage.cost_usd,
                        },
                        actor="model:assistant",
                    )
                )

                summary, parse_err = _parse_summary_json(resp.content)
                if parse_err is not None:
                    error = parse_err
                    tw.write(
                        TraceEvent.system(
                            event="error",
                            details={"reason": "json_parse_failed", "message": parse_err},
                            actor="system",
                        )
                    )
                    break

                try:
                    schema_validate(pb.output_schema, summary)
                    schema_valid = True
                except Exception as e:  # noqa: BLE001
                    error = f"schema_check failed: {e}"
                    tw.write(
                        TraceEvent.system(
                            event="error",
                            details={"reason": "schema_check_failed", "message": str(e)},
                            actor="system",
                        )
                    )
                    break

                # Persist the artifact.
                meta = session_manager.artifacts(sess.id).put(
                    json.dumps(summary, ensure_ascii=False, indent=2),
                    kind="application/json",
                    source="model:assistant",
                )
                artifact_id = meta.artifact_id
                tw.write(
                    TraceEvent.user_action(
                        action="approve",
                        target=meta.artifact_id,
                        actor=f"user:{request.owner}",
                    )
                )
                break
            else:
                # Loop exhausted without a final answer.
                error = (
                    f"max_turns ({pb.limits.max_turns}) exhausted before "
                    "model produced a final response"
                )
                tw.write(
                    TraceEvent.system(
                        event="error",
                        details={"reason": "max_turns_exhausted"},
                        actor="system",
                    )
                )
    except OrchestratorError:
        raise
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
    finally:
        # Best-effort transition; ignore if illegal (e.g. already aborted).
        target = "archived" if schema_valid else "aborted"
        with contextlib.suppress(Exception):
            session_manager.transition(sess.id, target)

    return RunResult(
        session_id=sess.id,
        artifact_id=artifact_id,
        summary=summary,
        schema_valid=schema_valid,
        error=error,
    )


# ── Helpers ──────────────────────────────────────────────────────────


def _load_ticket(path: Any) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise OrchestratorError(f"ticket input must be a JSON object: got {type(d).__name__}")
    d.pop("_comment", None)
    return d


def _format_ticket(ticket: dict[str, Any]) -> str:
    """Render the ticket dict into a readable user-prompt block.

    The orchestrator passes this through Redactor before adding it to the
    chat history; structure preserved so the model can see field labels.
    """
    parts: list[str] = []
    parts.append(
        f"工单 {ticket.get('ticket_id', '?')}"
        f" ({ticket.get('channel', '?')},"
        f" {ticket.get('submitted_at', '?')})"
    )
    if ticket.get("submitter_role"):
        parts.append(f"提交者角色：{ticket['submitter_role']}")
    if ticket.get("subject"):
        parts.append(f"主题：{ticket['subject']}")
    if ticket.get("body"):
        parts.append(f"正文：{ticket['body']}")
    for att in ticket.get("attachments") or []:
        name = att.get("name") or "(unnamed)"
        snippet = att.get("snippet") or ""
        parts.append(f"附件 {name}：\n{snippet}")
    return "\n".join(parts)


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?|\n?```\s*$", re.MULTILINE)


def _parse_summary_json(content: str) -> tuple[dict[str, Any], str | None]:
    """Extract the model's JSON object even if it's accidentally fenced.

    Returns ``(parsed_dict, error_or_None)``.
    """
    text = (content or "").strip()
    if not text:
        return {}, "empty model response"
    # Strip ```json ... ``` fences if the model ignored the system prompt.
    text = _JSON_FENCE_RE.sub("", text).strip()
    # If the model wrapped the JSON in narration, grab the first {...} block.
    if not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            text = m.group(0)
    try:
        d = json.loads(text)
    except json.JSONDecodeError as e:
        return {}, f"JSON parse error: {e}"
    if not isinstance(d, dict):
        return {}, "model returned non-object JSON"
    return d, None


_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def _normalise_action_id(raw: str | None) -> str | None:
    """Map provider-side tool-call ids onto our ``act_<ULID>`` shape.

    The trace-event schema requires ``^act_[0-9A-HJKMNP-TV-Z]{26}$``. If
    the provider supplies a different id format (e.g. ``call_001``) we
    drop it to None — the schema treats action_id as optional, and the
    audit trail still has the tool name + args.
    """
    if not raw:
        return None
    if raw.startswith("act_") and _ULID_RE.match(raw[len("act_") :]):
        return raw
    return None
