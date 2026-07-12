"""CIE Platform — dataset context builder (shared by UI and API).

Extracted from ``cie/ui/app.py:_build_dataset_context()`` (Phase 1 / R1-2)
so that the FastAPI ``/api/intent`` handler and the Streamlit UI derive column
metadata identically. No Streamlit dependency — importable from the headless
API layer.
"""

from __future__ import annotations

import io
from datetime import UTC
from pathlib import Path


class ExcelParseError(ValueError):
    """Raised when an uploaded Excel file cannot be parsed as a workbook."""


def list_excel_sheets(excel_bytes: bytes) -> list[str]:
    """Return the sheet names of an uploaded Excel workbook (.xlsx/.xls).

    Raises :class:`ExcelParseError` when the bytes are not a readable workbook
    so the API layer can surface an explicit 400 (無言失敗禁止).
    """
    import pandas as pd

    try:
        with pd.ExcelFile(io.BytesIO(excel_bytes)) as workbook:
            return [str(name) for name in workbook.sheet_names]
    except Exception as exc:
        raise ExcelParseError(str(exc)) from exc


def excel_sheet_to_csv_bytes(excel_bytes: bytes, sheet_name: str) -> bytes:
    """Convert one sheet of an Excel workbook to CSV bytes.

    The CSV form feeds the existing :func:`build_dataset_context` unchanged, so
    the downstream contract (workspace dataset.csv, var_n column metadata) is
    identical to a direct CSV upload.
    """
    import pandas as pd

    try:
        df = pd.read_excel(io.BytesIO(excel_bytes), sheet_name=sheet_name)
    except Exception as exc:
        raise ExcelParseError(str(exc)) from exc
    return df.to_csv(index=False).encode("utf-8")


