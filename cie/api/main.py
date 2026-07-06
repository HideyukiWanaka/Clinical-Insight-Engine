"""CIE Platform — FastAPI application (Phase 1 / R1-2).

Implements ``spec/api/rest-api-contract.md``:
- §1: thin wrapper over the shared service container (``cie/api/services.py``).
- §2: ``X-CIE-Token`` session-token auth on every ``/api/*`` and ``/ws/*``.
- Binds to ``127.0.0.1`` only (ADR-0005 — local leakage risk reduction). CORS
  is restricted to same-origin localhost.

Startup builds the service graph once (off the event loop via
``asyncio.to_thread`` because ``build_services`` uses ``asyncio.run``
internally) and mints a random session token, exposed to the launcher on
stdout and, for tests, on ``app.state.session_token``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from cie.api.models import ErrorResponse
from cie.api.routes import (
    dataset,
    files,
    intent,
    knowledge,
    propose,
    report,
    run,
    visualize,
    ws_console,
)

_log = logging.getLogger(__name__)

TOKEN_HEADER = "X-CIE-Token"
# Auth applies to these path prefixes (rest-api-contract §2). The WebSocket
# route authenticates via its first message, not this HTTP middleware.
_PROTECTED_PREFIXES = ("/api/",)
_CORS_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"


class SessionTokenMiddleware(BaseHTTPMiddleware):
    """Reject any ``/api/*`` request whose ``X-CIE-Token`` is missing/wrong.

    Second wall against accidental network exposure (§2). CORS preflight
    (``OPTIONS``) is allowed through so browsers can negotiate.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Enforce the session token on protected prefixes."""
        path = request.url.path
        if request.method != "OPTIONS" and any(
            path.startswith(p) for p in _PROTECTED_PREFIXES
        ):
            expected = request.app.state.session_token
            provided = request.headers.get(TOKEN_HEADER)
            if not provided or not secrets.compare_digest(provided, expected):
                return JSONResponse(
                    status_code=401,
                    content=ErrorResponse(
                        error_code="UNAUTHORIZED",
                        message="Missing or invalid session token.",
                        detail=f"Provide the {TOKEN_HEADER} header issued at startup.",
                    ).model_dump(),
                )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the service graph once and mint the session token."""
    if not getattr(app.state, "services", None):
        # build_services() uses asyncio.run internally; run it off this loop.
        app.state.services = await asyncio.to_thread(_build_services_safe)
    if not getattr(app.state, "session_token", None):
        app.state.session_token = os.environ.get(
            "CIE_API_SESSION_TOKEN"
        ) or secrets.token_urlsafe(32)
    _log.info("CIE API ready. Session token issued (X-CIE-Token).")
    # The launcher hands this to the frontend exactly once (§2).
    print(f"[CIE-API] {TOKEN_HEADER}={app.state.session_token}", flush=True)  # noqa: T201
    yield


def _build_services_safe() -> dict:
    from cie.api.services import build_services

    return build_services()


def create_app(services: dict | None = None, session_token: str | None = None) -> FastAPI:
    """Construct the FastAPI app.

    Args:
        services: Pre-built service container (tests inject a shared/mocked one).
            When ``None``, the lifespan builds it at startup.
        session_token: Fixed token (tests). When ``None``, a random one is
            minted at startup.

    Returns:
        The configured :class:`FastAPI` application.
    """
    app = FastAPI(
        title="CIE Platform API",
        version="1.0.0",
        description="REST/WebSocket contract for the CIE IDE frontend (Phase 1).",
        lifespan=lifespan,
    )
    if services is not None:
        app.state.services = services
    if session_token is not None:
        app.state.session_token = session_token

    app.add_middleware(SessionTokenMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=_CORS_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(dataset.router)
    app.include_router(intent.router)
    app.include_router(propose.router)
    app.include_router(run.router)
    app.include_router(visualize.router)
    app.include_router(report.router)
    app.include_router(files.router)
    app.include_router(knowledge.router)
    app.include_router(ws_console.router)

    return app


app = create_app()


def serve() -> None:
    """Launch uvicorn bound to 127.0.0.1 only (ADR-0005)."""
    import uvicorn

    uvicorn.run(
        "cie.api.main:app",
        host="127.0.0.1",
        port=int(os.environ.get("CIE_API_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    serve()
