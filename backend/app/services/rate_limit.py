"""Minimal in-memory sliding-window rate limiter (R3).

Used to bound abuse of the public early-access signup endpoint. Keys are
ephemeral — held only in process memory and never persisted, so no raw IP
addresses are stored for attribution or analytics.

The limiter is per-process: in multi-worker deployments each worker keeps its
own counters. That is an accepted limitation for the pre-launch waitlist; a
shared store (e.g. Redis) can replace it later without changing callers.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        """Record one attempt for ``key``; True when under the limit."""
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            # Bound memory: opportunistically drop idle keys.
            if len(self._hits) > 10_000:
                stale = [k for k, dq in self._hits.items() if not dq or dq[-1] <= cutoff]
                for k in stale:
                    self._hits.pop(k, None)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