def build_dataset_context(
    csv_bytes: bytes | None,
    *,
    workspace_dir: str | Path,
    source_name: str | None = None,
) -> dict:
    """Place the uploaded dataset where R can read it and derive column metadata.

    ``workspace_dir`` must be the same path the rest of the running process
    was wired to at startup (``services["workspace_dir"]`` — see
    ``cie/api/services.py``), not re-read from :class:`CIEConfig` here. The
    storage-location setting can be changed via ``POST
    /api/settings/storage/workspace_directory``, but that only writes ``.env``
    for the *next* launch (every already-wired R executor/agent keeps the old
    path in memory) — re-reading config fresh in this function would make
    dataset uploads jump to the new path immediately while everything else
    still writes to the old one.

    ``source_name`` is the user-facing origin label (original filename, plus
    the sheet name for Excel) kept only so the UI can show *which* file is the
    current 解析対象 — it is echoed back in dataset summaries and never enters
    the LLM/agents payload.

    Writes the CSV to ``<workspace>/dataset.csv`` (the path the generated R
    script reads via WORKSPACE_DIR) and returns a ``dataset_context`` dict that
    the Orchestrator merges into the workflow's initial payload:
      - dataset_structural_metadata: {var_n: {inferred_type, unique_count,
        name?}} for the LLM. ``name`` carries the *real* column header so the
        Planner can map the user's words ("血圧") to the right column — but
        ONLY for columns that pass the Layer-1 column-name PII scan
        (:class:`PIIDetectorLayer1`). PII-signalling headers (患者氏名, 患者ID,
        …) keep their var_n alias with no ``name`` so no patient identifier
        reaches the LLM. Header *names* are structural metadata, not row values
        (DQ-001 governs row values); the Planner contract (agents/planner.yaml)
        explicitly lists "Header names" as allowed input.
      - data_quality_report: a passing gate so the Statistics node proceeds
      - DatasetMetadata fields (metadata_type/columns/row_count/...): the
        aggregate-only input the Data Quality nodes validate (DQ-001 — no row
        values are included)
    Returns an empty dict when no dataset was uploaded.

    The on-disk ``dataset.csv`` is re-encoded as BOM-free UTF-8 (rather than the
    verbatim upload bytes) so the generated R ``read.csv`` reads clean headers:
    a UTF-8 BOM + multibyte (e.g. Japanese) headers under R's default C/POSIX
    locale corrupt the first column name and break ``outcome_var %in%
    names(data)`` lookups (a common cause of exit_code=1). ``r_executor.py`` is
    intentionally left unmodified (CLAUDE.md / ADR-0005 RT-002).
    """
    if not csv_bytes:
        return {}

    from datetime import datetime

    import pandas as pd

    from cie.security.pii_detector import PIIDetectorLayer1

    workspace = Path(workspace_dir)
    workspace.mkdir(parents=True, exist_ok=True)

    metadata: dict = {}
    dq_columns: list[dict] = []
    var_n_alias_map: dict[str, str] = {}
    pii_masked_vars: list[str] = []
    pii_detector = PIIDetectorLayer1()
    row_count = 0
    normalized_csv_bytes = csv_bytes
    try:
        df = pd.read_csv(io.BytesIO(csv_bytes))
        # Re-serialize without a BOM so R's read.csv sees clean UTF-8 headers
        # even under a C/POSIX locale (Fix D). pandas already decoded any BOM.
        normalized_csv_bytes = df.to_csv(index=False).encode("utf-8")
        row_count = int(len(df))
        for idx, col in enumerate(df.columns, start=1):
            series = df[col]
            if pd.api.types.is_numeric_dtype(series):
                inferred = "continuous"
            elif series.nunique(dropna=True) <= 2:
                inferred = "categorical_binary"
            else:
                inferred = "categorical_nominal"
            var_n = f"var_{idx}"
            # Column-name PII scan: a signalling header (patient name/ID, DOB,
            # phone, address, …) is never revealed to the LLM — it keeps its
            # var_n alias only. Non-PII measurement headers carry their real
            # name so the Planner can resolve intent → column semantically.
            is_pii = bool(pii_detector.detect_column_name(str(col)))
            metadata[var_n] = {
                "inferred_type": inferred,
                "unique_count": int(series.nunique(dropna=True)),
            }
            if is_pii:
                pii_masked_vars.append(var_n)
            else:
                metadata[var_n]["name"] = str(col)
            var_n_alias_map[var_n] = str(col)
            missing_count = int(series.isna().sum())
            dq_columns.append({
                "var_n": var_n,
                # Original header, shown only in the local UI (never sent to
                # the LLM/agents pipeline — DQ-001 is about row *values*, not
                # column names) so the user can verify which real column the
                # AI's var_n reference actually points to.
                "original_name": str(col),
                "inferred_type": inferred,
                "missing_count": missing_count,
                "missing_rate_pct": (
                    round(missing_count / row_count * 100.0, 2) if row_count else 0.0
                ),
                "pii_masked": is_pii,
            })
    except Exception:
        metadata = {}
        dq_columns = []
        var_n_alias_map = {}
        pii_masked_vars = []
        normalized_csv_bytes = csv_bytes

    (workspace / "dataset.csv").write_bytes(normalized_csv_bytes)

    return {
        "dataset_structural_metadata": metadata,
        # The Statistics node is gated on a passing quality report (ST-001).
        # Until the data_quality stage runs on real data, seed a passing gate
        # so the analysis proceeds; the data_quality node still runs and can
        # override this with its own findings.
        "data_quality_report": {"quality_gate_passed": True},
        # DatasetMetadata contract consumed by the Data Quality nodes
        # (validate_dataset / classify_variables / detect_missing_values /
        # detect_outliers). Aggregates only — DQ-001.
        "dataset_id": "uploaded_dataset",
        "source_name": source_name,
        "metadata_type": "validated_structural",
        "row_count": row_count,
        "column_count": len(dq_columns),
        "columns": dq_columns,
        "var_n_alias_map": var_n_alias_map,
        # var_n aliases whose real header signalled PII — display code must not
        # reveal their original_name in the chat (Fix C).
        "pii_masked_vars": pii_masked_vars,
        "created_at": datetime.now(UTC).isoformat(),
    }
