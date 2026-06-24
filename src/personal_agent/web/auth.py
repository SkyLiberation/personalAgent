from __future__ import annotations

import logging
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from personal_agent.core.rate_limit import InMemoryRateLimiter

logger = logging.getLogger(__name__)

_PUBLIC_PATHS = {"/api/health"}


class RateLimiter:
    """Per-API-key transport rate limiter with a fixed limit/window.

    Thin adapter over the shared :class:`~personal_agent.core.rate_limit.InMemoryRateLimiter`
    so the transport edge and the tool gateway share one sliding-window engine.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._limiter = InMemoryRateLimiter()

    def is_allowed(self, key: str) -> bool:
        return self._limiter.allow(
            key, limit=self._max_requests, window_seconds=self._window_seconds
        )

    def retry_after_seconds(self, key: str) -> int:
        return self._limiter.retry_after(key, window_seconds=self._window_seconds)


class AuthMiddleware(BaseHTTPMiddleware):
    """ASGI middleware for API key authentication and rate limiting.

    Reads Authorization: Bearer <key> or X-API-Key: <key>.
    Sets request.state.user_id on success.
    Public paths (/api/health) are exempt.
    """

    def __init__(
        self,
        app,
        api_keys: dict[str, str],
        rate_limiter: RateLimiter | None = None,
        admin_api_keys: dict[str, str] | None = None,
    ) -> None:
        super().__init__(app)
        self._api_keys = api_keys
        self._admin_api_keys = admin_api_keys or {}
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

        # Look up user — admin keys also resolve to a user_id and gain admin scope.
        is_admin = api_key in self._admin_api_keys
        user_id = self._admin_api_keys.get(api_key) or self._api_keys.get(api_key)
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

        # Attach identity to request state
        request.state.user_id = user_id
        request.state.is_admin = is_admin

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
