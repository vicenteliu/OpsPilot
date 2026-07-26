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


def _model_map(m: dict[str, Any]) -> CommentedMap:
    """A model block as a double-quoted mapping, matching the existing style."""
    out = CommentedMap()
    for f in _STR_FIELDS:
        out[f] = _DoubleQuoted(str(m[f]))
    params = m.get("params") or {}
    if params:
        out["params"] = dict(params)
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

    All other content — comments, key order, formatting — is preserved.
    Raises ``ValueError`` if the file has no top-level ``model:`` block.
    """
    path = source_dir / "playbook.yaml"
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    y = _yaml()

    model_b = _block_bounds(lines, "model")
    if model_b is None:
        raise ValueError("playbook.yaml has no top-level `model:` block")
    extra_b = _block_bounds(lines, "extra_models")

    model_render = _render("model", _model_map(primary), y)
    extra_render = _render("extra_models", [_model_map(m) for m in extras], y)

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
