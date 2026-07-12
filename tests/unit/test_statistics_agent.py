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

    # --- off-catalogue detection ---------------------------------------------

    def test_select_method_matched_for_catalog_objective(
        self, agent: StatisticsAgent
    ) -> None:
        method, matched = agent._select_method(
            "between_group_comparison", "continuous", 2, False, "assumed_normal"
        )
        assert matched is True
        assert method["method_id"] == "independent_samples_t_test"

    def test_select_method_unmatched_for_uncatalogued_objective(
        self, agent: StatisticsAgent
    ) -> None:
        # prediction_model has no modelled method → falls to the generic default
        # but is reported as off-catalogue.
        method, matched = agent._select_method(
            "prediction_model", "continuous", 2, False, "assumed_normal"
        )
        assert matched is False
        assert method["method_id"] == "independent_samples_t_test"

    def test_skill_grounding_off_catalog_injects_no_skill(
        self, agent: StatisticsAgent
    ) -> None:
        # Off-catalogue must never inject a (mismatched) Skill block.
        block, grounded = agent._skill_grounding("independent_samples_t_test", True)
        assert block == ""
        assert grounded is False

    async def test_provenance_off_catalog_false_for_catalog_request(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))
        prov = result.output_payload["r_script_provenance"]
        assert prov["off_catalog"] is False
        assert prov["grounded_by_skill"] is True

    async def test_provenance_off_catalog_true_for_uncatalogued_request(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "objective": "prediction_model"},
        }
        result = await agent.run(_make_input(payload, token))
        prov = result.output_payload["r_script_provenance"]
        assert prov["off_catalog"] is True
        assert prov["grounded_by_skill"] is False


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

    async def test_off_catalog_conversational_proposal_has_caveat(
        self,
        mock_policy_engine: MagicMock,
        mock_schema_registry: MagicMock,
        mock_audit: MagicMock,
        token: CapabilityToken,
    ) -> None:
        """Off-catalogue conversational proposal flags off_catalog + caveat."""
        mock_llm = MagicMock()
        mock_llm.provider = "anthropic"
        mock_llm.model = "test-model"
        mock_llm.complete = AsyncMock(return_value=_CONVERSATIONAL_LLM_RESPONSE)

        agent = StatisticsAgent(
            mock_policy_engine, mock_schema_registry, mock_audit, llm_client=mock_llm,
        )
        payload = {
            **_BASE_PAYLOAD,
            "conversational_mode": True,
            "intent_object": {**_BASE_INTENT, "objective": "prediction_model"},
        }
        result = await agent.run(_make_input(payload, token))

        proposal = result.output_payload["analysis_proposal"]
        assert proposal["off_catalog"] is True
        assert "caveat_markdown" in proposal and proposal["caveat_markdown"]
        assert result.output_payload["r_script_provenance"]["off_catalog"] is True
        assert result.output_payload["r_script_provenance"]["grounded_by_skill"] is False

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


# ---------------------------------------------------------------------------
# Streaming conversational proposal (Phase 2, WS /ws/chat)
# ---------------------------------------------------------------------------


class _FakeStreamLLM:
    """Async-generator LLM stub: yields the canned response in small chunks."""

    def __init__(self, text: str, chunk_size: int = 17) -> None:
        self._text = text
        self._chunk = chunk_size
        self.provider = "anthropic"
        self.model = "test-model"

    async def stream_messages(self, system, messages, assistant_prefill=None):
        for i in range(0, len(self._text), self._chunk):
            yield self._text[i : i + self._chunk]


async def _collect_stream(agent: StatisticsAgent, payload: dict,
                          token: CapabilityToken) -> list[dict]:
    events: list[dict] = []
    async for ev in agent.stream_conversational_proposal(_make_input(payload, token)):
        events.append(ev)
    return events


