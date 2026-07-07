"""CIE Platform — in-process rate limiting (OWASP A04:2025 — Insecure Design).

A fixed-window counter keyed by client host, applied to the LLM-backed and
execution endpoints. No external dependency: the app is single-user and
127.0.0.1-bound (ADR-0005 offline-first), so an in-memory window is enough —
it exists to stop a runaway client loop from burning LLM quota or CPU, not to
defend a multi-tenant deployment.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from cie.api.models import ErrorResponse

# (path prefix, requests allowed, window in seconds). First matching prefix wins.
_RATE_LIMITS: tuple[tuple[str, int, int], ...] = (
    ("/api/intent", 10, 60),
    ("/api/propose", 10, 60),
    ("/api/run", 20, 60),
    ("/api/workspace/reset", 30, 60),
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests beyond a fixed per-client, per-endpoint quota with 429."""

    def __init__(self, app: Callable) -> None:
        """Initialise with an empty per-(client, prefix) request-timestamp store."""
        super().__init__(app)
        self._hits: dict[tuple[str, str], list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Enforce the fixed-window limit matching the request path, if any."""
        limit = self._match(request.url.path)
        if limit is not None:
            prefix, max_requests, window_seconds = limit
            client = request.client.host if request.client else "unknown"
            key = (client, prefix)
            now = time.monotonic()
            recent = [t for t in self._hits[key] if now - t < window_seconds]
            if len(recent) >= max_requests:
                retry_after = window_seconds - (now - recent[0])
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(max(1, int(retry_after)))},
                    content=ErrorResponse(
                        error_code="RATE_LIMITED",
                        message="Too many requests. Please slow down.",
                        detail=f"Limit: {max_requests} requests per {window_seconds}s "
                        f"on {prefix}.",
                    ).model_dump(),
                )
            recent.append(now)
            self._hits[key] = recent
        return await call_next(request)

    @staticmethod
    def _match(path: str) -> tuple[str, int, int] | None:
        for prefix, max_requests, window_seconds in _RATE_LIMITS:
            if path.startswith(prefix):
                return (prefix, max_requests, window_seconds)
        return None
