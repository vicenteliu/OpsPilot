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

from ..errors import ProviderError
from ..providers.base import ProviderProtocol
from ..providers.registry import make_provider
from ..providers.types import Message, SamplingParams, ToolDef
from ..redaction import Redactor
from ..schemas import validate as schema_validate
from ..session.manager import SessionManager
from ..session.types import TraceEvent
from .errors import OrchestratorError
from .tools import make_kb_search_tool, render_tool_result
from .types import PlaybookSpec, RunRequest, RunResult, TokenUsage

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
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost_usd = 0.0

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

            # 3b. Optional prefetch retrieval (PR-8.5).
            #     For weak tool-call models we run kb_search ONCE here and
            #     fold the hits into the system prompt; the chat loop then
            #     runs with tools=[] and max_turns=1.
            #     The trace still gets a tool_call + tool_result pair so the
            #     harness's _retrieved_chunks() walker can find the chunks.
            effective_system_prompt = pb.system_prompt
            effective_tools: list[ToolDef] = [tool_def]
            effective_max_turns = pb.limits.max_turns
            prefetch_chunk_ids: set[str] = set()
            prefetch_hits: list[dict[str, Any]] = []
            if pb.retrieval.mode == "prefetch":
                effective_system_prompt, prefetch_chunk_ids, prefetch_hits = _do_prefetch(
                    pb=pb,
                    ticket=ticket,
                    redactor=redactor,
                    tool_handler=tool_handler,
                    tw=tw,
                )
                effective_tools = []
                effective_max_turns = 1

            # 3c. system + user prompts (post-prefetch so trace mirrors the
            #     content actually fed to the model).
            tw.write(
                TraceEvent.prompt(
                    role="system",
                    content=effective_system_prompt,
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
                Message(role="system", content=effective_system_prompt),
                Message(role="user", content=user_msg),
            ]

            # Build fallback provider lazily — uses the first extra_model if available.
            auto_fallback_model = pb.extra_models[0] if pb.extra_models else None
            fallback_provider: ProviderProtocol | None = None
            if auto_fallback_model is not None:
                with contextlib.suppress(Exception):  # unavailable fallback is non-fatal
                    fallback_provider = make_provider(
                        auto_fallback_model.provider_id,
                        kind=auto_fallback_model.kind,
                    )

            for _ in range(effective_max_turns):
                try:
                    resp = provider.chat(
                        messages,
                        model=pb.model.name,
                        params=SamplingParams(
                            temperature=pb.model.params.get("temperature", 0.2),
                            top_p=pb.model.params.get("top_p", 0.9),
                            max_tokens=pb.model.params.get("max_tokens", 1500),
                        ),
                        tools=effective_tools,
                    )
                except ProviderError:
                    if fallback_provider is None or auto_fallback_model is None:
                        raise
                    resp = fallback_provider.chat(
                        messages,
                        model=auto_fallback_model.name,
                        params=SamplingParams(
                            temperature=auto_fallback_model.params.get("temperature", 0.2),
                            top_p=auto_fallback_model.params.get("top_p", 0.9),
                            max_tokens=auto_fallback_model.params.get("max_tokens", 1500),
                        ),
                        tools=effective_tools,
                    )

                # accumulate tokens for every round (tool_call and final)
                total_input_tokens += resp.usage.input_tokens
                total_output_tokens += resp.usage.output_tokens
                total_cost_usd += resp.usage.cost_usd

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

                # Weak-model salvage: if prefetch is on and the model wrote
                # a citation chunk_id that is 1 character off from a real
                # retrieved chunk_id (e.g. dropped a digit), correct it
                # before schema validation. Bounded by edit-distance ≤ 1.
                if prefetch_chunk_ids:
                    _correct_citation_chunk_ids(summary, prefetch_chunk_ids)
                    # If the model returned empty citations despite having KB
                    # hits, auto-populate from the prefetch results.
                    if not summary.get("citations") and prefetch_hits:
                        summary["citations"] = _citations_from_hits(prefetch_hits)

                # Drop any top-level fields the schema doesn't declare.
                # Strong models (Claude) sometimes add helpful extras
                # (e.g. kb_handles_used) that fail additionalProperties: false.
                summary = _drop_extra_fields(summary, pb.output_schema)

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
        usage=TokenUsage(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cost_usd=total_cost_usd,
        ),
    )


# ── Helpers ──────────────────────────────────────────────────────────