class TestStreamingConversationalProposal:

    def test_explanation_so_far_withholds_partial_code_marker(self) -> None:
        # No EXPLANATION opener yet → nothing to emit.
        assert StatisticsAgent._explanation_so_far("partial pre") == ""
        # Opener present, no CODE marker yet → a trailing slice is withheld so a
        # half-formed "=== CODE:" can never flash as prose.
        partial = "=== EXPLANATION ===\nhello world\n=== CO"
        got = StatisticsAgent._explanation_so_far(partial)
        # A trailing slice is withheld, so `got` is a (possibly shortened) prefix
        # of the prose — and crucially never contains the half-formed marker.
        assert "hello world".startswith(got)
        assert "=== CO" not in got
        # Once the CODE marker resolves, the full explanation is available.
        full = "=== EXPLANATION ===\nhello world\n=== CODE: a|b ===\n```r\nx\n```"
        assert StatisticsAgent._explanation_so_far(full) == "hello world"

    async def test_stream_yields_deltas_then_proposal(
        self,
        mock_policy_engine: MagicMock,
        mock_schema_registry: MagicMock,
        mock_audit: MagicMock,
        token: CapabilityToken,
    ) -> None:
        agent = StatisticsAgent(
            mock_policy_engine, mock_schema_registry, mock_audit,
            llm_client=_FakeStreamLLM(_CONVERSATIONAL_LLM_RESPONSE),
        )
        payload = {**_BASE_PAYLOAD, "conversational_mode": True}
        events = await _collect_stream(agent, payload, token)

        deltas = [e["text"] for e in events if e["type"] == "delta"]
        proposals = [e for e in events if e["type"] == "proposal"]
        assert deltas, "expected at least one streamed explanation delta"
        assert len(proposals) == 1
        proposal = proposals[0]["analysis_proposal"]
        # The concatenated deltas reconstruct the explanation prose (the code is
        # withheld from the stream and only ever arrives as candidates).
        assert "".join(deltas).strip() == proposal["explanation_markdown"].strip()
        assert "```r" not in "".join(deltas)
        assert len(proposal["code_candidates"]) == 2
        assert proposal["recommended_candidate_id"] == "welch_t_test"
        assert proposals[0]["r_script_provenance"]["llm_generated"] is True
        assert proposals[0]["recommended_r_script"].startswith("data <-")

    async def test_stream_enforces_scope_validates_and_audits(
        self,
        mock_policy_engine: MagicMock,
        mock_schema_registry: MagicMock,
        mock_audit: MagicMock,
        token: CapabilityToken,
    ) -> None:
        """Governance parity with run(): scope check + input validation + audit."""
        agent = StatisticsAgent(
            mock_policy_engine, mock_schema_registry, mock_audit,
            llm_client=_FakeStreamLLM(_CONVERSATIONAL_LLM_RESPONSE),
        )
        payload = {**_BASE_PAYLOAD, "conversational_mode": True}
        await _collect_stream(agent, payload, token)

        mock_policy_engine.enforce_multi.assert_awaited_once()
        mock_schema_registry.validate.assert_called_once()
        mock_audit.write.assert_awaited_once()

    async def test_stream_off_catalog_flags_caveat(
        self,
        mock_policy_engine: MagicMock,
        mock_schema_registry: MagicMock,
        mock_audit: MagicMock,
        token: CapabilityToken,
    ) -> None:
        agent = StatisticsAgent(
            mock_policy_engine, mock_schema_registry, mock_audit,
            llm_client=_FakeStreamLLM(_CONVERSATIONAL_LLM_RESPONSE),
        )
        payload = {
            **_BASE_PAYLOAD,
            "conversational_mode": True,
            "intent_object": {**_BASE_INTENT, "objective": "prediction_model"},
        }
        events = await _collect_stream(agent, payload, token)
        proposal_ev = next(e for e in events if e["type"] == "proposal")
        assert proposal_ev["analysis_proposal"]["off_catalog"] is True
        assert proposal_ev["analysis_proposal"]["caveat_markdown"]
        assert proposal_ev["r_script_provenance"]["grounded_by_skill"] is False

    async def test_stream_without_llm_client_emits_error(
        self, agent: StatisticsAgent, token: CapabilityToken
    ) -> None:
        """No llm_client → a single error event whose reason is never silent."""
        payload = {**_BASE_PAYLOAD, "conversational_mode": True}
        events = await _collect_stream(agent, payload, token)
        assert [e["type"] for e in events] == ["error"]
        assert events[0]["reason"] == "no_llm_client_configured"

    async def test_stream_quality_gate_blocked_emits_error(
        self,
        mock_policy_engine: MagicMock,
        mock_schema_registry: MagicMock,
        mock_audit: MagicMock,
        token: CapabilityToken,
    ) -> None:
        agent = StatisticsAgent(
            mock_policy_engine, mock_schema_registry, mock_audit,
            llm_client=_FakeStreamLLM(_CONVERSATIONAL_LLM_RESPONSE),
        )
        payload = {
            **_BASE_PAYLOAD,
            "conversational_mode": True,
            "data_quality_report": {"quality_gate_passed": False},
        }
        events = await _collect_stream(agent, payload, token)
        assert events == [{"type": "error", "reason": "quality_gate_blocked"}]


