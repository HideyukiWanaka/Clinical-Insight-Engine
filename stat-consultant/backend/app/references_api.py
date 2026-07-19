"""REST /api/references — save a user reference (Step 4).

Markdown/text/PDF (text layer only); image handling is Step 9. The file is
saved into the single ``user_references/`` folder and the in-process library
is reloaded so the next chat turn can ground on it. No approval flow, no
hierarchy.
"""

from __future__ import annotations

import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .origins import require_local_origin

router = APIRouter(tags=["references"])

_MAX_TEXT_BYTES = 1_000_000  # 1 MB is ample for a text/Markdown reference
_MAX_PDF_BYTES = 20_000_000  # papers often carry figures; cap at 20 MB


def _extract_pdf_text(raw: bytes) -> str:
    """Extract the text layer from a PDF. Raises HTTPException if there is none."""
    try:
        reader = PdfReader(io.BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages]
    except PdfReadError:
        raise HTTPException(status_code=415, detail="PDFを読み込めませんでした") from None
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text:
        # Scanned/image-only PDF — no text layer to extract. OCR is out of scope.
        raise HTTPException(
            status_code=422,
            detail="PDFからテキストを抽出できませんでした（スキャン画像PDFの可能性があります）",
        )
    return text


@router.post("/api/references", dependencies=[Depends(require_local_origin)])
async def upload_reference(
    request: Request, file: UploadFile = File(...)
) -> dict[str, object]:
    """Persist an uploaded Markdown/text/PDF reference and reflect it into the index."""
    raw = await file.read()
    filename = file.filename or "reference.md"
    is_pdf = filename.lower().endswith(".pdf") or file.content_type == "application/pdf"

    if is_pdf:
        if len(raw) > _MAX_PDF_BYTES:
            raise HTTPException(status_code=413, detail="file too large")
        content = _extract_pdf_text(raw)
        filename = Path(filename).stem + ".md"
    else:
        if len(raw) > _MAX_TEXT_BYTES:
            raise HTTPException(status_code=413, detail="file too large")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            # Non-UTF-8, non-PDF (e.g. an image) — not a supported reference.
            raise HTTPException(status_code=415, detail="text/markdown/pdf only") from None

    library = request.app.state.references
    name = library.save(filename, content)
    return {"status": "ok", "filename": name, "count": len(library.docs)}
