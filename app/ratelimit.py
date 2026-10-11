import math
import threading
import time
from collections import defaultdict, deque
from typing import Callable

from app.errors import RateLimitedError


class RateLimiter:
    """In-memory sliding-window limiter, per key. Single process only (not distributed)."""

    def __init__(self, limit: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key_id: str) -> None:
        """Record one request for the key, or raise RateLimitedError when over the limit."""
        now = self._clock()
        with self._lock:
            hits = self._hits[key_id]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = max(1, math.ceil(self.window - (now - hits[0])))
                raise RateLimitedError(retry_after)
            hits.append(now)  # rejected requests are not counted
