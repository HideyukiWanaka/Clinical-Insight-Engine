"""POST /api/dataset — register the working dataset (Phase 1 / R1-2).

Not a REST-contract §3 endpoint per se, but rest-api-contract §3.1 assumes
"データセットは POST /api/dataset で先に登録済み前提". Stores the CSV via the
shared :func:`cie.api.dataset.build_dataset_context` builder and caches the
resulting context on ``app.state`` for downstream handlers.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, UploadFile

from cie.api.dataset import build_dataset_context
from cie.api.upload_limits import read_upload_bounded

router = APIRouter(prefix="/api", tags=["dataset"])

# 100 MB — generous for tabular clinical datasets while bounding memory use
# against an oversized upload (OWASP A03:2025).
MAX_CSV_BYTES = 100 * 1024 * 1024


@router.post("/dataset")
async def register_dataset(request: Request, file: UploadFile) -> dict:
    """Store an uploaded CSV and derive its column metadata (DQ-001 aggregates).

    Returns an aggregate-only summary — never row values.
    """
    csv_bytes = await read_upload_bounded(file, MAX_CSV_BYTES)
    if not csv_bytes:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "EMPTY_DATASET",
                "message": "Uploaded dataset is empty.",
                "detail": None,
            },
        )
    context = build_dataset_context(csv_bytes)
    request.app.state.dataset_context = context
    return {
        "dataset_id": context.get("dataset_id", "uploaded_dataset"),
        "row_count": context.get("row_count", 0),
        "column_count": context.get("column_count", 0),
        "columns": context.get("columns", []),
    }
