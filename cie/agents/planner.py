"""CIE Platform — Planner Agent: natural language → IntentObject.

Translates a user's research prompt and dataset structural metadata into a
validated IntentObject conforming to analysis-request.schema.json.

Behavioral rules PL-001 through PL-006 from agents/planner.yaml are embedded
in the LLM system prompt.  The key architectural constraint from ADR-0001:

    workflow_id is NEVER produced by this agent.
    The Orchestrator selects the workflow via deterministic rules (WS-001–WS-004).
    Any workflow_id that leaks from an LLM response is stripped before output.

Scope requirements (spec/permissions.yaml):
    - dataset.proxy_metadata   — read column names / types only (no raw rows)
    - workflow.state_read      — inspect current workflow state
    - audit.write_entry        — record execution in audit log
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Literal

import httpx

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.exceptions import AgentError
from cie.schemas.validator import SchemaRegistry
from cie.security.capability_token import CapabilityScope
from cie.security.context_guard import ContextGuard
from cie.security.policy_engine import PolicyEngine
from cie.core.audit import AuditService

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured clarification options (planner.yaml exception_handling)
# ---------------------------------------------------------------------------

_PAIRED_AMBIGUITY_OPTIONS: list[dict] = [
    {
        "option_id": "independent",
        "label": "Independent groups — different subjects in each group/time point",
        "intent_override": {"paired": False, "subject_id_var": None},
    },
    {
        "option_id": "paired",
        "label": "Paired/repeated-measures — same subjects measured at each time point",
        "intent_override": {"paired": True},
    },
]

_SUBJECT_ID_OPTION: dict = {
    "option_id": "specify_subject_id",
    "label": (
        "A paired design was detected but no subject identifier column could be "
        "found in the dataset metadata. Please specify which column identifies each "
        "subject (patient ID, participant number, etc.)."
    ),
    "intent_override": {"paired": True},
}

# ---------------------------------------------------------------------------
# IntentObject schema excerpt — embedded in system prompt so the LLM can
# produce schema-conforming output without additional context.
# ---------------------------------------------------------------------------

_INTENT_OBJECT_SCHEMA_EXCERPT: dict = {
    "required": ["objective", "outcome_type", "study_design"],
    "properties": {
        "objective": {
            "enum": [
                "between_group_comparison", "paired_comparison",
                "correlation_analysis", "regression_analysis",
                "survival_analysis", "diagnostic_accuracy",
                "prediction_model", "descriptive_only", "systematic_review",
            ]
        },
        "outcome_type": {
            "enum": [
                "continuous", "categorical_binary", "categorical_ordinal",
                "categorical_nominal", "survival", "unknown",
            ]
        },
        "predictor_type": {
            "enum": [
                "categorical_binary", "categorical_nominal",
                "categorical_ordinal", "continuous", "mixed", None,
            ]
        },
        "study_design": {
            "enum": [
                "randomized_controlled_trial", "observational", "cohort",
                "case_control", "cross_sectional", "prediction_model",
                "systematic_review_or_meta_analysis",
                "diagnostic_accuracy_study", "unknown",
            ]
        },
        "distribution_assumptions": {
            "enum": ["assumed_normal", "assumed_non_normal", "unknown"]
        },
        "reporting_checklist_inference": {
            "enum": ["CONSORT", "STROBE", "TRIPOD", "PRISMA", "STARD", None]
        },
        "natural_language_summary": {"type": "string"},
        "sample_size_estimate": {"type": ["integer", "null"]},
        "outcome_variables": {
            "description": "List of {var_n, role} dicts for outcome columns",
            "items": {
                "role_enum": [
                    "primary_outcome", "secondary_outcome",
                    "time_to_event", "event_indicator",
                ]
            },
        },
        "predictor_variables": {
            "description": "List of {var_n, role} dicts for predictor/grouping columns",
            "items": {
                "role_enum": [
                    "primary_predictor", "covariate",
                    "grouping_variable", "matching_variable",
                ]
            },
        },
    },
}

# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are a clinical research intent extraction agent for the CIE Platform.
Your ONLY task: translate the user's research prompt + dataset metadata into a
structured JSON payload. Never produce conversational text, markdown, or commentary.

=== BEHAVIORAL RULES ===

PL-001 [CRITICAL]: Respond with a single, valid JSON object only. No prose. No code blocks.

PL-002 [HIGH]: Map language strictly to formal clinical epidemiology concepts.
  Examples:
    "compare blood pressure between Group A and Group B"
      → objective="between_group_comparison", outcome_type="continuous",
        predictor_type="categorical_binary", paired=false
    "relationship between age and survival time"
      → objective="survival_analysis", outcome_type="survival"
  Always populate: objective, outcome_type, study_design in intent_object.
  Always populate at response top-level: paired (true/false/null),
    subject_id_var (var_N string or null), n_groups_estimate (int or null).

PL-003 [HIGH]: If the research objective is ambiguous, set
  requires_human_clarification=true and provide mutually exclusive
  clarification_options with option_id, label, and intent_override.

PL-004 [HIGH]: Infer paired from language signals.
  paired=true:  "before and after", "pre/post", "baseline and follow-up",
                "治療前後", "介入前後", "same subjects", "同一患者", "クロスオーバー",
                "repeated measures", "within-subject"
  paired=false: clearly distinct populations ("Group A vs B", "exposed vs unexposed")
  paired=null:  temporal language present but unclear if same subjects
                Example: "compare outcomes at 3 months and 6 months" (ambiguous cohort)

PL-005 [HIGH]: When paired=true, inspect dataset_structural_metadata for a
  subject identifier column (inferred_type != continuous, unique_count ~ n_subjects).
  If not found, set subject_id_var=null and requires_human_clarification=true.
  NEVER output paired=true with subject_id_var=null without flagging clarification.

PL-006 [MEDIUM]: Infer n_groups_estimate from explicit counts in the prompt
  ("three groups", "baseline + 3 months + 6 months" → 3) or from metadata
  unique_count of the grouping variable. Set null if undeterminable.

ADR-0001 [CRITICAL]: DO NOT include "workflow_id" anywhere in your response.
  The Orchestrator selects workflows. The Planner never assigns workflow_id.

=== REQUIRED OUTPUT FORMAT ===

Return exactly this JSON structure (no additional keys at top level):

{{
  "intent_object": {{
    "objective": "<see enum below>",
    "outcome_type": "<see enum below>",
    "predictor_type": "<see enum below, or null>",
    "study_design": "<see enum below>",
    "distribution_assumptions": "assumed_normal | assumed_non_normal | unknown",
    "reporting_checklist_inference": "CONSORT | STROBE | TRIPOD | PRISMA | STARD | null",
    "natural_language_summary": "<one sentence>",
    "sample_size_estimate": <int or null>,
    "outcome_variables": [{{"var_n": "var_N", "role": "primary_outcome | secondary_outcome | time_to_event | event_indicator"}}],
    "predictor_variables": [{{"var_n": "var_N", "role": "primary_predictor | covariate | grouping_variable | matching_variable"}}]
  }},
  "paired": true | false | null,
  "subject_id_var": "var_N or null",
  "n_groups_estimate": <int or null>,
  "confidence_score": <float 0.0–1.0>,
  "requires_human_clarification": true | false,
  "clarification_options": []
}}

=== IntentObject Schema Reference ===

{intent_object_schema}
"""


