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

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.cache.models import CacheEntry, CacheKey
from cie.cache.store import CacheStore
from cie.core.audit import AuditEvent, AuditEventSeverity
from cie.core.exceptions import AgentError
from cie.core.llm_client import LLMClient, LLMError
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


def _name_matches_prompt(name: str, prompt: str) -> bool:
    """Heuristic: does a column ``name`` plausibly appear in the user ``prompt``?

    Used only by the empty-outcome fallback (:meth:`_infer_outcome_variables`)
    as a safety net when the LLM returns no outcome_variables. Strips unit/format
    suffixes (``収縮期血圧_mmHg`` → ``収縮期血圧``) and looks for a shared run of
    ≥2 characters between the column name and the prompt — enough to match
    ``血圧`` in ``男女の血圧を比較したい`` while rejecting an unrelated ``検査年``.
    Intentionally conservative: ambiguity (0 or many matches) defers to a human.
    """
    if not name or not prompt:
        return False
    # Drop a trailing unit/format segment after the last underscore (mmHg, mg_dl…).
    core = name.split("_", 1)[0].strip().lower()
    p = prompt.lower()
    if len(core) >= 2 and core in p:
        return True
    # Fall back to any shared contiguous run of ≥2 chars (handles CJK without
    # word boundaries, e.g. 収縮期血圧 sharing 血圧 with the prompt).
    for i in range(len(core) - 1):
        for j in range(i + 2, len(core) + 1):
            if core[i:j] in p:
                return True
    return False

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

