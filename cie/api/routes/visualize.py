"""POST /api/visualize — figure generation via VisualizationAgent (§3.4)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from cie.api.deps import (
    get_dataset_context,
    get_services,
    invoke_agent,
    new_execution_id,
)
from cie.api.models import Figure, VisualizeRequest, VisualizeResponse
from cie.security.capability_token import CapabilityScope

router = APIRouter(prefix="/api", tags=["visualize"])


@router.post("/visualize", response_model=VisualizeResponse)
async def visualize(request: Request, body: VisualizeRequest) -> VisualizeResponse:
    """Generate figures from statistical results."""
    services = get_services(request)
    execution_id = new_execution_id()
    dataset_context = get_dataset_context(request)
    col_meta = dataset_context.get("dataset_structural_metadata", {})
    var_n_alias_map = dataset_context.get("var_n_alias_map", {})

    output = await invoke_agent(
        services,
        agent_key="visualization",
        agent_id="visualization",
        step_id="api_visualize",
        scopes=[
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.R_CODE_GENERATE_TEMPLATE,
            CapabilityScope.RUNTIME_INVOKE_EXECUTION,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ],
        payload={
            "statistical_results": body.statistical_results,
            "intent_object": body.intent_object,
            "dataset_structural_metadata": col_meta,
            "var_n_alias_map": var_n_alias_map,
            "inject_raw_data_rows": False,
        },
        input_schema_ref="cie://schemas/task-context.schema.json",
        execution_id=execution_id,
    )

    if output.status != "success":
        return VisualizeResponse(
            execution_id=execution_id,
            figures=[],
            error_detail=output.error_message or "Figure generation failed.",
        )

    manifest = output.output_payload.get("figure_manifest") or []
    figures = [
        Figure(title=f.get("figure_id", "Figure"), path=f.get("actual_path"))
        for f in manifest
        if isinstance(f, dict)
    ]
    return VisualizeResponse(execution_id=execution_id, figures=figures)
