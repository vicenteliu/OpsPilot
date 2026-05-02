"""Markdown chunker — naive ``headings_then_size`` strategy (PR-2).

Strategy in this PR:

1. If the input begins with a YAML frontmatter (``---\\n…\\n---\\n``), strip
   it. Body coordinates remain in the *original* text's char/line space so
   chunks reference the unmodified document.
2. Walk the body line by line, tracking the ATX-heading stack
   (``# .. ######``).
3. Every heading opens a new "block"; a block's content is its heading
   line plus all subsequent non-heading lines until the next heading.
4. A block is "content-bearing" iff it has at least one non-blank line
   beyond the heading.
5. Chunks = greedy concatenation of consecutive content-bearing blocks
   until the running token estimate would exceed
   ``ChunkConfig.target_size_tokens``. Heading-only blocks are skipped
   for chunking but still update the heading-path context.

Token estimation is intentionally crude (``len(text) // 3``) — good
enough for cut-point selection. PR-5 will plug in a real tokenizer that
agrees with the embedding model's token count.

Each chunk carries:

* ``content``                 redacted markdown text
* ``char_start`` / ``char_end``    offsets into the *original* document
* ``line_start`` / ``line_end``    1-based, inclusive
* ``heading_path``            tuple of ancestor headings at chunk start
* ``anchor``                  ``#slug`` form of the leading heading
* ``token_count``             estimate
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final, Literal

# ATX heading: 1-6 ``#`` then mandatory space then text.
_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
_FRONTMATTER_FENCE: Final[str] = "---"


@dataclass(frozen=True, slots=True)
class ChunkConfig:
    strategy: Literal["headings_then_size", "fixed_size"] = "headings_then_size"
    target_size_tokens: int = 512
    max_size_tokens: int = 1024
    overlap_tokens: int = 64


@dataclass(frozen=True, slots=True)
class Chunk:
    seq: int
    content: str
    char_start: int
    char_end: int
    line_start: int
    line_end: int
    heading_path: tuple[str, ...]
    anchor: str | None
    token_count: int


# ──────────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────────


def _strip_frontmatter(text: str) -> tuple[str, int, int]:
    """If text begins with ``---\\n…\\n---\\n``, return (body, body_char_start, body_line_start).

    body_line_start is 1-based — the line number of the first body line in
    the original text.
    """
    if not text.startswith(_FRONTMATTER_FENCE):
        return text, 0, 1

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\n") != _FRONTMATTER_FENCE:
        return text, 0, 1

    for i in range(1, len(lines)):
        if lines[i].rstrip("\n") == _FRONTMATTER_FENCE:
            # Lines 0..i are frontmatter; body starts at line i+1 (0-based) → i+2 (1-based)
            body_start_char = sum(len(line) for line in lines[: i + 1])
            body = "".join(lines[i + 1 :])
            body_start_line = i + 2
            return body, body_start_char, body_start_line

    # No closing fence; treat as no frontmatter.
    return text, 0, 1


def _estimate_tokens(text: str) -> int:
    """Crude estimate: ``len(text) // 3``. Good enough for cut-point selection."""
    return max(1, len(text) // 3)


_SLUG_NON_WORD = re.compile(r"[^\w\s-]", flags=re.UNICODE)
_SLUG_DASH_SPACE = re.compile(r"[-\s]+", flags=re.UNICODE)


def _slug(text: str) -> str:
    """Convert a heading title into a URL-fragment-style anchor slug."""
    s = _SLUG_NON_WORD.sub("", text).strip().lower()
    s = _SLUG_DASH_SPACE.sub("-", s)
    return s.strip("-")


# ──────────────────────────────────────────────────────────────────────────
#  Internal block model
# ──────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _Block:
    """One section of the body: a heading + all lines until the next heading."""

    line_start: int  # 1-based, in original text
    line_end: int  # 1-based, inclusive
    char_start: int  # 0-based, in original text
    char_end: int  # 0-based, exclusive in original text
    content: str  # the section text (heading line included)
    heading_level: int  # 0 if no heading (preamble); 1..6 otherwise
    heading_text: str  # "" if no heading
    has_content: bool  # at least one non-blank, non-heading line
    heading_path: tuple[str, ...] = field(default_factory=tuple)


def _parse_blocks(body: str, body_char_offset: int, body_line_offset: int) -> list[_Block]:
    """Split *body* into _Block instances, tracking heading-path stack."""
    blocks: list[_Block] = []
    if not body:
        return blocks

    heading_stack: list[tuple[int, str]] = []  # [(level, text)]
    cur_lines: list[str] = []
    cur_block_start_line = body_line_offset
    cur_block_start_char = body_char_offset
    cur_heading: tuple[int, str] | None = None  # current section's leading heading

    char_pos_in_body = 0  # offset within body (not including frontmatter)
    lines = body.split("\n")

    def close_block(end_char: int, end_line: int) -> None:
        nonlocal cur_lines, cur_block_start_line, cur_block_start_char, cur_heading
        if cur_heading is None and not any(line.strip() for line in cur_lines):
            cur_lines = []
            return
        content = "\n".join(cur_lines)
        # has_content = at least one non-blank, non-heading line
        body_lines = cur_lines[1:] if cur_heading is not None and cur_lines else cur_lines
        has_content = any(line.strip() for line in body_lines)
        path = tuple(t for _, t in heading_stack)
        blocks.append(
            _Block(
                line_start=cur_block_start_line,
                line_end=end_line,
                char_start=cur_block_start_char,
                char_end=end_char,
                content=content,
                heading_level=(cur_heading[0] if cur_heading else 0),
                heading_text=(cur_heading[1] if cur_heading else ""),
                has_content=has_content,
                heading_path=path,
            )
        )
        cur_lines = []

    for line_idx, line in enumerate(lines):
        line_no = body_line_offset + line_idx
        char_pos_in_orig = body_char_offset + char_pos_in_body

        m = _HEADING_RE.match(line)
        if m:
            # Close the previous block first (its char_end is BEFORE this heading line).
            if cur_lines or cur_heading is not None:
                close_block(end_char=char_pos_in_orig, end_line=line_no - 1)
            # Update heading stack: pop all levels >= this one, then push.
            level = len(m.group(1))
            text = m.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, text))
            cur_heading = (level, text)
            cur_block_start_line = line_no
            cur_block_start_char = char_pos_in_orig
            cur_lines = [line]
        else:
            cur_lines.append(line)

        # Advance char position. ``split('\n')`` consumes the newline between
        # adjacent lines; account for the +1 except after the last line.
        char_pos_in_body += len(line)
        if line_idx < len(lines) - 1:
            char_pos_in_body += 1

    # Close the final block.
    if cur_lines or cur_heading is not None:
        final_end_line = body_line_offset + len(lines) - 1
        # If the last line is empty (trailing newline) we still treat the block
        # as ending there.
        close_block(
            end_char=body_char_offset + char_pos_in_body,
            end_line=final_end_line,
        )

    return blocks


