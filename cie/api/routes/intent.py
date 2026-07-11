"""POST /api/intent — research-intent analysis via PlannerAgent (§3.1)."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request

from cie.api.deps import (
    get_dataset_context,
    get_services,
    invoke_agent,
    new_execution_id,
)
from cie.api.models import IntentRequest, IntentResponse
from cie.security.capability_token import CapabilityScope

router = APIRouter(prefix="/api", tags=["intent"])

_VAR_TOKEN_RE = re.compile(r"\bvar_\d+\b")
_MASKED_LABEL = "（匿名化された列）"


def _unmask_var_tokens(
    text: str, alias_map: dict[str, str], masked_vars: set[str]
) -> str:
    """Replace ``var_N`` tokens in user-facing text with real column names.

    The Planner authors ``natural_language_summary`` and clarification labels in
    var_n alias space (it never sees real names on the intent path), so those
    aliases would otherwise leak into the chat (Fix C). We resolve them here —
    the single server-side source of truth — using ``var_n_alias_map``. A var
    whose header signalled PII is shown as an anonymised placeholder, never its
    real name.
    """
    if not text:
        return text

    def repl(match: re.Match[str]) -> str:
        var_n = match.group(0)
        if var_n in masked_vars:
            return _MASKED_LABEL
        return alias_map.get(var_n, var_n)

    return _VAR_TOKEN_RE.sub(repl, text)


def _resolve_intent_display(
    intent_object: dict,
    clarification_options: list[dict],
    alias_map: dict[str, str],
    masked_vars: set[str],
) -> None:
    """In-place: un-mask var_n tokens in the human-readable fields only.

    Structured identifiers (``outcome_variables[].var_n`` etc.) are left intact
    so the frontend keeps using them programmatically; only prose the user reads
    (``natural_language_summary`` and each option's ``label``) is resolved.
    """
    summary = intent_object.get("natural_language_summary")
    if isinstance(summary, str):
        intent_object["natural_language_summary"] = _unmask_var_tokens(
            summary, alias_map, masked_vars
        )
    for opt in clarification_options:
        label = opt.get("label")
        if isinstance(label, str):
            opt["label"] = _unmask_var_tokens(label, alias_map, masked_vars)


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
    _resolve_intent_display(
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