def _drop_extra_fields(summary: dict[str, Any], schema_name: str) -> dict[str, Any]:
    """Remove top-level keys not declared in the schema's properties.

    Strong models sometimes add undeclared fields (e.g. kb_handles_used).
    Stripping them before validation avoids additionalProperties failures
    without weakening the schema itself.
    """
    from ..schemas import get_schema

    allowed = set(get_schema(schema_name).get("properties", {}).keys())
    if not allowed:
        return summary
    return {k: v for k, v in summary.items() if k in allowed}


def _do_prefetch(
    *,
    pb: PlaybookSpec,
    ticket: dict[str, Any],
    redactor: Redactor,
    tool_handler: Callable[[dict[str, Any]], dict[str, Any]],
    tw: Any,  # TraceWriter — typed Any to avoid import cycle
) -> tuple[str, set[str], list[dict[str, Any]]]:
    """Run kb_search once before the chat loop; return augmented system prompt + retrieved chunk_ids + raw hits.

    Side effects:
      * writes one ``tool_call`` and one ``tool_result`` event to ``tw``
        (actor=``system`` / ``tool:kb`` respectively)

    Returns:
        ``(augmented_system_prompt, retrieved_chunk_ids)`` — the chunk_id
        set is used downstream to fuzzy-correct typos in
        ``artifact.citations[].chunk_id`` before schema validation.

    The query is built from ``pb.retrieval.prefetch.query_fields`` and run
    through the redactor so the trace never carries pre-redaction PII.
    """
    fields = pb.retrieval.prefetch.query_fields or ["subject", "body"]
    raw_parts: list[str] = []
    for f in fields:
        v = ticket.get(f)
        if v:
            raw_parts.append(str(v))
    query_raw = "\n".join(raw_parts).strip()
    if not query_raw:
        # Fall back to the rendered ticket so we always have *something*.
        query_raw = _format_ticket(ticket)
    # Redact PII first, then strip the [REDACTED:...] placeholders
    # themselves: they're noise tokens that crater FTS5 implicit-AND
    # recall (e.g. "REDACTED hostname phone 33a7d3da" can never co-occur
    # in a real KB chunk). Vector retrieval also benefits from cleaner
    # input. Loop strips nested placeholders like
    # ``[REDACTED:hostname:[REDACTED:phone:...]]``.
    query = _strip_redaction_placeholders(redactor.redact(query_raw).text)

    top_k = pb.retrieval.prefetch.top_k or pb.limits.max_kb_search_results
    args = {"query": query, "top_k": top_k}

    tw.write(
        TraceEvent.tool_call(
            tool="kb_search",
            args=args,
            action_id=None,
            actor="system",
        )
    )

    payload = tool_handler(args)
    rendered = render_tool_result(payload)
    tw.write(
        TraceEvent.tool_result(
            tool="kb_search",
            status="ok",
            action_id=None,
            stdout_ref=rendered[:8000],
            actor="tool:kb",
        )
    )

    addendum = _render_prefetch_addendum(payload)
    hits = list(payload.get("hits") or [])
    chunk_ids: set[str] = {str(h["chunk_id"]) for h in hits if h.get("chunk_id")}
    return pb.system_prompt + "\n\n" + addendum, chunk_ids, hits


_REDACTION_PLACEHOLDER_RE = re.compile(r"\[REDACTED:[^\[\]]*\]")


def _strip_redaction_placeholders(text: str) -> str:
    """Remove ``[REDACTED:...]`` placeholders from a query string.

    Called after the redactor on prefetch queries so that placeholder
    tokens (REDACTED / hostname / phone / hex ids) don't pollute the
    FTS5 implicit-AND search. Iterates until stable to handle nested
    placeholders like ``[REDACTED:hostname:[REDACTED:phone:abc123]]``.
    """
    prev: str | None = None
    cur = text
    while cur != prev:
        prev = cur
        cur = _REDACTION_PLACEHOLDER_RE.sub(" ", cur)
    return re.sub(r"\s+", " ", cur).strip()


