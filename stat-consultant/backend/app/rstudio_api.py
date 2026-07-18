"""REST /api/rstudio — send-to-RStudio plumbing (Step 5).

``POST /insert`` queues one code block; ``GET /pending`` drains the queue
(poll-and-consume, so a future Addin poll loop never re-inserts the same code
twice). No auth, no connection/heartbeat detection — the Addin itself, and the
shared-secret scheme it authenticates with, are Step 6. Environment scanning
is Step 7. Both are out of scope here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

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


@router.get("/pending")
def pending(request: Request) -> dict[str, object]:
    """Return and clear all queued code blocks."""
    queue = request.app.state.rstudio_queue
    return {"items": [item.as_dict() for item in queue.drain()]}
