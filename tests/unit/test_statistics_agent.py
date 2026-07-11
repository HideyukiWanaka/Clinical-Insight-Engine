"""Unit tests for cie.agents.statistics.StatisticsAgent.

Test matrix:
- test_agent_id_and_scopes              — agent_id="statistics", correct scopes
- test_quality_gate_blocked             — ST-001: gate_passed=False → status="failed"
- test_method_selected_continuous_two   — continuous, 2-group, parametric → t_test
- test_method_selected_non_parametric   — non-parametric → mann_whitney
- test_method_selected_categorical      — categorical_binary → chi_square
- test_method_selected_paired           — paired=True, normal → paired_t_test
- test_method_selected_multi_group      — n_groups=3, normal → one_way_anova
- test_method_selected_survival         — objective=survival_analysis → kaplan_meier
- test_method_selected_correlation      — objective=correlation_analysis → pearson
- test_output_has_required_fields       — selected_methods, analysis_plan, etc.
- test_effect_size_always_reported      — ST-004: effect_size_measure present
- test_justification_present            — ST-002: justification field per method
- test_assumption_checks_declared       — ST-003: assumption_checks_required populated
- test_missing_quality_report_blocked   — no data_quality_report key → blocked
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from cie.agents.base import AgentInput
from cie.agents.statistics import StatisticsAgent
from cie.security.capability_token import CapabilityScope, CapabilityToken

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXEC_ID = str(uuid.uuid4())
NODE_ID = "statistics_node"

_BASE_INTENT = {
    "objective": "between_group_comparison",
    "outcome_type": "continuous",
    "study_design": "randomized_controlled_trial",
    "n_groups_estimate": 2,
    "paired": False,
    "distribution_assumptions": "assumed_normal",
    "outcome_variables": [],
    "predictor_variables": [],
}

_BASE_PAYLOAD = {
    "execution_id": EXEC_ID,
    "intent_object": _BASE_INTENT,
    "data_quality_report": {"quality_gate_passed": True},
    "dataset_structural_metadata": {"columns_count": 5},
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
    sr.validate = MagicMock()
    return sr


@pytest.fixture
def mock_audit() -> MagicMock:
    svc = MagicMock()
    svc.write = AsyncMock()
    return svc


@pytest.fixture
def agent(
    mock_policy_engine: MagicMock,
    mock_schema_registry: MagicMock,
    mock_audit: MagicMock,
) -> StatisticsAgent:
    return StatisticsAgent(mock_policy_engine, mock_schema_registry, mock_audit)


@pytest.fixture
def token() -> CapabilityToken:
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id="statistics",
        bound_step_id=NODE_ID,
        granted_scopes=frozenset({
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.R_CODE_GENERATE_TEMPLATE,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        }),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=300),
    )


def _make_input(payload: dict, token: CapabilityToken) -> AgentInput:
    return AgentInput(
        execution_id=EXEC_ID,
        node_id=NODE_ID,
        capability_token=token,
        payload=payload,
        input_schema_ref="cie://schemas/analysis-request.schema.json",
    )


# ---------------------------------------------------------------------------
# Identity tests
# ---------------------------------------------------------------------------


class TestAgentIdentity:

    def test_agent_id_and_scopes(self, agent: StatisticsAgent) -> None:
        assert agent.agent_id == "statistics"
        assert CapabilityScope.DATASET_READ_VALIDATED in agent.required_scopes
        assert CapabilityScope.R_CODE_GENERATE_TEMPLATE in agent.required_scopes
        assert CapabilityScope.AUDIT_WRITE_ENTRY in agent.required_scopes


# ---------------------------------------------------------------------------
# ST-001: Quality gate enforcement
# ---------------------------------------------------------------------------


class TestQualityGate:

    async def test_quality_gate_blocked(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """ST-001: gate_passed=False must produce status='failed'."""
        payload = {
            **_BASE_PAYLOAD,
            "data_quality_report": {"quality_gate_passed": False},
        }
        result = await agent.run(_make_input(payload, token))

        assert result.status == "failed"
        assert "QUALITY_GATE_BLOCKED" in (result.error_message or "")

    async def test_missing_quality_report_blocked(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """Missing data_quality_report defaults to gate_passed=False."""
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "data_quality_report"}
        result = await agent.run(_make_input(payload, token))

        assert result.status == "failed"
        assert "QUALITY_GATE_BLOCKED" in (result.error_message or "")


# ---------------------------------------------------------------------------
# Method selection tests
# ---------------------------------------------------------------------------


class TestMethodSelection:

    async def test_method_selected_continuous_two(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """Continuous, 2-group, parametric → independent_samples_t_test."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        assert result.status == "success"
        methods = result.output_payload["selected_methods"]
        assert any(m["method_id"] == "independent_samples_t_test" for m in methods)

    async def test_method_selected_non_parametric(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """Continuous, 2-group, non-parametric → mann_whitney_u_test."""
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "distribution_assumptions": "assumed_non_normal"},
        }
        result = await agent.run(_make_input(payload, token))

        methods = result.output_payload["selected_methods"]
        assert any(m["method_id"] == "mann_whitney_u_test" for m in methods)

    async def test_method_selected_categorical(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """Categorical binary outcome → chi_square_test_or_fishers_exact."""
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "outcome_type": "categorical_binary"},
        }
        result = await agent.run(_make_input(payload, token))

        methods = result.output_payload["selected_methods"]
        assert any(m["method_id"] == "chi_square_test_or_fishers_exact" for m in methods)

    async def test_method_selected_paired(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """Paired=True, continuous, parametric → paired_t_test."""
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "paired": True},
        }
        result = await agent.run(_make_input(payload, token))

        methods = result.output_payload["selected_methods"]
        assert any(m["method_id"] == "paired_t_test" for m in methods)

    async def test_method_selected_multi_group(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """n_groups=3, continuous, normal → one_way_anova."""
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "n_groups_estimate": 3},
        }
        result = await agent.run(_make_input(payload, token))

        methods = result.output_payload["selected_methods"]
        assert any(m["method_id"] == "one_way_anova" for m in methods)

    async def test_method_selected_survival(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """Survival analysis → kaplan_meier_estimator."""
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "objective": "survival_analysis", "outcome_type": "survival"},
        }
        result = await agent.run(_make_input(payload, token))

        methods = result.output_payload["selected_methods"]
        assert any(m["method_id"] == "kaplan_meier_estimator" for m in methods)

    async def test_method_selected_correlation(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """Correlation analysis + parametric → pearson_correlation."""
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "objective": "correlation_analysis"},
        }
        result = await agent.run(_make_input(payload, token))

        methods = result.output_payload["selected_methods"]
        assert any(m["method_id"] == "pearson_correlation" for m in methods)