=== JSON OUTPUT REQUIREMENTS ===
- Respond with ONLY valid JSON (RFC 8259 compliant).
- Escape all special characters in string values: quotes (") as \", newlines as \n, backslashes as \\.
- Use double quotes only (no single quotes).
- Ensure all string values are properly closed with quotes.

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

PL-007 [CRITICAL]: Map the user's words to columns using the metadata "name".
  dataset_structural_metadata is keyed by var_n alias; each entry has
  "inferred_type", "unique_count", and usually "name" (the real header).
  Select outcome_variables / predictor_variables by matching the user's
  request to the column "name", then emit that column's var_n.
    Example: user says "compare blood pressure between men and women" and the
    metadata contains var_10 with name "収縮期血圧_mmHg" (continuous) and var_6
    with name "性別" (categorical_binary) → set outcome_variables to var_10
    (role primary_outcome) and predictor_variables to var_6 (role
    grouping_variable).
  NEVER pick a column merely because it is the first of a matching type — a
  year/ID/date column ("検査年", "exam year") is NOT the outcome for a "blood
  pressure" request. If NO column "name" plausibly matches the requested
  outcome, do NOT guess: set requires_human_clarification=true and offer the
  candidate columns (by name) as clarification_options. Some columns have no
  "name" (privacy-masked identifiers) — never select those as the outcome.

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
        llm_client: Provider-agnostic LLM client (``LLMClient``).
        cache_store: Semantic cache (ADR-0004). ``None`` disables caching.
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        schema_registry: SchemaRegistry,
        audit_service: AuditService,
        context_guard: ContextGuard,
        llm_client: LLMClient,
        cache_store: CacheStore | None = None,
    ) -> None:
        super().__init__(policy_engine, schema_registry, audit_service)
        self._context_guard = context_guard
        self._llm_client = llm_client
        self._cache_store = cache_store

    # ------------------------------------------------------------------
    # Abstract property implementations
    # ------------------------------------------------------------------

    @property
    def agent_id(self) -> str:
        return "planner"

    @property
    def input_schema_ref(self) -> str:
        return "cie://schemas/planner-input.schema.json"

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
        conversation_history: list = payload.get("conversation_history") or []

        # Step 1.5 — semantic cache lookup (ADR-0004; keyed per model, CA-005).
        # Skip the cache entirely when prior turns are present: the same prompt
        # ("血圧です") means different things depending on what it corrects, so a
        # prompt-keyed cache entry would be wrong here.
        cache_key: CacheKey | None = None
        if self._cache_store is not None and not conversation_history:
            cache_key = self._cache_store.make_key(user_prompt, dataset_metadata)
            cached = self._cache_store.get(
                cache_key,
                llm_provider=self._llm_client.provider,
                llm_model=self._llm_client.model,
            )
            if cached is not None and not cached.intent_object.get("outcome_variables"):
                # Stale entry cached before schema validation ran (empty
                # outcome_variables violates minItems=1). Drop it and fall
                # through to a fresh LLM call.
                _log.warning(
                    "Discarding cached intent with empty outcome_variables "
                    "(pre-validation poisoned entry)"
                )
                self._cache_store.delete_by_key(
                    cache_key,
                    llm_provider=self._llm_client.provider,
                    llm_model=self._llm_client.model,
                )
                cached = None
            if cached is not None:
                self._cache_store.record_hit(
                    cache_key,
                    llm_provider=self._llm_client.provider,
                    llm_model=self._llm_client.model,
                )
                await self._write_cache_hit_audit(agent_input, cache_key)
                return self._build_output_from_cache(agent_input, cached)

        # Step 2 — build LLM request
        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(
            user_prompt, dataset_metadata, conversation_history
        )

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

        # outcome_variables requires minItems=1 per schema. If LLM returned
        # empty or missing, infer from dataset metadata as a fallback — but only
        # commit silently when the inference is confident. An ambiguous guess
        # (no clear name match / multiple candidates) must ask the human rather
        # than picking an arbitrary column (which used to select 検査年).
        if not intent_obj.get("outcome_variables"):
            inferred_outcomes, confident = self._infer_outcome_variables(
                intent_obj, dataset_metadata, user_prompt
            )
            intent_obj["outcome_variables"] = inferred_outcomes
            if not confident:
                requires_clarification = True
                if not any(
                    str(o.get("option_id", "")).startswith("outcome:")
                    for o in clarification_options
                ):
                    clarification_options.extend(
                        self._build_outcome_clarification_options(dataset_metadata)
                    )

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

        # Step 5.5 — cache write on LLM success (CA-002 / CA-003 via should_cache)
        if self._cache_store is not None and cache_key is not None:
            confidence_score = float(output_payload["confidence_score"])
            if self._cache_store.should_cache(confidence_score, requires_clarification):
                self._cache_store.put(
                    key=cache_key,
                    original_prompt=user_prompt,
                    intent_object=intent_obj,
                    confidence_score=confidence_score,
                    llm_provider=self._llm_client.provider,
                    llm_model=self._llm_client.model,
                )

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
    # Semantic cache (ADR-0004)
    # ------------------------------------------------------------------

    async def _write_cache_hit_audit(
        self, agent_input: AgentInput, cache_key: CacheKey
    ) -> None:
        """CA-001: cache-served analyses keep a full audit trail."""
        await self._audit_service.write(AuditEvent(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            action="CACHE_HIT",
            status="success",
            severity=AuditEventSeverity.INFO,
            payload={
                "normalized_prompt": cache_key.normalized_prompt,
                "dataset_fingerprint": cache_key.dataset_fingerprint,
            },
        ))

    def _build_output_from_cache(
        self, agent_input: AgentInput, cached: CacheEntry
    ) -> AgentOutput:
        """Reconstruct an AgentOutput from a cache entry without calling the LLM.

        Cached entries never require clarification (CA-003), so status is
        always "success".
        """
        output_payload: dict = {
            "execution_id": agent_input.execution_id,
            "intent_object": dict(cached.intent_object),
            "confidence_score": cached.confidence_score,
            "requires_human_clarification": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        output_payload["intent_object"].pop("workflow_id", None)  # ADR-0001 guard
        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status="success",
            output_payload=output_payload,
            output_schema_ref=self.output_schema_ref,
            requires_human_clarification=False,
            clarification_options=[],
        )

    # ------------------------------------------------------------------
    # LLM interface
    # ------------------------------------------------------------------

    async def _call_llm(self, system_prompt: str, user_message: str) -> dict:
        """Call the LLM via LLMClient and parse the JSON response.

        Args:
            system_prompt: Rules and schema context for the LLM.
            user_message:  JSON-encoded research prompt + dataset metadata.

        Returns:
            The parsed JSON dict from the LLM's text response.

        Raises:
            AgentError: On any LLM, parse, or structural failure.
        """
        try:
            raw_text = await self._llm_client.complete(system_prompt, user_message)
            _log.debug(f"LLM raw response (first 500 chars): {raw_text[:500]}")
            json_text = self._extract_json_from_response(raw_text)
            _log.debug(f"Extracted JSON (first 500 chars): {json_text[:500]}")
            return json.loads(json_text)
        except LLMError as exc:
            raise AgentError(
                f"INTENT_EXTRACTION_FAILED: {exc}",
                agent_id=self.agent_id,
            ) from exc
        except json.JSONDecodeError as exc:
            # Log the problematic text around the error location
            lines = json_text.split('\n')
            if exc.lineno <= len(lines):
                problem_line = lines[exc.lineno - 1]
                context = problem_line[max(0, exc.colno-20):min(len(problem_line), exc.colno+20)]
                _log.error(f"JSON parse error context: ...{context}...")
            _log.error(f"Full extracted JSON:\n{json_text}")

            # Try to detect and fix truncated JSON
            fixed_json = self._attempt_fix_truncated_json(json_text)
            if fixed_json and fixed_json != json_text:
                _log.info("Attempting to parse with fixed JSON...")
                try:
                    return json.loads(fixed_json)
                except json.JSONDecodeError:
                    pass

            raise AgentError(
                f"INTENT_EXTRACTION_FAILED: Invalid JSON at line {exc.lineno} column {exc.colno}: {exc.msg}",
                agent_id=self.agent_id,
            ) from exc
        except Exception as exc:
            _log.error(f"Unexpected error in _call_llm: {exc}", exc_info=True)
            raise AgentError(
                f"INTENT_EXTRACTION_FAILED: {exc}",
                agent_id=self.agent_id,
            ) from exc

    def _extract_json_from_response(self, raw_text: str) -> str:
        """Extract valid JSON from LLM response, handling markdown code blocks.

        If the response contains a ```json ... ``` code block, extract it.
        Otherwise, return the text as-is for parsing.
        """
        import re
        # Try more flexible markdown extraction patterns
        patterns = [
            r'```json\s*\n(.*?)\n```',  # ```json\n{...}\n```
            r'```(?:json)?\s*\n(.*?)```',  # ```\n{...}``` (no trailing newline)
            r'```(?:json)?(.*?)```',  # ``${...}`` (minimal spacing)
        ]

        for pattern in patterns:
            match = re.search(pattern, raw_text, re.DOTALL)
            if match:
                candidate = match.group(1).strip()
                if candidate and self._validate_json_structure(candidate):
                    _log.debug(f"Extracted JSON from code block pattern: {pattern}")
                    return candidate

        # Try to find the first { and last } to extract just the JSON
        text = raw_text.strip()
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            candidate = text[start:end+1]
            if self._validate_json_structure(candidate):
                _log.debug("Extracted JSON using { } bracket matching")
                return candidate

        # Last resort: return as-is (might fail, but error will be informative)
        _log.warning(f"Could not extract valid JSON from response. Raw text: {raw_text[:200]}")
        return raw_text.strip()

    def _attempt_fix_truncated_json(self, text: str) -> str | None:
        """Attempt to fix truncated JSON by closing open structures.

        If JSON appears to be cut off mid-string or mid-structure, try to
        close it gracefully so it can at least be parsed.
        """
        # Count open/close braces and brackets
        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')

        if open_braces <= 0 and open_brackets <= 0:
            return None  # Not truncated

        # Try to close open structures
        fixed = text.rstrip()

        # Close any open strings by adding a quote if the last character suggests it
        if fixed and fixed[-1] not in ('"', '}', ']', ','):
            fixed += '"'

        # Add closing brackets
        fixed += ']' * open_brackets
        # Add closing braces
        fixed += '}' * open_braces

        _log.info(f"Attempted to fix truncated JSON (open_braces={open_braces}, open_brackets={open_brackets})")
        return fixed

    def _validate_json_structure(self, text: str) -> bool:
        """Quick validation that JSON structure looks complete."""
        # Check for balanced braces and brackets
        brace_count = text.count('{') - text.count('}')
        bracket_count = text.count('[') - text.count(']')

        if brace_count != 0 or bracket_count != 0:
            _log.warning(f"Unbalanced JSON structure: braces={brace_count}, brackets={bracket_count}")
            return False

        # Check for unclosed strings (handle escaped backslashes)
        i = 0
        quote_count = 0
        while i < len(text):
            if text[i] == '"':
                # Count preceding backslashes
                num_backslashes = 0
                j = i - 1
                while j >= 0 and text[j] == '\\':
                    num_backslashes += 1
                    j -= 1
                # Quote is only escaped if preceded by odd number of backslashes
                if num_backslashes % 2 == 0:
                    quote_count += 1
            i += 1

        if quote_count % 2 != 0:
            _log.warning(f"Odd number of unescaped quotes ({quote_count}) detected - JSON may be truncated")
            return False

        return True

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

    def _infer_outcome_variables(
        self, intent_obj: dict, dataset_metadata: dict, user_prompt: str = ""
    ) -> tuple[list[dict], bool]:
        """Fallback: infer outcome_variables from dataset metadata.

        Called when the LLM returns an empty or missing outcome_variables list,
        which would fail schema validation (minItems=1). Rather than blindly
        grabbing the first column of the matching type (which selected an
        unrelated year/ID column for a "blood pressure" request), we match the
        user's words against each candidate column's "name" and only commit
        when exactly one column matches.

        Returns:
            (outcome_variables, confident). ``confident`` is False when the
            match was ambiguous (0 or >1 candidates) — the caller then triggers
            human clarification instead of silently trusting the guess. A
            placeholder entry is still returned so schema validation
            (minItems=1) passes, but never a PII-masked (nameless) column.
        """
        outcome_type = intent_obj.get("outcome_type", "continuous")

        # Prefer continuous vars for continuous outcomes, otherwise any var.
        # Never offer a PII-masked (nameless) column as an outcome candidate.
        candidates = [
            var_n for var_n, meta in dataset_metadata.items()
            if isinstance(meta, dict) and meta.get("name") and (
                (outcome_type == "continuous" and meta.get("inferred_type") == "continuous")
                or outcome_type != "continuous"
            )
        ]

        if not candidates:
            # No named candidate of the right type — fall back to any named col.
            candidates = [
                var_n for var_n, meta in dataset_metadata.items()
                if isinstance(meta, dict) and meta.get("name")
            ]

        if not candidates:
            # Absolute fallback — schema still validates with one entry, but we
            # cannot verify it, so it is never confident.
            first = next(iter(dataset_metadata), "var_1")
            _log.warning("No named dataset variables available; using %s as placeholder", first)
            return [{"var_n": first, "role": "primary_outcome"}], False

        # Match the user's request against candidate column names.
        matched = [
            var_n for var_n in candidates
            if _name_matches_prompt(str(dataset_metadata[var_n].get("name", "")), user_prompt)
        ]
        if len(matched) == 1:
            _log.info("Inferred outcome %s by name match to prompt", matched[0])
            return [{"var_n": matched[0], "role": "primary_outcome"}], True

        # 0 or >1 name matches → ambiguous. Return a placeholder but flag it so
        # the caller asks the user which column is the outcome.
        _log.warning(
            "LLM returned empty outcome_variables and name match was ambiguous "
            "(%d candidates matched); flagging for clarification",
            len(matched),
        )
        placeholder = matched[0] if matched else candidates[0]
        return [{"var_n": placeholder, "role": "primary_outcome"}], False

    def _build_outcome_clarification_options(self, dataset_metadata: dict) -> list[dict]:
        """One clickable clarification option per named continuous column.

        Presented when the outcome could not be resolved confidently. Each
        option's ``intent_override`` pins ``outcome_variables`` to the chosen
        column so the UI can apply the user's pick directly (Fix B). Only
        columns that carry a real ``name`` (non-PII) are offered; the label uses
        that name so the user recognises the column, never the var_n alias.
        """
        options: list[dict] = []
        for var_n, meta in dataset_metadata.items():
            if not isinstance(meta, dict) or not meta.get("name"):
                continue
            if meta.get("inferred_type") != "continuous":
                continue
            name = str(meta["name"])
            options.append({
                "option_id": f"outcome:{var_n}",
                "label": f"アウトカム（比較したい値）は「{name}」です",
                "intent_override": {
                    "outcome_variables": [
                        {"var_n": var_n, "role": "primary_outcome"}
                    ]
                },
            })
        return options

    def _build_user_message(
        self,
        user_prompt: str,
        dataset_metadata: dict,
        conversation_history: list | None = None,
    ) -> str:
        """Serialize the user prompt and metadata for LLM consumption.

        dataset_metadata is keyed by var_n aliases; each entry usually carries a
        "name" field with the real column header so the Planner can resolve the
        user's intent to a column (PL-007). Headers that signalled Layer-1 PII
        are masked upstream (:func:`cie.api.dataset.build_dataset_context`) and
        arrive with no "name" — patient identifiers never reach the LLM. Header
        names are structural metadata, not row values; the planner.yaml contract
        lists "Header names" as allowed input and inject_raw_data_rows stays
        False as the structural guarantee.

        Args:
            user_prompt: Natural language research objective (the current turn).
            dataset_metadata: Structural metadata keyed by var_n aliases, with
                PII-scanned column names under each entry's "name".
            conversation_history: Prior chat turns (oldest→newest) so the current
                prompt can be read as a correction/refinement, not in isolation.

        Returns:
            JSON string sent as the user message turn.
        """
        message: dict = {
            "user_natural_language_prompt": user_prompt,
            "dataset_structural_metadata": dataset_metadata,
            "inject_raw_data_rows": False,
        }
        if conversation_history:
            message["conversation_history"] = conversation_history
            message["note"] = (
                "conversation_history lists earlier turns (oldest→newest). Treat "
                "user_natural_language_prompt as the LATEST turn, which may CORRECT "
                "or REFINE an earlier turn (e.g. changing which column is the "
                "outcome). Resolve the full intent from the whole conversation, "
                "not the latest fragment alone."
            )
        return json.dumps(message, ensure_ascii=False, indent=2)