class _CapturingStreamLLM:
    """Stream stub that records the (system, messages) it was called with."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.provider = "anthropic"
        self.model = "test-model"
        self.system: str | None = None
        self.messages: list | None = None

    async def stream_messages(self, system, messages, assistant_prefill=None):
        self.system = system
        self.messages = messages
        yield self._text


class TestStreamingContinuation:
    """Follow-up (continuation) turns stream as conversational proposals too."""

    async def test_continuation_query_grounds_prompt_and_flags_provenance(
        self,
        mock_policy_engine: MagicMock,
        mock_schema_registry: MagicMock,
        mock_audit: MagicMock,
        token: CapabilityToken,
    ) -> None:
        llm = _CapturingStreamLLM(_CONVERSATIONAL_LLM_RESPONSE)
        agent = StatisticsAgent(
            mock_policy_engine, mock_schema_registry, mock_audit, llm_client=llm,
        )
        payload = {
            **_BASE_PAYLOAD,
            "conversational_mode": True,
            "continuation_query": "サブグループごとに効果量も出したい",
            "prior_statistical_results": {
                "test_name": "Welch t-test", "p_value": 0.03,
                "effect_size": 0.42, "effect_size_measure": "Cohen's d",
                # Not in the whitelist — must NOT be echoed back to the model.
                "raw_rows": [[1, 2], [3, 4]],
            },
            "prior_r_script": "data <- read.csv('x')\nt.test(BP ~ Sex)",
        }
        events = await _collect_stream(agent, payload, token)

        # Provenance marks it as a continuation.
        proposal_ev = next(e for e in events if e["type"] == "proposal")
        assert proposal_ev["r_script_provenance"]["continuation"] is True

        # The follow-up query + whitelisted prior results reached the prompt; the
        # non-whitelisted key (raw rows) did not.
        user_msg = llm.messages[0]["content"]
        assert "サブグループごとに効果量も出したい" in user_msg
        assert "Welch t-test" in user_msg
        assert "raw_rows" not in user_msg
        # The follow-up framing preamble is prepended to the system prompt.
        assert "FOLLOW-UP" in llm.system

    async def test_continuation_offers_single_candidate(
        self,
        mock_policy_engine: MagicMock,
        mock_schema_registry: MagicMock,
        mock_audit: MagicMock,
        token: CapabilityToken,
    ) -> None:
        """A follow-up stays focused: no parametric/non-parametric fork request."""
        llm = _CapturingStreamLLM(_CONVERSATIONAL_LLM_RESPONSE)
        agent = StatisticsAgent(
            mock_policy_engine, mock_schema_registry, mock_audit, llm_client=llm,
        )
        payload = {
            **_BASE_PAYLOAD,
            "conversational_mode": True,
            "continuation_query": "信頼区間も表示して",
        }
        await _collect_stream(agent, payload, token)

        # No alternative method is offered to the model on a follow-up turn.
        assert '"alternative_method": null' in llm.messages[0]["content"]
