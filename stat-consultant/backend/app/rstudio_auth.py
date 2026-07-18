"""Local shared-secret token for the RStudio Addin (Step 6).

Zero-config auth: a random token is generated fresh at every backend process
start and written to a well-known path under the user's home directory
(``~/.stat-consultant/rstudio_token``). The Addin re-reads this file on every
poll cycle (no caching), so it self-heals across backend restarts without the
user re-invoking the Addin.

Protects only ``GET /pending`` — see rstudio_api.py for the boundary
rationale. ``POST /insert`` stays open to the same-origin browser, which has
no way to read a local file and (per SPEC 5.1) must not require a manual
token-paste UI.
"""

from __future__ import annotations

import hmac
import secrets
import stat
from pathlib import Path

from fastapi import Header, HTTPException, Request

# Home-anchored so an installed R Addin (which has no notion of where this repo
# lives) can independently resolve the same path. macOS/Linux agree via $HOME;
# on Windows Python's Path.home() (USERPROFILE) may differ from R's
# path.expand("~") (R_USER/HOME) — the startup log below prints the absolute
# path so a mismatch is self-diagnosable rather than a silent hang.
TOKEN_DIR = Path.home() / ".stat-consultant"
TOKEN_PATH = TOKEN_DIR / "rstudio_token"


def generate_and_write_token() -> str:
    """(Re)write the shared-secret file with a fresh token; owner-only perms.

    Returns the token so the caller can stash it on ``app.state`` for the
    per-request comparison in :func:`require_rstudio_token`.
    """
    token = secrets.token_urlsafe(32)
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token, encoding="utf-8")
    try:
        TOKEN_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        # chmod is largely inert on Windows; harmless to skip.
        pass
    print(f"[stat-consultant] RStudio shared secret written to {TOKEN_PATH}")
    return token


def require_rstudio_token(
    request: Request,
    x_stat_consultant_token: str | None = Header(default=None),
) -> None:
    """FastAPI dependency: 401 unless the header matches this process's token.

    Wired onto ``GET /pending`` only. Uses a constant-time comparison so a
    token can't be recovered by timing the response.
    """
    expected: str = request.app.state.rstudio_token
    if not x_stat_consultant_token or not hmac.compare_digest(
        x_stat_consultant_token, expected
    ):
        raise HTTPException(status_code=401, detail="invalid or missing RStudio token")
