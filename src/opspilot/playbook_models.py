"""Rewrite a playbook.yaml's ``model`` / ``extra_models`` blocks in place.

Admins curate which models the UI offers by editing the active playbook's
model list from the admin module (ADR-0021). Only those two value blocks
are re-rendered — everything else in the file, including every hand-written
comment, is spliced back untouched, so the version-controlled spec stays
readable. ruamel renders the replacement blocks (correct scalar quoting and
indentation); we never hand-format YAML.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString as _DoubleQuoted

_STR_FIELDS = ("provider_id", "kind", "name", "version")


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)  # matches the checked-in style
    y.width = 4096  # never wrap scalars
    return y


def _own_comments(slots: Any) -> Any | None:
    """``slots`` with the document's own section comments removed.

    ruamel parks a comment on the key it follows, so the heading that opens the
    *next* top-level section ends up attached to the last key of this block.
    Carrying that forward duplicates it — the heading appears both where it
    belongs and inside the rewritten block. Column tells them apart: an inner
    comment is indented (col > 0), a section heading sits at col 0.
    """

    def keep(slot: Any) -> Any:
        if slot is None:
            return None
        if isinstance(slot, list):
            kept = [t for t in slot if getattr(t, "column", 0) > 0]
            return kept or None
        return slot if getattr(slot, "column", 0) > 0 else None

    out = [keep(slot) for slot in slots]
    return out if any(x is not None for x in out) else None


def _params_map(new: dict[str, Any], previous: Any) -> Any:
    """The params block, carrying across whatever comments it already had.

    Both value blocks are re-rendered from parsed data, so a comment written
    *inside* one used to be dropped every time an admin touched the model list
    from the UI — including the two that exist to stop someone re-adding a field
    that 400s:

        # Sonnet 5 / Opus 5 reject temperature / top_p / top_k (HTTP 400).
        # Opus 5 rejects a token budget ... so depth is `effort`.

    ruamel attaches comments to the key they precede, so reusing the previous
    mapping's ``ca`` for every key that survives keeps them. A key the admin
    removed takes its comment with it, which is what should happen.
    """
    if not isinstance(previous, CommentedMap):
        return dict(new)
    merged = CommentedMap()
    for key in previous:  # previous order first, so comments stay next to their key
        if key in new:
            # An unchanged value keeps the scalar ruamel parsed, so its quoting
            # survives: editing the model list should not restyle values it did
            # not touch.
            merged[key] = previous[key] if previous[key] == new[key] else new[key]
    for key, value in new.items():
        if key not in merged:
            merged[key] = value
    for key, comment in previous.ca.items.items():
        kept = _own_comments(comment)
        if key in merged and kept is not None:
            merged.ca.items[key] = kept
    return merged


def _model_map(m: dict[str, Any], previous: Any = None) -> CommentedMap:
    """A model block as a double-quoted mapping, matching the existing style."""
    out = CommentedMap()
    for f in _STR_FIELDS:
        out[f] = _DoubleQuoted(str(m[f]))
    params = m.get("params") or {}
    if params:
        out["params"] = _params_map(
            params, previous.get("params") if isinstance(previous, CommentedMap) else None
        )
    if isinstance(previous, CommentedMap):
        # A comment before the *first* key of a nested mapping is attached to
        # the parent's key, not to the key it visually precedes — so the one
        # above `max_tokens:` lives here, on `params`, and _params_map cannot
        # see it.
        for key, comment in previous.ca.items.items():
            kept = _own_comments(comment)
            if key in out and kept is not None:
                out.ca.items[key] = kept
    return out


def _by_identity(block: Any) -> dict[tuple[str, str], Any]:
    """Existing model entries keyed by (provider_id, name) so a rewrite can find
    the entry it is replacing and carry that entry's comments forward."""
    out: dict[tuple[str, str], Any] = {}
    for entry in block or []:
        if isinstance(entry, CommentedMap):
            out[(str(entry.get("provider_id")), str(entry.get("name")))] = entry
    return out


def _render(key: str, value: Any, y: YAML) -> list[str]:
    buf = io.StringIO()
    y.dump({key: value}, buf)
    return buf.getvalue().rstrip("\n").split("\n")


def _block_bounds(lines: list[str], key: str) -> tuple[int, int] | None:
    """``(start, end)`` line indices of a top-level ``key:`` block, or None.

    ``start`` is the ``key:`` line; ``end`` is one past the last value line —
    the key line plus the indented lines under it, stopping at the first blank
    or non-indented line. This keeps any following blank line + comments
    (which belong to the *next* section) outside the replaced region.
    """
    prefix = f"{key}:"
    start = next(
        (i for i, ln in enumerate(lines) if ln == prefix or ln.startswith(prefix + " ")),
        None,
    )
    if start is None:
        return None
    end = start + 1
    while end < len(lines) and lines[end].startswith((" ", "\t")):
        end += 1
    return start, end


def write_playbook_models(
    source_dir: Path, primary: dict[str, Any], extras: list[dict[str, Any]]
) -> None:
    """Replace the model / extra_models blocks in ``<source_dir>/playbook.yaml``.

    Everything outside the two blocks is spliced back untouched. Inside them the
    content is re-rendered, so only comments attached to a key that survives the
    rewrite are carried across — see :func:`_params_map`.

    Raises ``ValueError`` if the file has no top-level ``model:`` block.
    """
    path = source_dir / "playbook.yaml"
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    y = _yaml()

    existing = y.load(text) or {}
    previous_primary = existing.get("model")
    previous_extras = _by_identity(existing.get("extra_models"))

    model_b = _block_bounds(lines, "model")
    if model_b is None:
        raise ValueError("playbook.yaml has no top-level `model:` block")
    extra_b = _block_bounds(lines, "extra_models")

    model_render = _render("model", _model_map(primary, previous_primary), y)
    extra_render = _render(
        "extra_models",
        [
            _model_map(m, previous_extras.get((str(m["provider_id"]), str(m["name"]))))
            for m in extras
        ],
        y,
    )

    # extra_models sits below model, so splice it first to keep model's indices
    # valid; when it's absent, splice model then insert extras right after it.
    if extra_b is not None:
        lines[extra_b[0] : extra_b[1]] = extra_render
        lines[model_b[0] : model_b[1]] = model_render
    else:
        lines[model_b[0] : model_b[1]] = model_render
        new_model_b = _block_bounds(lines, "model")
        assert new_model_b is not None
        ins = new_model_b[1]
        lines[ins:ins] = ["", *extra_render]

    path.write_text("\n".join(lines), encoding="utf-8")
