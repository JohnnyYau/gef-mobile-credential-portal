"""session_store.py — the chat session memory, behind a replaceable interface.

Batch U5.3. The store used to be a module-level dict in ``person_context``,
which meant: process-local by definition, capped by a literal, and impossible
to replace without editing the resolver.

Now the interface is explicit (``get`` / ``set`` / ``clear`` / ``__contains__``)
and the implementation is chosen by ``SESSION_BACKEND``:

  * ``memory`` (default) — in-process LRU, exactly the old behaviour.
  * ``redis``            — placeholder; see TODO[external-redis] below.

The point is not that Redis exists today. It is that a deploy with more than
one worker must not silently keep per-worker sessions, and that swap should be
a config change rather than a refactor.
"""

import logging
from collections import OrderedDict

from .config import SESSION_BACKEND, SESSION_LIMIT

logger = logging.getLogger("sessions")


class InMemorySessionStore:
    """Process-local LRU session store (the default)."""

    def __init__(self, limit=None):
        self.limit = int(limit or SESSION_LIMIT)
        self._data: OrderedDict[str, dict] = OrderedDict()

    def get(self, session_id):
        if not session_id:
            return None
        entry = self._data.get(session_id)
        if entry is not None:
            self._data.move_to_end(session_id)  # LRU touch
        return entry

    def set(self, session_id, value):
        if not session_id or value is None:
            return
        if self.limit <= 0:
            return
        if session_id in self._data:
            self._data.move_to_end(session_id)
        self._data[session_id] = value
        while len(self._data) > self.limit:
            self._data.popitem(last=False)

    def clear(self):
        self._data.clear()

    def delete(self, session_id):
        """Drop one entry (U12 R2: staff logout and expired sessions)."""
        self._data.pop(session_id, None)

    def items(self):
        """Snapshot of ``(session_id, value)`` in LRU order, oldest first.

        U14: the staff console needs to count and evict sessions *per role*,
        which the LRU cap alone cannot express. A copied list keeps callers
        from mutating the store mid-iteration.
        """
        return list(self._data.items())

    def __contains__(self, session_id):
        return session_id in self._data

    def __len__(self):
        return len(self._data)


def open_session_store(backend=None):
    """Return the configured store.

    ``redis`` is deliberately a placeholder: implementing it would need a
    connection pool, key namespacing and a serialization contract, and calling
    a fake Redis "pluggable" would be worse than saying it is not done.

    TODO[external-redis]: multi-worker session sharing. The store interface
    above is the seam; a RedisSessionStore must implement it with
    ``SESSION_LIMIT`` mapped to an expiry/TTL rather than an LRU cap.
    """
    backend = (backend or SESSION_BACKEND or "memory").lower()
    if backend == "memory":
        return InMemorySessionStore()
    if backend == "redis":
        logger.warning(
            "SESSION_BACKEND=redis is not implemented; using in-memory sessions "
            "(sessions will not be shared across workers)")
        return InMemorySessionStore()
    logger.warning("unknown SESSION_BACKEND=%r; using in-memory sessions", backend)
    return InMemorySessionStore()