# ---------------------------------------------------------------------------
# Output contract tests (ST-002, ST-003, ST-004)
# ---------------------------------------------------------------------------


class TestOutputContract:

    async def test_output_has_required_fields(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """Output payload must have all guaranteed fields from the contract."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        op = result.output_payload
        for field in (
            "execution_id", "selected_methods", "analysis_plan",
            "r_script_specification", "assumption_checks_required",
            "expected_output_schema", "interpretation_guidelines",
        ):
            assert field in op, f"Missing required field: {field}"

    async def test_effect_size_always_reported(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """ST-004: every selected method must declare an effect_size_measure."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        for method in result.output_payload["selected_methods"]:
            assert "effect_size_measure" in method
            assert method["effect_size_measure"] is not None

    async def test_justification_present(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """ST-002: every method must include a justification field."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        for method in result.output_payload["selected_methods"]:
            assert "justification" in method
            assert len(method["justification"]) > 0

    async def test_assumption_checks_declared_for_t_test(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """ST-003: assumption_checks_required populated for parametric tests."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        checks = result.output_payload["assumption_checks_required"]
        assert isinstance(checks, list)
        assert len(checks) > 0
        assert all("check_id" in c for c in checks)

    async def test_r_script_spec_has_seed(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """Fixed seed=42 must be declared (STAT-005-A reproducibility)."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        r_spec = result.output_payload["r_script_specification"]
        assert r_spec["seed"] == 42


# ---------------------------------------------------------------------------
# Conversational proposal (Workbench chat mode)
# ---------------------------------------------------------------------------

_CONVERSATIONAL_LLM_RESPONSE = """\
=== EXPLANATION ===
性別間の血圧を比較するには、対応のない2群の比較を行います。正規性が仮定できる場合は
Welchのt検定、疑わしい場合はWilcoxon順位和検定を代替として使ってください。

=== CODE: welch_t_test|Welchのt検定 ===
```r
data <- read.csv(file.path(Sys.getenv("WORKSPACE_DIR"), "dataset.csv"))
t.test(BP ~ Sex, data = data)
```

=== CODE: wilcoxon|Wilcoxon順位和検定 ===
```r
data <- read.csv(file.path(Sys.getenv("WORKSPACE_DIR"), "dataset.csv"))
wilcox.test(BP ~ Sex, data = data)
```
"""


class TestConversationalProposal:

    def test_extract_conversational_proposal_parses_two_candidates(self) -> None:
        result = StatisticsAgent._extract_conversational_proposal(
            _CONVERSATIONAL_LLM_RESPONSE
        )
        assert result is not None
        explanation, candidates = result
        assert "対応のない2群" in explanation
        assert len(candidates) == 2
        assert candidates[0]["candidate_id"] == "welch_t_test"
        assert candidates[0]["label"] == "Welchのt検定"
        assert "t.test(BP ~ Sex" in candidates[0]["r_code"]
        assert candidates[1]["candidate_id"] == "wilcoxon"
        assert "wilcox.test(BP ~ Sex" in candidates[1]["r_code"]

    def test_extract_conversational_proposal_returns_none_when_no_code(self) -> None:
        assert StatisticsAgent._extract_conversational_proposal(
            "=== EXPLANATION ===\nNo code here.\n"
        ) is None

    def test_conversation_history_included_in_user_message(self) -> None:
        """Prior chat turns are surfaced to the conversational prompt (P1-B)."""
        msg = StatisticsAgent._build_conversational_user_message(
            method={"method_id": "independent_samples_t_test", "r_function": "t.test"},
            alt_method=None,
            intent_obj={"objective": "between_group_comparison"},
            column_metadata={"収縮期血圧_mmHg": {"inferred_type": "continuous"}},
            references=[],
            alias_map={},
            conversation_history=[
                {"role": "user", "text": "男女の血圧を比較したい"},
                {"role": "assistant", "text": "収縮期血圧で比較しますね"},
            ],
        )
        assert "CONVERSATION SO FAR" in msg
        assert "男女の血圧を比較したい" in msg

    def test_no_history_block_when_empty(self) -> None:
        msg = StatisticsAgent._build_conversational_user_message(
            method={"method_id": "x", "r_function": "t.test"},
            alt_method=None,
            intent_obj={},
            column_metadata={},
            references=[],
            alias_map={},
            conversation_history=[],
        )
        assert "CONVERSATION SO FAR" not in msg

    async def test_conversational_mode_produces_analysis_proposal(
        self,
        mock_policy_engine: MagicMock,
        mock_schema_registry: MagicMock,
        mock_audit: MagicMock,
        token: CapabilityToken,
    ) -> None:
        """conversational_mode=True yields analysis_proposal with 2 candidates
        and mirrors the recommended candidate's code into r_script for
        backward compatibility with Runtime Agent's _extract_script_source."""
        mock_llm = MagicMock()
        mock_llm.provider = "anthropic"
        mock_llm.model = "test-model"
        mock_llm.complete = AsyncMock(return_value=_CONVERSATIONAL_LLM_RESPONSE)

        agent = StatisticsAgent(
            mock_policy_engine, mock_schema_registry, mock_audit,
            llm_client=mock_llm,
        )
        payload = {**_BASE_PAYLOAD, "conversational_mode": True}
        result = await agent.run(_make_input(payload, token))

        assert result.status == "success"
        proposal = result.output_payload["analysis_proposal"]
        assert proposal["recommended_candidate_id"] == "welch_t_test"
        assert len(proposal["code_candidates"]) == 2
        assert result.output_payload["r_script"] == proposal["code_candidates"][0]["r_code"]
        assert result.output_payload["r_script_provenance"]["conversational"] is True

    async def test_conversational_mode_without_llm_client_surfaces_reason(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """No llm_client configured: r_script/analysis_proposal absent, but the
        failure reason must be present in r_script_provenance (not swallowed)."""
        payload = {**_BASE_PAYLOAD, "conversational_mode": True}
        result = await agent.run(_make_input(payload, token))

        assert "analysis_proposal" not in result.output_payload
        assert result.output_payload["r_script"] is None
        assert result.output_payload["r_script_provenance"]["reason"] == (
            "no_llm_client_configured"
        )
