"""Shared localhost-origin policy for browser-facing endpoints.

The app binds loopback only (the launch scripts start uvicorn with no
``--host``, so it defaults to ``127.0.0.1``), but "only localhost can reach the
port" does NOT mean "only our own page can drive it": any website the user has
open can issue cross-origin requests to ``http://127.0.0.1:8000`` from their
browser, and WebSocket connections are exempt from CORS entirely. So the CORS
middleware (``main.py``) and the per-request/handshake checks here share ONE
allow-rule, defined once below, to keep them from drifting apart.

Policy (threat model: real data on a researcher's personal machine — see
``docs/SECURITY.md``): allow only ``http://localhost`` / ``http://127.0.0.1``
(any port). A request with **no** ``Origin`` header is allowed — browsers always
send ``Origin`` on cross-origin requests and on WebSocket handshakes, so an
absent header means a non-browser client (curl, ``websocat``, the R Addin, a
test harness), which the loopback bind already contains. An opaque ``"null"``
origin (sandboxed iframe, ``file://``) is treated as untrusted and rejected.
"""

from __future__ import annotations

import re

from fastapi import Header, HTTPException

# The single source of truth for "is this a localhost origin". Matched with
# ``fullmatch`` so ``http://localhost.evil.com`` (and a trailing-newline
# variant, which ``$`` would wrongly accept) cannot match. Shared with
# Starlette's CORS middleware — which also fullmatches — via the string form.
ALLOW_ORIGIN_REGEX = r"http://(localhost|127\.0\.0\.1)(:\d+)?"
_ALLOW_ORIGIN_RE = re.compile(ALLOW_ORIGIN_REGEX)


def is_allowed_origin(origin: str | None) -> bool:
    """True if a browser ``Origin`` header should be allowed to drive the app.

    An absent header (``None``/empty) is allowed — that is a non-browser client,
    which the loopback bind already contains. Any present origin must match the
    localhost allow-rule exactly; ``"null"`` and remote origins are rejected.
    """
    if not origin:
        return True
    return _ALLOW_ORIGIN_RE.fullmatch(origin) is not None


def require_local_origin(origin: str | None = Header(default=None)) -> None:
    """FastAPI dependency: 403 a browser request from a non-localhost origin.

    Loopback binding stops *remote hosts* reaching the port, and CORS stops a
    remote page *reading* our responses — but neither stops a remote page from
    *sending* a state-changing request (a cross-origin ``POST`` still executes
    server-side; simple requests aren't even preflighted). Gating the open
    write endpoints on this closes that cross-origin-write / CSRF-to-localhost
    vector. The frontend (``http://localhost:5173``) passes; ``evil.com`` does
    not; a header-less non-browser client (curl / tests) is allowed.
    """
    if not is_allowed_origin(origin):
        raise HTTPException(status_code=403, detail="cross-origin request rejected")
