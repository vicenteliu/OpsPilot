"""Schema registry: discover and validate against the spec's JSON schemas.

The 7 top-level dirs (providers/, memory/, session/, sandbox/, harness/,
skills/, wiki/) each have a ``schemas/`` subdirectory. This module auto-
discovers all ``*.schema.json`` files and exposes:

* :func:`registry`        — name → schema dict
* :func:`get_schema`      — fetch one
* :func:`validate`        — run jsonschema against an instance
* :func:`load_data`       — load .json/.jsonl/.yaml from disk
* :func:`iter_items`      — yield items from a list-or-single payload
* :func:`infer_schema_name` — path → schema name (for CLI ``validate``)
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from .errors import SchemaError

# Repo root: src/opspilot/schemas.py → src/opspilot → src → repo
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

# Spec dirs that may contain schemas/.
SCHEMA_SEARCH_DIRS: tuple[str, ...] = (
    "providers",
    "memory",
    "session",
    "sandbox",
    "harness",
    "skills",
    "wiki",
    "orchestrator",  # PR-7: incident_summary_v1 + future playbook output schemas
)


def _discover_schemas(repo_root: Path) -> dict[str, dict[str, Any]]:
    """Scan ``{repo_root}/{dir}/schemas/*.schema.json`` and return mapping by name.

    *name* = filename without ``.schema.json`` suffix (e.g. ``kb-document``).
    Raises :class:`SchemaError` on duplicate names.
    """
    out: dict[str, dict[str, Any]] = {}
    for d in SCHEMA_SEARCH_DIRS:
        sd = repo_root / d / "schemas"
        if not sd.is_dir():
            continue
        for f in sorted(sd.glob("*.schema.json")):
            name = f.name.removesuffix(".schema.json")
            with f.open(encoding="utf-8") as fh:
                schema = json.load(fh)
            if name in out:
                msg = (
                    f"Duplicate schema name '{name}': "
                    f"{out[name].get('$id', '?')} vs {schema.get('$id', f)}"
                )
                raise SchemaError(msg, schema_name=name)
            out[name] = schema
    return out


@lru_cache(maxsize=4)
def registry(repo_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Cached schema registry. Pass ``repo_root=None`` to use auto-detected root."""
    return _discover_schemas(repo_root or REPO_ROOT)


def get_schema(name: str, *, repo_root: Path | None = None) -> dict[str, Any]:
    """Return the schema with the given name. Raises :class:`SchemaError` if missing."""
    reg = registry(repo_root)
    if name not in reg:
        msg = f"Schema '{name}' not registered. Known: {sorted(reg)}"
        raise SchemaError(msg, schema_name=name)
    return reg[name]


def validate(name: str, instance: Any, *, repo_root: Path | None = None) -> None:
    """Validate *instance* against schema *name*. Raises :class:`SchemaError` on failure."""
    schema = get_schema(name, repo_root=repo_root)
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as e:
        path = ".".join(str(p) for p in e.absolute_path) or "<root>"
        msg = f"[{name}] at {path}: {e.message}"
        raise SchemaError(msg, schema_name=name) from e


# ──────────────────────────────────────────────────────────────────────────
#  File loaders
# ──────────────────────────────────────────────────────────────────────────


def load_data(path: Path) -> Any:
    """Load a ``.json`` / ``.yaml`` / ``.yml`` / ``.jsonl`` file.

    For ``.jsonl`` returns a list of objects (one per non-blank line).
    """
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        return json.loads(text)
    if suffix in (".yaml", ".yml"):
        return yaml.safe_load(text)
    if suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    msg = f"Unsupported file extension: {path}"
    raise SchemaError(msg, path=str(path))


def iter_items(data: Any) -> Iterable[Any]:
    """Yield items from a single object OR a list (used for jsonl)."""
    if isinstance(data, list):
        yield from data
    else:
        yield data


# ──────────────────────────────────────────────────────────────────────────
#  Path → schema name inference (for CLI `opspilot validate <dir>`)
# ──────────────────────────────────────────────────────────────────────────


def infer_schema_name(path: Path) -> str | None:
    """Best-effort guess of which schema to validate *path* against.

    Returns ``None`` for files we shouldn't try to validate (templates,
    SKILL.md frontmatter-only files, etc.). Test cases live in
    ``tests/test_schemas.py::TestInfer``.
    """
    parts = path.parts
    name = path.name

    # Templates (anything under templates/) — skip; they're for humans, not validation.
    if "templates" in parts:
        return None

    # Schemas themselves — skip.
    if "schemas" in parts and name.endswith(".schema.json"):
        return None

    # Sandbox leftover files start with `_`.
    if name.startswith("_"):
        return None

    # KB
    if name == "doc-meta.json":
        return "kb-document"
    if name == "chunks.jsonl":
        return "kb-chunk"

    # Retrieval (single schema with oneOf for request/response)
    if "retrieval" in parts and name in ("request.json", "response.json"):
        return "retrieval-query"

    # Session
    if name == "meta.yaml" and "session" in parts and "variants" not in parts:
        return "session"
    if name == "trace.jsonl":
        return "trace-event"

    # Harness
    if name == "fixture.json":
        return "fixture"
    if name == "results.jsonl" or name.endswith("-results.jsonl"):
        return "eval-result"

    # Iteration
    if path.parent.name == "iteration" and name in ("recipe.yaml", "record.yaml"):
        return "iteration"

    # Skill variants
    if "variants" in parts and name == "meta.yaml":
        return "skill-variant"

    # Feedback signals
    if name == "signals.jsonl" and "feedback" in parts:
        return "feedback-signal"

    # Wiki has its own page schema but pages live under `wiki/pages/<kind>/`,
    # which is a runtime layout (not in the spec's templates/). Skip for now.

    return None
