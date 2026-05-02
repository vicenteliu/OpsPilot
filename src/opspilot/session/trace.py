"""Append-only ``trace.jsonl`` writer.

* Auto-stamps ``session_id`` / ``seq`` / ``ts`` on every event.
* Validates each emitted row against ``trace-event.schema.json``
  (D5: hard requirement per session/SPEC.md §9 — trace integrity).
* On open, scans the existing file for the highest ``seq`` and resumes
  from there. Safe for resume after pause/crash; not safe for concurrent
  writers (PR-6 doesn't claim concurrency support — single orchestrator
  per session).

Usage::

    sm = SessionManager(home=...)
    sess = sm.create(...)
    with sm.trace(sess.id) as tw:
        tw.write(TraceEvent.prompt(role="user", content="hi"))
        tw.write(TraceEvent.response(content="hello", finish_reason="stop"))
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import IO, Any

from ..schemas import validate as schema_validate
from ..timeutil import now_rfc3339
from .errors import SessionError
from .types import TraceEvent


class TraceWriter:
    """Per-session append-only writer for ``trace.jsonl``.

    Use as a context manager so the file handle closes deterministically.
    Each :meth:`write` flushes immediately — observability beats throughput
    at this layer.
    """

    def __init__(
        self,
        session_dir: Path,
        *,
        session_id: str,
        validate_on_write: bool = True,
    ) -> None:
        self._path = session_dir / "trace.jsonl"
        self._session_id = session_id
        self._validate = validate_on_write
        self._fh: IO[str] | None = None
        self._next_seq = self._discover_next_seq()

    # ── Context manager ──────────────────────────────────────────────

    def __enter__(self) -> TraceWriter:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a", encoding="utf-8")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._fh is not None and not self._fh.closed:
            self._fh.flush()
            self._fh.close()
        self._fh = None

    # ── Properties ───────────────────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    @property
    def next_seq(self) -> int:
        return self._next_seq

    # ── Write ────────────────────────────────────────────────────────

    def write(self, event: TraceEvent, *, ts: str | None = None) -> dict[str, Any]:
        """Stamp the event with seq + ts, validate, and append.

        Returns the rendered row (dict) so callers can hand it to other
        consumers without round-tripping through the file.
        """
        if self._fh is None or self._fh.closed:
            raise SessionError("TraceWriter not open; use it as a context manager")

        row = event.render(
            session_id=self._session_id,
            seq=self._next_seq,
            ts=ts or now_rfc3339(),
        )

        if self._validate:
            # Surface schema errors immediately at the source — caller
            # gets a precise jsonschema message rather than a downstream
            # consumer's vague complaint.
            schema_validate("trace-event", row)

        self._fh.write(json.dumps(row, ensure_ascii=False))
        self._fh.write("\n")
        self._fh.flush()
        self._next_seq += 1
        return row

    # ── Helpers ──────────────────────────────────────────────────────

    def _discover_next_seq(self) -> int:
        """Scan the file (if any) and return ``last_seq + 1``.

        For an empty / missing file, returns 0.
        """
        if not self._path.is_file():
            return 0
        last_seq = -1
        with self._path.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    s = int(d.get("seq", -1))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if s > last_seq:
                    last_seq = s
        return last_seq + 1
