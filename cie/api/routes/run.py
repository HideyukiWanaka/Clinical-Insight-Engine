"""POST /api/run — R script execution via RuntimeAgent (§3.3)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from cie.api.deps import get_services, invoke_agent, new_execution_id
from cie.api.models import RunRequest, RunResponse
from cie.security.capability_token import CapabilityScope

router = APIRouter(prefix="/api", tags=["run"])

# Runtime statuses that mean the R run did not produce results.
_FAILED_STATUSES = {"no_executable_script", "execution_failed", "nonzero_exit"}


@router.post("/run", response_model=RunResponse)
async def run_script(request: Request, body: RunRequest) -> RunResponse:
    """Execute an R script in the sandbox and return the parsed results.

    Failure is never silent (§3.3, §5): ``error_detail`` always carries
    ``execution_result.detail`` / ``statistical_results_reason`` on failure.
    """
    services = get_services(request)
    execution_id = new_execution_id()

    output = await invoke_agent(
        services,
        agent_key="runtime_agent",
        agent_id="runtime",
        step_id="api_run",
        scopes=[
            CapabilityScope.RUNTIME_INVOKE_EXECUTION,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ],
        payload={
            "r_script": body.r_script,
            "persist_workspace": body.persist_workspace,
            "inject_raw_data_rows": False,
        },
        input_schema_ref="cie://schemas/task-context.schema.json",
        execution_id=execution_id,
    )

    if output.status != "success":
        return RunResponse(
            execution_id=execution_id,
            execution_result={},
            error_detail=output.error_message or "R execution failed.",
        )

    op = output.output_payload
    execution_result: dict = op.get("execution_result") or {}
    statistical_results = op.get("statistical_results")
    stats_reason = op.get("statistical_results_reason")

    error_detail: str | None = None
    if execution_result.get("status") in _FAILED_STATUSES:
        error_detail = execution_result.get("detail") or (
            f"Rの実行が正常に終了しませんでした（exit_code={execution_result.get('exit_code')}）。"
        )
    elif statistical_results is None and stats_reason:
        error_detail = f"統計結果を読み取れませんでした（理由: {stats_reason}）。"

    return RunResponse(
        execution_id=execution_id,
        execution_result=execution_result,
        statistical_results=statistical_results,
        statistical_results_reason=stats_reason,
        generated_files=op.get("generated_files") or [],
        workspace_summary=op.get("workspace_summary"),
        error_detail=error_detail,
    )
