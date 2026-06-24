"""Shared rate-limiting abstraction.

Both the HTTP transport layer (``web/auth.py``, per API key) and the tool gateway
(``tools/gateway.py``, per tool+user) previously carried their own in-memory
sliding-window limiter with different keys and windows. This is the single
implementation behind a ``RateLimiter`` Protocol; each consumer keeps its own
key scheme and limit, but the windowing logic lives in one place. A durable
(e.g. Postgres/Redis) limiter can later implement the same Protocol.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable, Protocol


class RateLimiter(Protocol):
    """Per-key fixed-window rate limiter."""

    def allow(self, key: str, *, limit: int, window_seconds: float = 60.0) -> bool:
        """Record a hit for ``key`` and return whether it is within ``limit``."""
        ...

    def retry_after(self, key: str, *, window_seconds: float = 60.0) -> int:
        """Seconds until the oldest hit in ``key``'s window expires (>= 1)."""
        ...


class InMemoryRateLimiter:
    """Process-local sliding window keyed by an opaque string.

    ``limit <= 0`` means "unlimited" (the gateway uses this for tools without a
    configured ``rate_limit_per_minute``).
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._clock = clock

    def allow(self, key: str, *, limit: int, window_seconds: float = 60.0) -> bool:
        if limit <= 0:
            return True
        now = self._clock()
        window = self._windows[key]
        while window and now - window[0] >= window_seconds:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True

    def retry_after(self, key: str, *, window_seconds: float = 60.0) -> int:
        window = self._windows.get(key)
        if not window:
            return 1
        return max(1, int(window[0] + window_seconds - self._clock()) + 1)


__all__ = ["InMemoryRateLimiter", "RateLimiter"]
