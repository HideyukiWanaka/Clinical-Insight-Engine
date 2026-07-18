"""REST /api/rstudio — send-to-RStudio plumbing (Step 5).

``POST /insert`` queues one code block; ``GET /pending`` drains the queue
(poll-and-consume, so the Addin poll loop never re-inserts the same code twice).

Auth boundary (Step 6): only ``GET /pending`` is gated by the local shared
secret (see rstudio_auth.py). ``POST /insert`` stays open to the same-origin
browser — it has no way to read the local secret file, and per SPEC 5.1 a
manual token-paste UI is explicitly out of scope. The token's job is "only a
process with filesystem access to this OS user's home may drain the queue"
(i.e. the RStudio Addin), not "authenticate the browser". Environment scanning
is Step 7 and out of scope here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .rstudio_auth import require_rstudio_token

router = APIRouter(prefix="/api/rstudio", tags=["rstudio"])


class InsertBody(BaseModel):
    code: str
    language: str = "r"


@router.post("/insert")
def insert(body: InsertBody, request: Request) -> dict[str, object]:
    """Queue one code block for the (not-yet-existing) RStudio Addin to consume."""
    if not body.code.strip():
        raise HTTPException(status_code=400, detail="code is empty")
    queue = request.app.state.rstudio_queue
    item = queue.push(body.code, body.language)
    return {"status": "ok", "id": item.id, "pending_count": len(queue)}


@router.get("/pending", dependencies=[Depends(require_rstudio_token)])
def pending(request: Request) -> dict[str, object]:
    """Return and clear all queued code blocks (Addin-only; token-gated)."""
    queue = request.app.state.rstudio_queue
    return {"items": [item.as_dict() for item in queue.drain()]}
