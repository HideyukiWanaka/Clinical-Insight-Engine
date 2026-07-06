"""CIE Platform — FastAPI request/response models (Phase 1 / R1-2).

Pydantic models mirroring ``spec/api/rest-api-contract.md`` §3–§5. The API is a
**thin wrapper** (PROJECT_RULES.md S.4): nested domain objects (``intent_object``,
``statistical_results``, …) are kept as free-form ``dict`` payloads that already
have their own JSON Schemas under ``schemas/`` and are validated inside the
agents via ``BaseAgent.run``. These models only pin down the API envelope.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Errors (§5)
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """4xx/5xx error envelope. Never carries raw data or PII (§5)."""

    error_code: str
    message: str
    detail: str | None = None


# ---------------------------------------------------------------------------
# POST /api/intent (§3.1)
# ---------------------------------------------------------------------------


class IntentRequest(BaseModel):
    """Request body for ``POST /api/intent``."""

    prompt: str
    dataset_uploaded: bool = False


class IntentResponse(BaseModel):
    """Planner result: the intent_object (no workflow_id — ADR-0001)."""

    execution_id: str
    intent_object: dict[str, Any] = Field(default_factory=dict)
    confidence_score: float = 0.0
    requires_human_clarification: bool = False
    clarification_options: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# POST /api/propose (§3.2)
# ---------------------------------------------------------------------------


class ProposeRequest(BaseModel):
    """Initial proposal (``intent_object``) or a continuation query.

    First turn sends ``intent_object``. Follow-up analysis sends
    ``continuation_query`` + ``prior_statistical_results`` + ``prior_r_script``.
    """

    intent_object: dict[str, Any] | None = None
    continuation_query: str | None = None
    prior_statistical_results: dict[str, Any] | None = None
    prior_r_script: str | None = None


class ProposeResponse(BaseModel):
    """Conversational proposal; reason is always present on failure (§3.2)."""

    execution_id: str
    # None when generation failed — r_script_provenance.reason then explains why.
    analysis_proposal: dict[str, Any] | None = None
    r_script_provenance: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# POST /api/run (§3.3)
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    """Request body for ``POST /api/run``."""

    r_script: str
    persist_workspace: bool = False


class RunResponse(BaseModel):
    """Runtime execution result; ``error_detail`` is set on any failure (§5)."""

    execution_id: str
    execution_result: dict[str, Any] = Field(default_factory=dict)
    statistical_results: dict[str, Any] | None = None
    statistical_results_reason: str | None = None
    generated_files: list[str] = Field(default_factory=list)
    workspace_summary: dict[str, Any] | None = None
    # Always populated on failure so the frontend never fails silently (§5).
    error_detail: str | None = None


# ---------------------------------------------------------------------------
# POST /api/visualize (§3.4)
# ---------------------------------------------------------------------------


class VisualizeRequest(BaseModel):
    """Request body for ``POST /api/visualize``."""

    statistical_results: dict[str, Any] = Field(default_factory=dict)
    intent_object: dict[str, Any] = Field(default_factory=dict)


class Figure(BaseModel):
    """A single generated figure (title + workspace path)."""

    title: str
    path: str | None = None


class VisualizeResponse(BaseModel):
    """Figures produced by the Visualization agent."""

    execution_id: str
    figures: list[Figure] = Field(default_factory=list)
    error_detail: str | None = None


# ---------------------------------------------------------------------------
# POST /api/report (§3.5)
# ---------------------------------------------------------------------------


class ReportRequest(BaseModel):
    """Request body for ``POST /api/report``."""

    statistical_results: dict[str, Any] = Field(default_factory=dict)
    intent_object: dict[str, Any] = Field(default_factory=dict)
    reporting_checklist_id: str | None = None
    target_journal_style: str = "APA"
    reporting_skill_id: str | None = None


class ManuscriptSection(BaseModel):
    """One drafted manuscript section."""

    section_id: str
    text: str
    is_ai_generated: bool = False


class ReportResponse(BaseModel):
    """Manuscript sections produced by the Reporting agent."""

    execution_id: str
    manuscript_sections: list[ManuscriptSection] = Field(default_factory=list)
    error_detail: str | None = None


# ---------------------------------------------------------------------------
# GET /api/files (§3.6, §3.7)
# ---------------------------------------------------------------------------


class FileEntry(BaseModel):
    """One workspace file listing entry."""

    path: str
    size_bytes: int
    modified: str
    kind: str


class FilesResponse(BaseModel):
    """Read-only workspace file listing."""

    files: list[FileEntry] = Field(default_factory=list)


class FileContentResponse(BaseModel):
    """Text file content + detected language (image files return bytes)."""

    text: str
    language: str


# ---------------------------------------------------------------------------
# Knowledge (§3.8)
# ---------------------------------------------------------------------------


class KnowledgeIngestResponse(BaseModel):
    """Result of a KIP ingestion — a pending draft awaiting human approval."""

    draft_id: str
    extracted: dict[str, Any] = Field(default_factory=dict)
    extraction_limitations: list[str] = Field(default_factory=list)


class KnowledgeApproveRequest(BaseModel):
    """Human approval of a pending draft into institutional/ (ADR-0003)."""

    draft_id: str
    domain: str
    trust_level: str
    corrections: dict[str, Any] = Field(default_factory=dict)


class KnowledgeApproveResponse(BaseModel):
    """Registered institutional entry id (reindex is Phase 5)."""

    entry_id: str
    indexed_docs: int | None = None
    chunks: int | None = None


class KnowledgeRejectRequest(BaseModel):
    """Rejection of a pending draft."""

    draft_id: str
    reason: str


class KnowledgeRejectResponse(BaseModel):
    """Confirmation that a pending draft was rejected."""

    draft_id: str
    status: str = "rejected"


class KnowledgeListResponse(BaseModel):
    """Registered institutional knowledge entries (REGISTRY.yaml)."""

    entries: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# WebSocket /ws/console (§4.1)
# ---------------------------------------------------------------------------


class ConsoleMessage(BaseModel):
    """One console frame streamed over ``/ws/console`` (stdout/stderr/exit)."""

    type: str  # "stdout" | "stderr" | "exit"
    text: str = ""
    exit_code: int | None = None
