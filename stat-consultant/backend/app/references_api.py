"""REST /api/references — save a user reference (Step 4).

Markdown/text only (SPEC 5.6); image handling is Step 9. The file is saved into
the single ``user_references/`` folder and the in-process library is reloaded so
the next chat turn can ground on it. No approval flow, no hierarchy.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

router = APIRouter(tags=["references"])

_MAX_BYTES = 1_000_000  # 1 MB is ample for a text/Markdown reference


@router.post("/api/references")
async def upload_reference(
    request: Request, file: UploadFile = File(...)
) -> dict[str, object]:
    """Persist an uploaded Markdown/text reference and reflect it into the index."""
    raw = await file.read()
    if len(raw) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="file too large")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        # Non-UTF-8 (e.g. an image) — not a text reference. Images are Step 9.
        raise HTTPException(status_code=415, detail="text/markdown only") from None

    library = request.app.state.references
    name = library.save(file.filename or "reference.md", content)
    return {"status": "ok", "filename": name, "count": len(library.docs)}
