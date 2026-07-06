"""POST /api/report — manuscript generation via ReportingAgent (§3.5)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from cie.api.deps import get_services, invoke_agent, new_execution_id
from cie.api.models import ManuscriptSection, ReportRequest, ReportResponse
from cie.security.capability_token import CapabilityScope

router = APIRouter(prefix="/api", tags=["report"])


@router.post("/report", response_model=ReportResponse)
async def report(request: Request, body: ReportRequest) -> ReportResponse:
    """Draft manuscript sections from statistical results + intent."""
    services = get_services(request)
    execution_id = new_execution_id()

    output = await invoke_agent(
        services,
        agent_key="reporting",
        agent_id="reporting",
        step_id="api_report",
        scopes=[
            CapabilityScope.REPORT_COMPILE_MANUSCRIPT,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ],
        payload={
            "statistical_results": body.statistical_results,
            "intent_object": body.intent_object,
            "reporting_checklist_id": body.reporting_checklist_id,
            "target_journal_style": body.target_journal_style,
            "reporting_skill_id": body.reporting_skill_id,
            "inject_raw_data_rows": False,
        },
        input_schema_ref="cie://schemas/task-context.schema.json",
        execution_id=execution_id,
    )

    if output.status != "success":
        return ReportResponse(
            execution_id=execution_id,
            manuscript_sections=[],
            error_detail=output.error_message or "Manuscript generation failed.",
        )

    sections = output.output_payload.get("manuscript_sections") or []
    manuscript_sections = [
        ManuscriptSection(
            section_id=s.get("section_id", str(i)),
            text=s.get("content", ""),
            is_ai_generated=bool(s.get("llm_generated", False)),
        )
        for i, s in enumerate(sections)
        if isinstance(s, dict)
    ]
    return ReportResponse(
        execution_id=execution_id,
        manuscript_sections=manuscript_sections,
    )
