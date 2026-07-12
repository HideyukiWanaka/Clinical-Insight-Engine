"""Unit tests for cie.agents.planner.PlannerAgent.

Test matrix:
- test_success_returns_intent_object             — LLM returns clear intent → status="success"
- test_paired_null_triggers_clarification        — PL-004: paired=null → requires_human_clarification
- test_paired_true_without_subject_id            — PL-005: paired=true + subject_id_var=null → clarification
- test_paired_true_with_subject_id_succeeds      — PL-005 satisfied: paired=true + subject_id_var set
- test_workflow_id_stripped_from_llm_response    — ADR-0001: workflow_id at top level is removed
- test_workflow_id_stripped_from_intent_object   — ADR-0001: workflow_id inside intent_object removed
- test_workflow_id_not_in_output                 — ADR-0001: final output_payload has no workflow_id
- test_pii_in_prompt_blocked                     — PIIDetectedError propagates as status="failed"
- test_raw_data_rows_blocked                     — SecurityViolationError propagates as status="failed"
- test_llm_failure_returns_failed_status         — _call_llm AgentError → status="failed"
- test_httpx_only_no_requests_import             — 'requests' library must not be imported
- test_required_scopes                           — three mandatory scopes declared
- test_agent_id                                  — canonical id is "planner"
- test_context_guard_called_with_payload         — guard invoked before LLM call
- test_clarification_options_provided_on_paired_null — paired=null adds two clarification options
- test_clarification_options_provided_on_paired_true — paired=true no subject adds specify_subject_id
"""

from __future__ import annotations

import importlib
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cie.agents.base import AgentInput, AgentOutput
from cie.agents.planner import PlannerAgent
from cie.core.exceptions import AgentError, PIIDetectedError, SecurityViolationError
from cie.security.capability_token import CapabilityScope, CapabilityToken

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

EXEC_ID = str(uuid.uuid4())
NODE_ID = "planner_node"
INPUT_SCHEMA = "cie://schemas/task.schema.json"
OUTPUT_SCHEMA = "cie://schemas/analysis-request.schema.json"

# Minimal valid LLM response that satisfies PL-004/PL-005 (paired=false, clear intent)
_BASE_LLM_RESPONSE: dict = {
    "intent_object": {
        "objective": "between_group_comparison",
        "outcome_type": "continuous",
        "study_design": "observational",
        # The Planner now receives column names and returns explicit variable
        # mappings; supplying them here keeps the success path off the
        # empty-outcome clarification fallback.
        "outcome_variables": [{"var_n": "var_1", "role": "primary_outcome"}],
        "predictor_variables": [{"var_n": "var_2", "role": "grouping_variable"}],
    },
    "paired": False,
    "subject_id_var": None,
    "n_groups_estimate": 2,
    "confidence_score": 0.85,
    "requires_human_clarification": False,
    "clarification_options": [],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_policy_engine() -> MagicMock:
    pe = MagicMock()
    pe.enforce_multi = AsyncMock()
    return pe


@pytest.fixture
def mock_schema_registry() -> MagicMock:
    sr = MagicMock()
    sr.validate = MagicMock()  # synchronous no-op by default
    return sr


@pytest.fixture
def mock_audit() -> MagicMock:
    svc = MagicMock()
    svc.write = AsyncMock()
    return svc


@pytest.fixture
def mock_context_guard() -> MagicMock:
    guard = MagicMock()
    # Default: passthrough (no PII detected, no raw_data_rows)
    guard.sanitize_context_payload = AsyncMock(return_value={})
    return guard


@pytest.fixture
def mock_llm_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def planner(
    mock_policy_engine: MagicMock,
    mock_schema_registry: MagicMock,
    mock_audit: MagicMock,
    mock_context_guard: MagicMock,
    mock_llm_client: MagicMock,
) -> PlannerAgent:
    return PlannerAgent(
        policy_engine=mock_policy_engine,
        schema_registry=mock_schema_registry,
        audit_service=mock_audit,
        context_guard=mock_context_guard,
        llm_client=mock_llm_client,
    )


@pytest.fixture
def planner_token() -> CapabilityToken:
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id="planner",
        bound_step_id=NODE_ID,
        granted_scopes=frozenset({
            CapabilityScope.DATASET_PROXY_METADATA,
            CapabilityScope.WORKFLOW_STATE_READ,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        }),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=300),
    )


