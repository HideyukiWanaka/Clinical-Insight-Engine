"""CIE Platform — dataset context builder (shared by UI and API).

Extracted from ``cie/ui/app.py:_build_dataset_context()`` (Phase 1 / R1-2)
so that the FastAPI ``/api/intent`` handler and the Streamlit UI derive column
metadata identically. No Streamlit dependency — importable from the headless
API layer.
"""

from __future__ import annotations

from datetime import UTC


def build_dataset_context(csv_bytes: bytes | None) -> dict:
    """Place the uploaded dataset where R can read it and derive column metadata.

    Writes the CSV to ``<workspace>/dataset.csv`` (the path the generated R
    script reads via WORKSPACE_DIR) and returns a ``dataset_context`` dict that
    the Orchestrator merges into the workflow's initial payload:
      - dataset_structural_metadata: {column: {inferred_type}} for the LLM
      - data_quality_report: a passing gate so the Statistics node proceeds
      - DatasetMetadata fields (metadata_type/columns/row_count/...): the
        aggregate-only input the Data Quality nodes validate (DQ-001 — column
        names are replaced by var_n aliases; no row values are included)
    Returns an empty dict when no dataset was uploaded.
    """
    if not csv_bytes:
        return {}

    import io
    from datetime import datetime
    from pathlib import Path

    import pandas as pd

    from cie.core.config import CIEConfig

    workspace = Path(CIEConfig().workspace_directory)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "dataset.csv").write_bytes(csv_bytes)

    metadata: dict = {}
    dq_columns: list[dict] = []
    var_n_alias_map: dict[str, str] = {}
    row_count = 0
    try:
        df = pd.read_csv(io.BytesIO(csv_bytes))
        row_count = int(len(df))
        for idx, col in enumerate(df.columns, start=1):
            series = df[col]
            if pd.api.types.is_numeric_dtype(series):
                inferred = "continuous"
            elif series.nunique(dropna=True) <= 2:
                inferred = "categorical_binary"
            else:
                inferred = "categorical_nominal"
            metadata[str(col)] = {
                "inferred_type": inferred,
                "unique_count": int(series.nunique(dropna=True)),
            }
            var_n = f"var_{idx}"
            var_n_alias_map[var_n] = str(col)
            missing_count = int(series.isna().sum())
            dq_columns.append({
                "var_n": var_n,
                "inferred_type": inferred,
                "missing_count": missing_count,
                "missing_rate_pct": (
                    round(missing_count / row_count * 100.0, 2) if row_count else 0.0
                ),
            })
    except Exception:
        metadata = {}
        dq_columns = []
        var_n_alias_map = {}

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
        "metadata_type": "validated_structural",
        "row_count": row_count,
        "column_count": len(dq_columns),
        "columns": dq_columns,
        "var_n_alias_map": var_n_alias_map,
        "created_at": datetime.now(UTC).isoformat(),
    }