# ──────────────────────────────────────────────────────────────────────────
#  Public entrypoint
# ──────────────────────────────────────────────────────────────────────────


def chunk_markdown(text: str, *, config: ChunkConfig | None = None) -> list[Chunk]:
    """Split *text* into chunks using the ``headings_then_size`` strategy.

    See module docstring for the full algorithm; PR-2 keeps it intentionally
    simple, deferring real tokenizer-driven sizing to PR-5.
    """
    cfg = config or ChunkConfig()
    body, body_char_offset, body_line_offset = _strip_frontmatter(text)
    blocks = _parse_blocks(body, body_char_offset, body_line_offset)

    # Greedy merge content-bearing blocks until target_size_tokens.
    chunk_groups: list[list[_Block]] = []
    pending: list[_Block] = []
    pending_tokens = 0

    for b in blocks:
        if not b.has_content:
            # Heading-only block: its heading is already in subsequent blocks'
            # heading_path (we updated the stack before creating the block).
            continue
        block_tokens = _estimate_tokens(b.content)
        if block_tokens > cfg.max_size_tokens:
            # Flush pending, emit oversize block as its own chunk.
            if pending:
                chunk_groups.append(pending)
                pending = []
                pending_tokens = 0
            chunk_groups.append([b])
            continue
        if pending and (pending_tokens + block_tokens > cfg.target_size_tokens):
            chunk_groups.append(pending)
            pending = [b]
            pending_tokens = block_tokens
        else:
            pending.append(b)
            pending_tokens += block_tokens
    if pending:
        chunk_groups.append(pending)

    # Materialize Chunk objects.
    chunks: list[Chunk] = []
    for seq, group in enumerate(chunk_groups):
        first = group[0]
        last = group[-1]

        # Reconstruct content from the original-text char range so chunks
        # are byte-faithful to the source.
        content_start = first.char_start
        content_end = last.char_end
        content = text[content_start:content_end]

        # heading_path: if all blocks share the same path, use it.
        # Otherwise compute longest common prefix and join the differing
        # tails with " / " — matches the convention used in our spec
        # examples (chunk 2 of sop_vpn_zh.md).
        if all(b.heading_path == first.heading_path for b in group):
            heading_path = first.heading_path
        else:
            min_len = min(len(b.heading_path) for b in group)
            common: list[str] = []
            for i in range(min_len):
                if all(b.heading_path[i] == group[0].heading_path[i] for b in group):
                    common.append(group[0].heading_path[i])
                else:
                    break
            tails: list[str] = []
            for b in group:
                rest = b.heading_path[len(common) :]
                if rest:
                    tails.append(rest[-1])
                elif b.heading_text:
                    tails.append(b.heading_text)
            # Deduplicate while preserving order
            seen: set[str] = set()
            unique_tails: list[str] = []
            for t in tails:
                if t not in seen:
                    unique_tails.append(t)
                    seen.add(t)
            heading_path = tuple(common) + ((" / ".join(unique_tails),) if unique_tails else ())

        anchor = "#" + _slug(first.heading_text) if first.heading_text else None
        token_count = _estimate_tokens(content)
        chunks.append(
            Chunk(
                seq=seq,
                content=content,
                char_start=first.char_start,
                char_end=last.char_end,
                line_start=first.line_start,
                line_end=last.line_end,
                heading_path=heading_path,
                anchor=anchor,
                token_count=token_count,
            )
        )

    return chunks