@pytest.fixture
def agent_input(planner_token: CapabilityToken) -> AgentInput:
    return AgentInput(
        execution_id=EXEC_ID,
        node_id=NODE_ID,
        capability_token=planner_token,
        payload={
            "user_natural_language_prompt": "Compare blood pressure between Group A and Group B",
            "dataset_structural_metadata": {
                "var_1": {
                    "inferred_type": "continuous",
                    "unique_count": 200,
                    "name": "収縮期血圧_mmHg",
                },
                "var_2": {
                    "inferred_type": "categorical_binary",
                    "unique_count": 2,
                    "name": "性別",
                },
            },
        },
        input_schema_ref=INPUT_SCHEMA,
    )


# ---------------------------------------------------------------------------
# Helper — build a mock _call_llm that returns a given response dict
# ---------------------------------------------------------------------------


def _llm_mock(response: dict) -> AsyncMock:
    return AsyncMock(return_value=response)


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestPlannerIdentity:

    def test_agent_id(self, planner: PlannerAgent) -> None:
        """Canonical agent_id must be 'planner' (matches orchestrator.yaml)."""
        assert planner.agent_id == "planner"

    def test_input_schema_ref(self, planner: PlannerAgent) -> None:
        assert planner.input_schema_ref == "cie://schemas/planner-input.schema.json"

    def test_output_schema_ref(self, planner: PlannerAgent) -> None:
        assert planner.output_schema_ref == "cie://schemas/analysis-request.schema.json"

    def test_required_scopes(self, planner: PlannerAgent) -> None:
        """Three mandatory scopes must be declared (spec/permissions.yaml planner)."""
        scopes = planner.required_scopes
        assert CapabilityScope.DATASET_PROXY_METADATA in scopes
        assert CapabilityScope.WORKFLOW_STATE_READ in scopes
        assert CapabilityScope.AUDIT_WRITE_ENTRY in scopes

    def test_httpx_only_no_requests_import(self) -> None:
        """'requests' library must never be imported by planner (spec constraint).

        httpx is now used inside LLMClient (cie.core.llm_client) rather than
        imported directly in planner.py.  The constraint that matters is that
        the synchronous 'requests' library is absent.
        """
        import cie.agents.planner as planner_module
        importlib.reload(planner_module)
        assert "requests" not in sys.modules.get("cie.agents.planner", sys).__dict__

        import cie.agents.planner
        import inspect
        src = inspect.getsource(cie.agents.planner)
        assert "import requests" not in src
        # LLM calls are delegated to LLMClient — httpx lives in cie.core.llm_client
        assert "LLMClient" in src