def _render_prefetch_addendum(payload: dict[str, Any]) -> str:
    """Format kb_search hits as a Markdown block to append to system_prompt.

    Uses one ``### chunk #N: \\`chk_xxx\\``` heading per hit (D4) so the
    model sees both the citation key (in inline code, less likely to
    typo when copying) and the chunk content side-by-side.
    """
    hits = payload.get("hits") or []
    if not hits:
        return (
            "## 已预检索 KB / Prefetched KB chunks\n\n"
            "（本次 kb_search 未返回结果；请基于工单事实回答，并在 citations 字段写空数组）"
        )
    parts: list[str] = ["## 已预检索 KB / Prefetched KB chunks", ""]
    for i, h in enumerate(hits, start=1):
        cid = h.get("chunk_id", "?")
        cit = h.get("citation") or {}
        src = cit.get("source_path") or "?"
        ls, le = cit.get("line_start"), cit.get("line_end")
        # Inline-code wrap on the chunk_id makes weak models treat it as
        # an opaque token and copy it character-for-character.
        parts.append(f"### Chunk {i}: `{cid}`")
        parts.append(f"- source_path: `{src}`")
        if ls is not None and le is not None:
            parts.append(f"- lines: {ls}-{le}")
        if cit.get("heading_path"):
            parts.append(f"- heading_path: {' > '.join(cit['heading_path'])}")
        parts.append("")
        parts.append(str(h.get("content") or "").strip())
        parts.append("")
    parts.append(
        "请直接基于以上 chunks 引用，**不要调用任何工具**。"
        "在 `citations[]` 中的 `chunk_id` **必须逐字符精确复制**上面 "
        "Chunk N 标题里反引号包裹的字符串，不要省略或修改任何字符。"
    )
    return "\n".join(parts)


def _citations_from_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build citation objects from prefetch hits for models that omit citations."""
    result = []
    for i, h in enumerate(hits, start=1):
        cit = h.get("citation") or {}
        entry: dict[str, Any] = {
            "id": f"kb-{i}",
            "chunk_id": h.get("chunk_id", ""),
            "document_id": h.get("document_id", ""),
        }
        if cit.get("source_path"):
            entry["source_path"] = cit["source_path"]
        if cit.get("line_start") is not None:
            entry["line_start"] = cit["line_start"]
        if cit.get("line_end") is not None:
            entry["line_end"] = cit["line_end"]
        if cit.get("heading_path"):
            entry["heading_path"] = cit["heading_path"]
        result.append(entry)
    return result


def _correct_citation_chunk_ids(
    summary: dict[str, Any],
    valid_chunk_ids: set[str],
) -> None:
    """Fix typo'd chunk_id values in artifact citations (in-place).

    Weak models (gemma4:e4b) sometimes drop a hex digit when copying a
    chunk_id (observed: ``chk_0cf89826`` → ``chk_0cf8926``). For each
    citation whose chunk_id isn't in ``valid_chunk_ids``, find the
    nearest entry by edit distance ≤ 1 and replace it. If no candidate
    is within 1 edit, leave the value untouched and let schema_check
    surface the failure.
    """
    citations = summary.get("citations")
    if not isinstance(citations, list):
        return
    for c in citations:
        if not isinstance(c, dict):
            continue
        cid = c.get("chunk_id")
        if not isinstance(cid, str) or cid in valid_chunk_ids:
            continue
        match = _nearest_within_edit_distance(cid, valid_chunk_ids, max_distance=1)
        if match is not None:
            c["chunk_id"] = match


def _nearest_within_edit_distance(
    needle: str, candidates: set[str], *, max_distance: int = 1
) -> str | None:
    """Return the candidate within ``max_distance`` Levenshtein edits, else None.

    Tiny implementation since we expect ≤ 5 candidates and only call
    when the needle missed an exact match. If multiple candidates tie,
    returns the first one found — which is safe because the weak-model
    bug is single-char drops, not arbitrary corruption.
    """
    for c in candidates:
        if abs(len(c) - len(needle)) > max_distance:
            continue
        if _edit_distance_at_most(needle, c, max_distance):
            return c
    return None


def _edit_distance_at_most(a: str, b: str, k: int) -> bool:
    """True iff Levenshtein(a, b) ≤ k. Bounded DP, O(len(a)·len(b))."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > k:
        return False
    # Standard DP — OK because strings here are ≤ 16 chars (chunk_id).
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb] <= k


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


def _try_balance_brackets(text: str, *, max_pad: int = 3) -> str:
    """Append missing ``}`` / ``]`` if the model dropped trailing closers.

    Weak open models (gemma4:e4b in our host runs) reliably finish writing
    every nested object/array and then *forget the outermost* ``}``. Walk
    the string with a stack ignoring quoted-string contents; if 1..max_pad
    closers are missing, tack them on. ``max_pad`` keeps this from
    silently masking genuinely broken output.
    """
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in text:
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in ("}", "]") and stack and stack[-1] == ch:
            stack.pop()
    if 0 < len(stack) <= max_pad:
        return text + "".join(reversed(stack))
    return text


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
    # Graceful-degrade for weak-model outputs that drop trailing closers.
    text = _try_balance_brackets(text)
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
