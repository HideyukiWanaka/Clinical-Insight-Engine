"""CIE Platform — Pydantic payload models for inter-agent contracts.

Each class maps to the corresponding JSON Schema in ``schemas/`` and provides
type-safe Python access to validated inter-agent payloads.

These models are used for *construction and consumption* of payloads in Python
code.  Cross-boundary validation is always performed by
:class:`~cie.schemas.validator.SchemaRegistry` against the canonical JSON
Schema definitions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ColumnMetadata(BaseModel):
    """Structural metadata for a single anonymised dataset column.

    Corresponds to ``ColumnMetadata`` in ``schemas/dataset.schema.json``.
    No row-level content is ever stored here.
    """

    var_n: Annotated[str, Field(pattern=r"^var_[0-9]+$")]
    inferred_type: Literal[
        "continuous",
        "categorical_binary",
        "categorical_ordinal",
        "categorical_nominal",
        "date",
        "text",
        "unknown",
    ]
    missing_count: int
    missing_rate_pct: float = Field(ge=0.0, le=100.0)
    summary_stats: dict | None = None
    clinical_range_violation: bool | None = None


class DatasetMetadata(BaseModel):
    """Structural metadata for a full dataset passed between agents.

    Corresponds to the root object in ``schemas/dataset.schema.json``.
    Raw patient record content is never included.
    """

    dataset_id: str
    execution_id: str
    metadata_type: Literal["proxy_metadata", "validated_structural"]
    source_file_hash: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")] | None = None
    row_count: int
    column_count: int
    columns: list[ColumnMetadata]
    var_n_alias_map: dict[str, str] | None = None
    quality_gate_passed: bool | None = None
    created_at: datetime


class IntentObject(BaseModel):
    """Structured clinical research intent produced by the Planner Agent.

    Corresponds to ``IntentObject`` in ``schemas/analysis-request.schema.json``.
    Per ADR-0001, this object never carries a ``workflow_id`` field.
    """

    objective: Literal[
        "between_group_comparison",
        "paired_comparison",
        "correlation_analysis",
        "regression_analysis",
        "survival_analysis",
        "diagnostic_accuracy",
        "prediction_model",
        "descriptive_only",
        "systematic_review",
    ]
    outcome_type: str
    predictor_type: str | None = None
    paired: bool | None = None
    subject_id_var: Annotated[str, Field(pattern=r"^var_[0-9]+$")] | None = None
    n_groups_estimate: int | None = None
    sample_size_estimate: int | None = None
    distribution_assumptions: str = "unknown"
    reporting_checklist_inference: str | None = None
    natural_language_summary: str | None = None
    outcome_variables: list[dict] = []
    predictor_variables: list[dict] = []


class AnalysisRequest(BaseModel):
    """Planner Agent output consumed by the Statistics Agent.

    Corresponds to the root object in ``schemas/analysis-request.schema.json``.
    """

    execution_id: str
    intent_object: IntentObject
    confidence_score: float = Field(ge=0.0, le=1.0)
    requires_human_clarification: bool
    clarification_options: list[dict] = []
    created_at: datetime