class TestSuccessPath:

    async def test_success_returns_intent_object(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """Happy path: LLM returns unambiguous intent → status='success'."""
        with patch.object(planner, "_call_llm", new=_llm_mock(_BASE_LLM_RESPONSE)):
            result = await planner.run(agent_input)

        assert result.status == "success"
        assert result.agent_id == "planner"
        assert result.execution_id == EXEC_ID
        assert "intent_object" in result.output_payload
        assert result.requires_human_clarification is False

    async def test_paired_true_with_subject_id_succeeds(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """PL-005: paired=true WITH a subject_id_var → no clarification needed."""
        llm_resp = {
            **_BASE_LLM_RESPONSE,
            "paired": True,
            "subject_id_var": "var_1",  # identifier found
        }
        with patch.object(planner, "_call_llm", new=_llm_mock(llm_resp)):
            result = await planner.run(agent_input)

        assert result.status == "success"
        assert result.requires_human_clarification is False

    async def test_context_guard_called_with_payload(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
        mock_context_guard: MagicMock,
    ) -> None:
        """sanitize_context_payload must be called before the LLM, with the payload."""
        with patch.object(planner, "_call_llm", new=_llm_mock(_BASE_LLM_RESPONSE)):
            await planner.run(agent_input)

        mock_context_guard.sanitize_context_payload.assert_called_once_with(
            agent_input.payload,
            execution_id=EXEC_ID,
            agent_id="planner",
        )

    async def test_output_payload_contains_required_fields(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """output_payload must have execution_id, intent_object, confidence_score, etc."""
        with patch.object(planner, "_call_llm", new=_llm_mock(_BASE_LLM_RESPONSE)):
            result = await planner.run(agent_input)

        assert result.output_payload["execution_id"] == EXEC_ID
        assert "intent_object" in result.output_payload
        assert "confidence_score" in result.output_payload
        assert "requires_human_clarification" in result.output_payload
        assert "created_at" in result.output_payload


class TestPL004PairedAmbiguity:
    """PL-004: paired=null must trigger requires_human_clarification=true."""

    async def test_paired_null_triggers_clarification(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """'3ヶ月と6ヶ月を比較' is ambiguous — LLM returns paired=null → clarification."""
        ambiguous_input = AgentInput(
            execution_id=EXEC_ID,
            node_id=NODE_ID,
            capability_token=agent_input.capability_token,
            payload={
                "user_natural_language_prompt": "3ヶ月と6ヶ月の転帰を比較したい",
                "dataset_structural_metadata": {},
            },
            input_schema_ref=INPUT_SCHEMA,
        )
        llm_resp = {
            **_BASE_LLM_RESPONSE,
            "paired": None,         # ambiguous temporal language
            "requires_human_clarification": False,  # Planner must still catch this
        }
        with patch.object(planner, "_call_llm", new=_llm_mock(llm_resp)):
            result = await planner.run(ambiguous_input)

        assert result.requires_human_clarification is True
        assert result.status == "clarification_required"

    async def test_clarification_options_provided_on_paired_null(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """Two options must be offered: independent vs paired."""
        llm_resp = {**_BASE_LLM_RESPONSE, "paired": None, "clarification_options": []}
        with patch.object(planner, "_call_llm", new=_llm_mock(llm_resp)):
            result = await planner.run(agent_input)

        option_ids = {o["option_id"] for o in result.clarification_options}
        assert "independent" in option_ids
        assert "paired" in option_ids


class TestPL005SubjectId:
    """PL-005: paired=true + subject_id_var=null must trigger clarification."""

    async def test_paired_true_without_subject_id(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """LLM infers paired design but cannot identify subject column → clarification."""
        llm_resp = {
            **_BASE_LLM_RESPONSE,
            "paired": True,
            "subject_id_var": None,  # no identifier found
            "requires_human_clarification": False,  # Planner overrides via PL-005
        }
        with patch.object(planner, "_call_llm", new=_llm_mock(llm_resp)):
            result = await planner.run(agent_input)

        assert result.requires_human_clarification is True
        assert result.status == "clarification_required"

    async def test_clarification_options_provided_on_paired_true(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """A 'specify_subject_id' clarification option must be included."""
        llm_resp = {
            **_BASE_LLM_RESPONSE,
            "paired": True,
            "subject_id_var": None,
            "clarification_options": [],
        }
        with patch.object(planner, "_call_llm", new=_llm_mock(llm_resp)):
            result = await planner.run(agent_input)

        option_ids = [o["option_id"] for o in result.clarification_options]
        assert "specify_subject_id" in option_ids


class TestADR0001WorkflowIdAbsent:
    """ADR-0001: workflow_id must never appear in the PlannerAgent's output."""

    async def test_workflow_id_not_in_output(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """workflow_id must be absent from output_payload even if LLM includes it."""
        llm_resp = {
            **_BASE_LLM_RESPONSE,
            "workflow_id": "wf_should_be_stripped",  # injected by rogue LLM
        }
        with patch.object(planner, "_call_llm", new=_llm_mock(llm_resp)):
            result = await planner.run(agent_input)

        assert "workflow_id" not in result.output_payload

    async def test_workflow_id_stripped_from_intent_object(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """workflow_id inside intent_object must also be stripped (ADR-0001)."""
        llm_resp = {
            **_BASE_LLM_RESPONSE,
            "intent_object": {
                **_BASE_LLM_RESPONSE["intent_object"],
                "workflow_id": "also_illegal",  # inside intent_object
            },
        }
        with patch.object(planner, "_call_llm", new=_llm_mock(llm_resp)):
            result = await planner.run(agent_input)

        assert "workflow_id" not in result.output_payload
        assert "workflow_id" not in result.output_payload.get("intent_object", {})


class TestSecurityGuards:
    """Context guard raises must propagate as status='failed' via BaseAgent.run."""

    async def test_pii_in_prompt_blocked(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
        mock_context_guard: MagicMock,
    ) -> None:
        """PIIDetectedError from context_guard must produce status='failed'."""
        mock_context_guard.sanitize_context_payload.side_effect = PIIDetectedError(
            "SSN detected in prompt",
            severity="CRITICAL",
            field_hint="user_natural_language_prompt",
            execution_id=EXEC_ID,
        )
        result = await planner.run(agent_input)

        assert result.status == "failed"
        assert result.error_code == "PII_DETECTED"

    async def test_raw_data_rows_blocked(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
        mock_context_guard: MagicMock,
    ) -> None:
        """raw_data_rows in payload raises SecurityViolationError → status='failed'.

        inject_raw_data_rows=False is structurally enforced by ContextGuard.
        """
        mock_context_guard.sanitize_context_payload.side_effect = SecurityViolationError(
            "raw_data_rows must not be injected into agent context",
            policy_id="RT-004",
            execution_id=EXEC_ID,
        )
        raw_payload_input = AgentInput(
            execution_id=EXEC_ID,
            node_id=NODE_ID,
            capability_token=agent_input.capability_token,
            payload={
                "user_natural_language_prompt": "Summarise the data",
                "dataset_structural_metadata": {},
                "raw_data_rows": [{"var_1": 1.0}],  # must never reach LLM
            },
            input_schema_ref=INPUT_SCHEMA,
        )
        result = await planner.run(raw_payload_input)

        assert result.status == "failed"
        assert result.error_code == "SECURITY_VIOLATION"
        # LLM must NOT have been called
        # (the guard check happens before _call_llm inside _execute)


class TestLLMFailure:

    async def test_llm_failure_returns_failed_status(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """AgentError from _call_llm must produce status='failed'."""
        with patch.object(
            planner,
            "_call_llm",
            new=AsyncMock(side_effect=AgentError(
                "INTENT_EXTRACTION_FAILED: connection timeout",
                agent_id="planner",
            )),
        ):
            result = await planner.run(agent_input)

        assert result.status == "failed"
        assert result.error_code == "AGENT_ERROR"
        assert "INTENT_EXTRACTION_FAILED" in (result.error_message or "")

    async def test_llm_response_is_called_with_system_and_user_prompts(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """_call_llm must receive non-empty system_prompt and user_message strings."""
        captured: dict = {}

        async def capture_call(system_prompt: str, user_message: str) -> dict:
            captured["system"] = system_prompt
            captured["user"] = user_message
            return _BASE_LLM_RESPONSE

        with patch.object(planner, "_call_llm", new=capture_call):
            await planner.run(agent_input)

        assert "PL-001" in captured["system"]
        assert "ADR-0001" in captured["system"]
        assert "workflow_id" in captured["system"].lower()
        assert "user_natural_language_prompt" in captured["user"]
        assert "inject_raw_data_rows" in captured["user"]


# ---------------------------------------------------------------------------
# Semantic cache integration (ADR-0004 / prompts/phase_semantic_cache.md)
# ---------------------------------------------------------------------------


class TestSemanticCacheIntegration:

    @pytest.fixture
    def cached_planner(
        self,
        tmp_path,
        mock_policy_engine: MagicMock,
        mock_schema_registry: MagicMock,
        mock_audit: MagicMock,
        mock_context_guard: MagicMock,
        mock_llm_client: MagicMock,
    ) -> PlannerAgent:
        from cie.cache.store import CacheStore

        mock_llm_client.provider = "anthropic"
        mock_llm_client.model = "model-x"
        return PlannerAgent(
            policy_engine=mock_policy_engine,
            schema_registry=mock_schema_registry,
            audit_service=mock_audit,
            context_guard=mock_context_guard,
            llm_client=mock_llm_client,
            cache_store=CacheStore(cache_dir=tmp_path),
        )

    async def test_cache_hit_skips_llm_call(
        self,
        cached_planner: PlannerAgent,
        agent_input: AgentInput,
        mock_audit: MagicMock,
    ) -> None:
        """Second identical run must be served from cache without an LLM call."""
        llm_mock = _llm_mock(_BASE_LLM_RESPONSE)
        with patch.object(cached_planner, "_call_llm", new=llm_mock):
            first = await cached_planner.run(agent_input)
            second = await cached_planner.run(agent_input)

        assert first.status == "success"
        assert second.status == "success"
        assert llm_mock.await_count == 1  # LLM called once only
        assert second.output_payload["intent_object"] == \
            first.output_payload["intent_object"]

        # CA-001: CACHE_HIT audit event recorded
        actions = [call.args[0].action for call in mock_audit.write.await_args_list]
        assert "CACHE_HIT" in actions

    async def test_cache_store_none_behaves_as_before(
        self,
        planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """cache_store=None disables caching: every run calls the LLM."""
        llm_mock = _llm_mock(_BASE_LLM_RESPONSE)
        with patch.object(planner, "_call_llm", new=llm_mock):
            await planner.run(agent_input)
            await planner.run(agent_input)

        assert llm_mock.await_count == 2

    async def test_clarification_result_not_cached(
        self,
        cached_planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """CA-003: clarification-required results must not populate the cache."""
        ambiguous = dict(_BASE_LLM_RESPONSE)
        ambiguous["paired"] = None  # PL-004 → requires clarification
        llm_mock = _llm_mock(ambiguous)
        with patch.object(cached_planner, "_call_llm", new=llm_mock):
            first = await cached_planner.run(agent_input)
            second = await cached_planner.run(agent_input)

        assert first.status == "clarification_required"
        assert second.status == "clarification_required"
        assert llm_mock.await_count == 2  # no cache hit

    async def test_low_confidence_result_not_cached(
        self,
        cached_planner: PlannerAgent,
        agent_input: AgentInput,
    ) -> None:
        """CA-002: confidence < 0.7 must not populate the cache."""
        low_conf = dict(_BASE_LLM_RESPONSE)
        low_conf["confidence_score"] = 0.5
        llm_mock = _llm_mock(low_conf)
        with patch.object(cached_planner, "_call_llm", new=llm_mock):
            await cached_planner.run(agent_input)
            await cached_planner.run(agent_input)

        assert llm_mock.await_count == 2


# ---------------------------------------------------------------------------
# Fix A — empty-outcome fallback resolves by name or defers to a human
# ---------------------------------------------------------------------------


def _agent_input_with(prompt: str, metadata: dict, token: CapabilityToken) -> AgentInput:
    return AgentInput(
        execution_id=EXEC_ID,
        node_id=NODE_ID,
        capability_token=token,
        payload={
            "user_natural_language_prompt": prompt,
            "dataset_structural_metadata": metadata,
        },
        input_schema_ref=INPUT_SCHEMA,
    )


def _llm_no_outcome() -> dict:
    resp = {
        "intent_object": {
            "objective": "between_group_comparison",
            "outcome_type": "continuous",
            "study_design": "cross_sectional",
        },
        "paired": False,
        "subject_id_var": None,
        "n_groups_estimate": 2,
        "confidence_score": 0.85,
        "requires_human_clarification": False,
        "clarification_options": [],
    }
    return resp


class TestEmptyOutcomeFallback:
    async def test_confident_name_match_selects_column(
        self, planner: PlannerAgent, planner_token: CapabilityToken
    ) -> None:
        """One column name matches the prompt → pick it, no clarification."""
        metadata = {
            "var_1": {"inferred_type": "continuous", "unique_count": 5, "name": "検査年"},
            "var_2": {"inferred_type": "continuous", "unique_count": 90, "name": "収縮期血圧_mmHg"},
            "var_3": {"inferred_type": "categorical_binary", "unique_count": 2, "name": "性別"},
        }
        ai = _agent_input_with("男女の血圧を比較したい", metadata, planner_token)
        with patch.object(planner, "_call_llm", new=_llm_mock(_llm_no_outcome())):
            result = await planner.run(ai)

        assert result.status == "success"
        outcomes = result.output_payload["intent_object"]["outcome_variables"]
        assert outcomes == [{"var_n": "var_2", "role": "primary_outcome"}]

    async def test_ambiguous_match_requires_clarification(
        self, planner: PlannerAgent, planner_token: CapabilityToken
    ) -> None:
        """Two columns match "血圧" → defer to the human, offer them as options."""
        metadata = {
            "var_1": {"inferred_type": "continuous", "unique_count": 5, "name": "検査年"},
            "var_2": {"inferred_type": "continuous", "unique_count": 90, "name": "収縮期血圧_mmHg"},
            "var_3": {"inferred_type": "continuous", "unique_count": 70, "name": "拡張期血圧_mmHg"},
        }
        ai = _agent_input_with("血圧を比較したい", metadata, planner_token)
        with patch.object(planner, "_call_llm", new=_llm_mock(_llm_no_outcome())):
            result = await planner.run(ai)

        assert result.status == "clarification_required"
        opts = result.output_payload.get("clarification_options", [])
        outcome_opts = [
            o for o in opts if str(o.get("option_id", "")).startswith("outcome:")
        ]
        # One clickable option per named continuous column, each carrying the
        # override that pins outcome_variables to that column.
        assert {o["option_id"] for o in outcome_opts} == {
            "outcome:var_1", "outcome:var_2", "outcome:var_3"
        }
        first_override = outcome_opts[0]["intent_override"]["outcome_variables"][0]
        assert first_override["role"] == "primary_outcome"

    async def test_never_selects_pii_masked_column(
        self, planner: PlannerAgent, planner_token: CapabilityToken
    ) -> None:
        """A nameless (PII-masked) column is never offered/selected as outcome."""
        metadata = {
            "var_1": {"inferred_type": "continuous", "unique_count": 190},  # masked, no name
            "var_2": {"inferred_type": "continuous", "unique_count": 90, "name": "収縮期血圧_mmHg"},
        }
        ai = _agent_input_with("血圧を見たい", metadata, planner_token)
        with patch.object(planner, "_call_llm", new=_llm_mock(_llm_no_outcome())):
            result = await planner.run(ai)

        outcomes = result.output_payload["intent_object"]["outcome_variables"]
        assert outcomes == [{"var_n": "var_2", "role": "primary_outcome"}]
