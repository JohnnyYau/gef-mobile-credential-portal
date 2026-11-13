"""rate_limit.py — in-memory sliding-window rate limiter (demo grade).

Per-client-IP accounting in one process. Suited for the single-worker demo
deployment (uvicorn default); a production multi-worker setup would use Redis.
"""

import threading
import time
from collections import deque


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
