from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_PUBLIC_PATHS = {"/api/health", "/api/integrations/feishu/webhook"}


class RateLimiter:
    """Simple token-bucket per key, in-memory."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self._window_seconds
        # Remove expired entries
        self._buckets[key] = [t for t in self._buckets[key] if t > cutoff]
        if len(self._buckets[key]) >= self._max_requests:
            return False
        self._buckets[key].append(now)
        return True

    def retry_after_seconds(self, key: str) -> int:
        if not self._buckets[key]:
            return 1
        oldest = min(self._buckets[key])
        return max(1, int(oldest + self._window_seconds - time.time()) + 1)


class AuthMiddleware(BaseHTTPMiddleware):
    """ASGI middleware for API key authentication and rate limiting.

    Reads Authorization: Bearer <key> or X-API-Key: <key>.
    Sets request.state.user_id on success.
    Public paths (/api/health, feishu webhook) are exempt.
    """

    def __init__(
        self,
        app,
        api_keys: dict[str, str],
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        super().__init__(app)
        self._api_keys = api_keys
        self._rate_limiter = rate_limiter

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip auth for public paths
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        # Extract API key
        api_key = self._extract_key(request)
        if not api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "缺少 API Key。请在 Authorization 头或 X-API-Key 头中提供。"},
            )

        # Look up user
        user_id = self._api_keys.get(api_key)
        if user_id is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "无效的 API Key。"},
            )

        # Rate limiting
        if self._rate_limiter is not None and not self._rate_limiter.is_allowed(api_key):
            retry_after = self._rate_limiter.retry_after_seconds(api_key)
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后重试。"},
                headers={"Retry-After": str(retry_after)},
            )

        # Attach user_id to request state
        request.state.user_id = user_id

        return await call_next(request)

    def _extract_key(self, request: Request) -> str | None:
        # Authorization: Bearer <key>
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:].strip()

        # X-API-Key: <key>
        x_api_key = request.headers.get("X-API-Key", "").strip()
        if x_api_key:
            return x_api_key

        # api_key query parameter (for SSE EventSource which cannot set headers)
        query_key = request.query_params.get("api_key", "").strip()
        if query_key:
            return query_key

        return None