# ---------------------------------------------------------------------------
# PlannerAgent
# ---------------------------------------------------------------------------


class PlannerAgent(BaseAgent):
    """Translates natural language research prompts into validated IntentObjects.

    Args:
        policy_engine: Enforces capability scope checks.
        schema_registry: Validates input and output payloads against schemas.
        audit_service: Records execution outcomes.
        context_guard: PII check + inject_raw_data_rows structural enforcement.
        llm_client: Async HTTP client for LLM API calls (httpx.AsyncClient).
        llm_model: Claude model identifier.  Defaults to claude-haiku-4-5-20251001.
    """

    _LLM_MODEL: str = "claude-haiku-4-5-20251001"
    _LLM_API_URL: str = "https://api.anthropic.com/v1/messages"
    _LLM_MAX_TOKENS: int = 1024
    _API_TIMEOUT_SECONDS: float = 30.0

    def __init__(
        self,
        policy_engine: PolicyEngine,
        schema_registry: SchemaRegistry,
        audit_service: AuditService,
        context_guard: ContextGuard,
        llm_client: httpx.AsyncClient,
        llm_model: str | None = None,
    ) -> None:
        super().__init__(policy_engine, schema_registry, audit_service)
        self._context_guard = context_guard
        self._llm_client = llm_client
        self._llm_model = llm_model or self._LLM_MODEL

    # ------------------------------------------------------------------
    # Abstract property implementations
    # ------------------------------------------------------------------

    @property
    def agent_id(self) -> str:
        return "planner"

    @property
    def input_schema_ref(self) -> str:
        return "cie://schemas/task.schema.json"

    @property
    def output_schema_ref(self) -> str:
        return "cie://schemas/analysis-request.schema.json"

    @property
    def required_scopes(self) -> list[CapabilityScope]:
        return [
            CapabilityScope.DATASET_PROXY_METADATA,
            CapabilityScope.WORKFLOW_STATE_READ,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ]

    # ------------------------------------------------------------------
    # Core execution (step 3 of BaseAgent.run template)
    # ------------------------------------------------------------------

    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        """Extract an IntentObject from the natural language prompt.

        Steps:
          1. PII scan + raw-data-rows guard via ContextGuard.
          2. Build system prompt (PL-001–006) and user message.
          3. Call LLM and receive intermediate response dict.
          4. Apply PL-004 (paired=null) and PL-005 (subject_id missing) rules.
          5. Build schema-conforming output_payload (workflow_id stripped).
          6. Return AgentOutput.
        """
        payload = agent_input.payload

        # Step 1 — PII check; also raises SecurityViolationError on raw_data_rows
        # (context_guard.sanitize_context_payload enforces inject_raw_data_rows=False)
        await self._context_guard.sanitize_context_payload(
            payload,
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
        )

        user_prompt: str = payload["user_natural_language_prompt"]
        dataset_metadata: dict = payload.get("dataset_structural_metadata", {})

        # Step 2 — build LLM request
        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(user_prompt, dataset_metadata)

        # Step 3 — LLM call (raises AgentError on failure)
        llm_response = await self._call_llm(system_prompt, user_message)

        # Step 4 — apply PL-004 / PL-005 clarification rules
        paired = llm_response.get("paired")
        subject_id_var = llm_response.get("subject_id_var")

        requires_clarification: bool = bool(
            llm_response.get("requires_human_clarification", False)
        )
        clarification_options: list[dict] = list(
            llm_response.get("clarification_options") or []
        )

        # PL-004: paired=null signals temporal ambiguity → clarification required
        if paired is None and not requires_clarification:
            requires_clarification = True
            if not clarification_options:
                clarification_options = list(_PAIRED_AMBIGUITY_OPTIONS)

        # PL-005: paired=true without a resolved subject_id_var → must clarify
        if paired is True and subject_id_var is None:
            requires_clarification = True
            if not any(
                o.get("option_id") == "specify_subject_id"
                for o in clarification_options
            ):
                clarification_options = [_SUBJECT_ID_OPTION]

        # Step 5 — build schema-conforming output_payload
        intent_obj: dict = dict(llm_response.get("intent_object") or {})
        # Hard guard: workflow_id must never appear in output (ADR-0001)
        intent_obj.pop("workflow_id", None)

        output_payload: dict = {
            "execution_id": agent_input.execution_id,
            "intent_object": intent_obj,
            "confidence_score": float(llm_response.get("confidence_score") or 0.5),
            "requires_human_clarification": requires_clarification,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if clarification_options:
            output_payload["clarification_options"] = clarification_options

        # Secondary guard: strip workflow_id if it appears at the top level
        output_payload.pop("workflow_id", None)

        # Step 6 — return AgentOutput
        status: Literal["success", "failed", "clarification_required"] = (
            "clarification_required" if requires_clarification else "success"
        )
        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status=status,
            output_payload=output_payload,
            output_schema_ref=self.output_schema_ref,
            requires_human_clarification=requires_clarification,
            clarification_options=clarification_options,
        )

    # ------------------------------------------------------------------
    # LLM interface (httpx — no requests library)
    # ------------------------------------------------------------------

    async def _call_llm(self, system_prompt: str, user_message: str) -> dict:
        """POST a message to the Anthropic Messages API and parse the response.

        Args:
            system_prompt: Rules and schema context for the LLM.
            user_message:  JSON-encoded research prompt + dataset metadata.

        Returns:
            The parsed JSON dict from the LLM's first text block.

        Raises:
            AgentError: On any HTTP, parse, or structural failure.
        """
        try:
            response = await self._llm_client.post(
                self._LLM_API_URL,
                json={
                    "model": self._llm_model,
                    "max_tokens": self._LLM_MAX_TOKENS,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_message}],
                },
                headers={
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                timeout=self._API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()
            raw_text: str = data["content"][0]["text"]
            return json.loads(raw_text)
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError(
                f"INTENT_EXTRACTION_FAILED: {exc}",
                agent_id=self.agent_id,
            ) from exc

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Assemble the system prompt embedding PL-001 through PL-006 rules.

        The IntentObject schema excerpt is embedded so the LLM can produce
        schema-conforming output without requiring additional tool calls.
        """
        schema_text = json.dumps(
            _INTENT_OBJECT_SCHEMA_EXCERPT,
            indent=2,
            ensure_ascii=False,
        )
        return _SYSTEM_PROMPT_TEMPLATE.format(intent_object_schema=schema_text)

    def _build_user_message(self, user_prompt: str, dataset_metadata: dict) -> str:
        """Serialize the user prompt and metadata for LLM consumption.

        Only var_n aliases are present in dataset_metadata — original column
        names are never sent to the LLM (privacy by design / PL-002).
        The inject_raw_data_rows field is set to False as a structural signal.

        Args:
            user_prompt: Natural language research objective.
            dataset_metadata: Structural metadata using var_n column aliases only.

        Returns:
            JSON string sent as the user message turn.
        """
        return json.dumps(
            {
                "user_natural_language_prompt": user_prompt,
                "dataset_structural_metadata": dataset_metadata,
                "inject_raw_data_rows": False,
            },
            ensure_ascii=False,
            indent=2,
        )
