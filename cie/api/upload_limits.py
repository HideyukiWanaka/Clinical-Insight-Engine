"""CIE Platform — bounded upload reads (OWASP A03:2025 — unbounded upload DoS).

``UploadFile.read()`` with no size argument buffers the entire request body in
memory before any downstream validation (dataset size checks, IngestionGuard)
gets a chance to reject it. A single oversized upload can then exhaust memory
before the byte-count check that was supposed to stop it ever runs. Reading in
bounded chunks lets a request be rejected once it has already used
``max_bytes`` — not after the whole file sits in memory.
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile

_CHUNK_SIZE = 1024 * 1024  # 1 MB


async def read_upload_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """Read ``file`` in chunks, raising 413 the moment ``max_bytes`` is exceeded."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail={
                    "error_code": "FILE_TOO_LARGE",
                    "message": (
                        f"アップロードされたファイルが上限"
                        f"（{max_bytes // (1024 * 1024)} MB）を超えています。"
                    ),
                    "detail": None,
                },
            )
        chunks.append(chunk)
    return b"".join(chunks)
