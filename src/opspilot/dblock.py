"""One lock per SQLite connection, shared by every store that drives it.

Four stores — :class:`~opspilot.kb.sqlite_store.SqliteStore`,
``InventoryStore``, ``AuthStore``, ``SettingsStore`` — are constructed over the
*same* ``sqlite3.Connection`` (see ``api/app.py``), and a fifth (``MemoryStore``)
joins them. The connection is opened with ``check_same_thread=False`` and reached
from the default multi-threaded executor, so they drive it concurrently.

``commit()`` is **connection-scoped, not thread-scoped**. A lock held by one
store therefore protects nothing: ``InventoryStore.update_asset`` committing on
the same connection ends whatever transaction ``SqliteStore`` had open, exactly
the interleaving #166 set out to stop. The guard has to belong to the
**connection**, not to any one store.

``sqlite3.Connection`` cannot be weak-referenced, so the registry is keyed by
``id()`` and holds the connection itself — connections here live for the process
and are never reclaimed, and keeping a reference guarantees the id is not reused
by a later object.
"""

from __future__ import annotations

import sqlite3
import threading

_REGISTRY_GUARD = threading.Lock()
# id(conn) → (conn, lock). The connection is retained so its id cannot be reused.
_LOCKS: dict[int, tuple[sqlite3.Connection, threading.RLock]] = {}


def lock_for(conn: sqlite3.Connection) -> threading.RLock:
    """Return the lock guarding *conn*, creating it on first use.

    Reentrant: store methods call each other (``add_correction`` reads through
    ``get_chunk``), and a store may hold the lock while another store on the same
    connection is entered from the same thread.
    """
    key = id(conn)
    with _REGISTRY_GUARD:
        existing = _LOCKS.get(key)
        if existing is not None:
            return existing[1]
        lock = threading.RLock()
        _LOCKS[key] = (conn, lock)
        return lock
