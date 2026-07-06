"""POST /api/propose — conversational code proposal via StatisticsAgent (§3.2)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from cie.api.deps import (
    get_dataset_context,
    get_services,
    invoke_agent,
    new_execution_id,
)
from cie.api.models import ProposeRequest, ProposeResponse
from cie.security.capability_token import CapabilityScope

router = APIRouter(prefix="/api", tags=["propose"])


@router.post("/propose", response_model=ProposeResponse)
async def propose(request: Request, body: ProposeRequest) -> ProposeResponse:
    """Return an analysis_proposal (candidates + explanation) or a follow-up.

    Critical (§3.2): when no proposal can be generated, ``analysis_proposal`` is
    ``None`` but ``r_script_provenance.reason`` is ALWAYS present — the frontend
    shows it, so a generation failure is never silent.
    """
    services = get_services(request)
    execution_id = new_execution_id()
    col_meta = get_dataset_context(request).get("dataset_structural_metadata", {})

    payload: dict = {
        "data_quality_report": {"quality_gate_passed": True},
        "intent_object": body.intent_object or {},
        "dataset_structural_metadata": col_meta,
        "inject_raw_data_rows": False,
    }
    if body.continuation_query:
        payload["continuation_query"] = body.continuation_query
        payload["prior_statistical_results"] = body.prior_statistical_results
        payload["prior_r_script"] = body.prior_r_script
    else:
        payload["conversational_mode"] = True

    output = await invoke_agent(
        services,
        agent_key="statistics",
        agent_id="statistics",
        step_id="api_propose",
        scopes=[
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.R_CODE_GENERATE_TEMPLATE,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ],
        payload=payload,
        # task-context is the permissive dispatch schema the continuation
        # "原型" (_start_continuation_analysis, app.py:565) validates against.
        # analysis-request is the strict *intent_object* output schema and does
        # not match the Statistics *input* payload (it requires objective/
        # outcome_type/… at top level and forbids conversational_mode etc.).
        input_schema_ref="cie://schemas/task-context.schema.json",
        execution_id=execution_id,
    )

    if output.status != "success":
        # Never silent: carry the failure reason in provenance (§3.2, §5).
        return ProposeResponse(
            execution_id=execution_id,
            analysis_proposal=None,
            r_script_provenance={
                "llm_generated": False,
                "from_cache": False,
                "knowledge_references": [],
                "reason": output.error_message or "statistics_agent_failed",
            },
        )

    op = output.output_payload
    provenance = op.get("r_script_provenance") or {}
    proposal = op.get("analysis_proposal")
    if proposal is None and not op.get("r_script"):
        # Generation produced nothing — guarantee a reason is present.
        provenance.setdefault("reason", "no_proposal_generated")
    elif proposal is None and op.get("r_script"):
        # Continuation turn: single script, expose it as a one-candidate proposal.
        proposal = {
            "explanation_markdown": "",
            "code_candidates": [
                {
                    "candidate_id": "continuation",
                    "label": "この追加解析を実行",
                    "r_code": op["r_script"],
                }
            ],
            "recommended_candidate_id": "continuation",
        }

    return ProposeResponse(
        execution_id=execution_id,
        analysis_proposal=proposal,
        r_script_provenance=provenance,
    )
