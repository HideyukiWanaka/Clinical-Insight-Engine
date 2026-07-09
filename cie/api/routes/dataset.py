"""POST /api/dataset — register the working dataset (Phase 1 / R1-2).

Not a REST-contract §3 endpoint per se, but rest-api-contract §3.1 assumes
"データセットは POST /api/dataset で先に登録済み前提". Stores the CSV via the
shared :func:`cie.api.dataset.build_dataset_context` builder and caches the
resulting context on ``app.state`` for downstream handlers.

Excel (.xlsx/.xls) intake is a two-step flow mirroring the knowledge pipeline's
ingest → approve shape (cie/api/routes/knowledge.py): ``/dataset/excel/inspect``
parses the workbook and returns its sheet names, ``/dataset/excel/confirm``
converts the chosen sheet to CSV and feeds the same context builder — so the
downstream contract (workspace dataset.csv, var_n metadata) is identical to a
direct CSV upload.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, UploadFile

from cie.api.dataset import (
    ExcelParseError,
    build_dataset_context,
    excel_sheet_to_csv_bytes,
    list_excel_sheets,
)
from cie.api.models import ExcelConfirmRequest, ExcelInspectResponse
from cie.api.upload_limits import read_upload_bounded

router = APIRouter(prefix="/api", tags=["dataset"])

# 100 MB — generous for tabular clinical datasets while bounding memory use
# against an oversized upload (OWASP A03:2025). Shared by the CSV and Excel
# intake paths.
MAX_DATASET_BYTES = 100 * 1024 * 1024


def _dataset_summary(context: dict) -> dict:
    """Aggregate-only summary of a registered dataset — never row values."""
    return {
        "dataset_id": context.get("dataset_id", "uploaded_dataset"),
        "row_count": context.get("row_count", 0),
        "column_count": context.get("column_count", 0),
        "columns": context.get("columns", []),
    }


@router.post("/dataset")
async def register_dataset(request: Request, file: UploadFile) -> dict:
    """Store an uploaded CSV and derive its column metadata (DQ-001 aggregates).

    Returns an aggregate-only summary — never row values.
    """
    csv_bytes = await read_upload_bounded(file, MAX_DATASET_BYTES)
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
    return _dataset_summary(context)


@router.post("/dataset/excel/inspect", response_model=ExcelInspectResponse)
async def inspect_excel_dataset(
    request: Request, file: UploadFile
) -> ExcelInspectResponse:
    """Parse an uploaded Excel workbook and return its sheet names.

    The raw bytes are held in a single pending slot on ``app.state`` until the
    user confirms a sheet (single-user local app — one pending upload at a
    time; a new inspect replaces the previous pending one).
    """
    excel_bytes = await read_upload_bounded(file, MAX_DATASET_BYTES)
    if not excel_bytes:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "EMPTY_DATASET",
                "message": "Uploaded dataset is empty.",
                "detail": None,
            },
        )
    try:
        sheet_names = list_excel_sheets(excel_bytes)
    except ExcelParseError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "EXCEL_PARSE_ERROR",
                "message": "Excelファイルを読み込めませんでした。",
                "detail": str(exc),
            },
        ) from exc

    upload_id = uuid4().hex
    request.app.state.dataset_excel_pending = {
        "upload_id": upload_id,
        "bytes": excel_bytes,
    }
    return ExcelInspectResponse(upload_id=upload_id, sheet_names=sheet_names)


@router.post("/dataset/excel/confirm")
async def confirm_excel_dataset(request: Request, body: ExcelConfirmRequest) -> dict:
    """Convert the chosen sheet of a pending Excel upload and register it.

    Returns the same aggregate-only summary shape as ``POST /api/dataset``.
    """
    pending = getattr(request.app.state, "dataset_excel_pending", None)
    if pending is None or pending.get("upload_id") != body.upload_id:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "UPLOAD_NOT_FOUND",
                "message": "確認待ちのExcelアップロードが見つかりません。",
                "detail": "もう一度ファイルを選択してください。",
            },
        )
    try:
        csv_bytes = excel_sheet_to_csv_bytes(pending["bytes"], body.sheet_name)
    except ExcelParseError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "EXCEL_PARSE_ERROR",
                "message": f"シート「{body.sheet_name}」を読み込めませんでした。",
                "detail": str(exc),
            },
        ) from exc

    context = build_dataset_context(csv_bytes)
    request.app.state.dataset_context = context
    request.app.state.dataset_excel_pending = None
    return _dataset_summary(context)
