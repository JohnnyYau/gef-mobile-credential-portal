"""rate_limit.py — rate limiting (demo grade, pluggable backend).

Per-client-IP accounting in one process. Suited for the single-worker demo
deployment (uvicorn default). ``RateLimiter`` is the seam a multi-worker
deployment plugs into: the in-memory implementation stays the default, and a
shared store (Redis) can be dropped in behind the same two methods.
"""

import threading
import time
from collections import deque
from typing import Protocol


class RateLimiter(Protocol):
    """Minimal contract shared by all limiter backends."""

    def allow(self, key, limit) -> bool:
        """True if ``key`` may spend one more request under ``limit``."""
        ...


class SlidingWindowLimiter:
    def __init__(self, window_seconds=60):
        self.window = window_seconds
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key, limit):
        """True if the key is under ``limit`` requests in the window."""
        if limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            queue = self._hits.get(key)
            if queue is None:
                queue = self._hits[key] = deque()
            while queue and now - queue[0] > self.window:
                queue.popleft()
            if len(queue) >= limit:
                return False
            queue.append(now)
            if len(self._hits) > 2048:  # bounded memory
                cutoff = now - self.window
                self._hits = {k: q for k, q in self._hits.items()
                              if q and q[-1] > cutoff}
            return True


# TODO[external-redis]: multi-worker deployments need a counter shared across
# processes — the dict above is per-process, so N workers each allow `limit`
# requests. A Redis-backed implementation satisfies RateLimiter with
# INCR + EXPIRE (fixed window) or a sorted-set sliding window, selected by
# configuration. Not implemented here: adding a Redis client would break the
# zero-dependency demo install, so the in-memory limiter stays the default.
