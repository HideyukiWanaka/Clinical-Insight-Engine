"""POST /api/intent — research-intent analysis via PlannerAgent (§3.1)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from cie.api.deps import (
    get_dataset_context,
    get_services,
    invoke_agent,
    new_execution_id,
)
from cie.api.intent_display import resolve_intent_display
from cie.api.models import IntentRequest, IntentResponse
from cie.security.capability_token import CapabilityScope

router = APIRouter(prefix="/api", tags=["intent"])


@router.post("/intent", response_model=IntentResponse)
async def analyze_intent(request: Request, body: IntentRequest) -> IntentResponse:
    """Convert a natural-language prompt into an intent_object (ADR-0001).

    The Planner never selects a workflow (no ``workflow_id`` in the output).
    """
    services = get_services(request)
    execution_id = new_execution_id()
    dataset_context = get_dataset_context(request)
    col_meta = dataset_context.get("dataset_structural_metadata", {})
    alias_map = dataset_context.get("var_n_alias_map", {})
    masked_vars = set(dataset_context.get("pii_masked_vars", []))

    output = await invoke_agent(
        services,
        agent_key="planner",
        agent_id="planner",
        step_id="api_intent",
        scopes=[
            CapabilityScope.DATASET_PROXY_METADATA,
            CapabilityScope.WORKFLOW_STATE_READ,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ],
        payload={
            "user_natural_language_prompt": body.prompt,
            "dataset_structural_metadata": col_meta,
            "conversation_history": [
                {"role": t.role, "text": t.text} for t in body.conversation_history
            ],
            "inject_raw_data_rows": False,
        },
        input_schema_ref="cie://schemas/planner-input.schema.json",
        execution_id=execution_id,
    )

    if output.status not in ("success", "clarification_required"):
        # Agent internal failure — §5 5xx, reason surfaced in detail.
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": output.error_code or "PLANNER_FAILED",
                "message": "Intent analysis failed.",
                "detail": output.error_message,
            },
        )

    op = output.output_payload
    intent_object = op.get("intent_object", {}) or {}
    clarification_options = op.get("clarification_options") or []
    # Un-mask var_n aliases in user-facing prose so the chat never shows raw
    # internal identifiers like "var_4" (Fix C).
    resolve_intent_display(
        intent_object, clarification_options, alias_map, masked_vars
    )
    return IntentResponse(
        execution_id=execution_id,
        intent_object=intent_object,
        confidence_score=float(op.get("confidence_score") or 0.0),
        requires_human_clarification=bool(
            op.get("requires_human_clarification", False)
        ),
        clarification_options=clarification_options,
    )
