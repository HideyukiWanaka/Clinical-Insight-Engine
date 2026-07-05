"""Unit tests for Orchestrator decision-node routing (Phase 6).

Covers:
- spec/workflow.yaml rules parsing into WorkflowNodeDef.rules
- decision_assumption normality branch (default / intent-driven / report-driven)
- pruned branch is never dispatched; downstream approval gate still unblocks
- prediction workflow decision (agent + rules on the same node)
- DECISION_ROUTED audit event
- resume_workflow continues past security_review to the evaluation node
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cie.agents.base import AgentInput, AgentOutput
from cie.core.audit import AuditService
from cie.security.capability_token import CapabilityToken, CapabilityTokenManager
from cie.workflow.orchestrator import Orchestrator
from cie.workflow.registry import WorkflowRegistry
from cie.workflow.states import WorkflowState, WorkflowStateMachine

_WORKFLOW_YAML = Path(__file__).parent.parent.parent / "spec" / "workflow.yaml"

_GENERIC_INTENT = {
    "objective": "between_group_comparison",
    "outcome_type": "continuous",
    "requires_human_clarification": False,
}


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_registry() -> WorkflowRegistry:
    return WorkflowRegistry.load_from_yaml(_WORKFLOW_YAML)


@pytest.fixture
def mock_audit() -> AuditService:
    svc = MagicMock(spec=AuditService)
    svc.write = AsyncMock()
    return svc


@pytest.fixture
def mock_token_manager() -> CapabilityTokenManager:
    mgr = MagicMock(spec=CapabilityTokenManager)

    def _issue(execution_id, agent_id, step_id, requested_scopes):
        now = datetime.now(timezone.utc)
        return CapabilityToken(
            token_id=str(uuid.uuid4()),
            bound_execution_id=execution_id,
            bound_agent_id=agent_id,
            bound_step_id=step_id,
            granted_scopes=frozenset(requested_scopes),
            denied_scopes=frozenset(),
            issued_at=now,
            expires_at=now + timedelta(seconds=300),
        )

    mgr.issue.side_effect = _issue
    mgr.revoke.side_effect = lambda token: token
    return mgr


def _make_recording_agent(dispatched: list[str]) -> MagicMock:
    """Mock agent that records every node_id it is dispatched on."""
    agent = MagicMock()
    agent.agent_id = "mock_agent"
    agent.required_scopes = []

    async def _run(agent_input: AgentInput) -> AgentOutput:
        dispatched.append(agent_input.node_id)
        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id="mock_agent",
            status="success",
            output_payload={"ok": True},
            output_schema_ref="cie://schemas/task.schema.json",
        )

    agent.run = _run
    return agent


def _make_orchestrator(
    registry: WorkflowRegistry,
    token_manager: CapabilityTokenManager,
    audit: AuditService,
    dispatched: list[str],
) -> Orchestrator:
    agent = _make_recording_agent(dispatched)
    agent_registry = {
        agent_id: agent
        for agent_id in (
            "planner", "data_quality", "statistics", "visualization",
            "reporting", "reviewer", "security", "runtime", "evaluation",
        )
    }
    return Orchestrator(
        workflow_registry=registry,
        state_machine=WorkflowStateMachine(),
        token_manager=token_manager,
        policy_engine=MagicMock(),
        context_guard=MagicMock(),
        audit_service=audit,
        agent_registry=agent_registry,
    )


# ---------------------------------------------------------------------------
# Rules parsing
# ---------------------------------------------------------------------------


class TestRulesParsing:

    def test_decision_assumption_rules_loaded(self, real_registry) -> None:
        node = real_registry.get("clinical_analysis_standard").get_node(
            "decision_assumption"
        )
        assert node.node_type == "decision"
        assert node.rules == {
            "normality": {True: "generate_r_script", False: "select_nonparametric"}
        }

    def test_prediction_rules_loaded(self, real_registry) -> None:
        node = real_registry.get("clinical_analysis_prediction").get_node(
            "select_prediction_method"
        )
        assert node.rules["epp_sufficient"][True] == "generate_standard_logistic"
        assert node.rules["epp_sufficient"][False] == "generate_firth_logistic"

    def test_task_nodes_have_empty_rules(self, real_registry) -> None:
        node = real_registry.get("clinical_analysis_standard").get_node("intake")
        assert node.rules == {}

    def test_evaluation_node_has_agent(self, real_registry) -> None:
        for wf_id in real_registry.list_workflow_ids():
            node = real_registry.get(wf_id).get_node("evaluation")
            assert node.agent_id == "evaluation", wf_id


# ---------------------------------------------------------------------------
# Condition value resolution
# ---------------------------------------------------------------------------


class TestResolveConditionValue:

    def test_top_level_key_wins(self) -> None:
        value, source = Orchestrator._resolve_condition_value(
            "normality", {"normality": False}
        )
        assert value is False
        assert source == "context_top_level"

    def test_assumption_report_container(self) -> None:
        value, source = Orchestrator._resolve_condition_value(
            "normality", {"assumption_report": {"normality": False}}
        )
        assert value is False
        assert source == "assumption_report"

    def test_intent_distribution_fallback_normal(self) -> None:
        ctx = {"intent_object": {"distribution_assumptions": "assumed_normal"}}
        value, source = Orchestrator._resolve_condition_value("normality", ctx)
        assert value is True
        assert source == "intent_object.distribution_assumptions"

    def test_intent_distribution_fallback_nonparametric(self) -> None:
        ctx = {"intent_object": {"distribution_assumptions": "non_parametric"}}
        value, _ = Orchestrator._resolve_condition_value("normality", ctx)
        assert value is False

    def test_default_is_primary_branch(self) -> None:
        value, source = Orchestrator._resolve_condition_value("normality", {})
        assert value is True
        assert source == "default_primary_branch"

    def test_epp_report_container(self) -> None:
        value, source = Orchestrator._resolve_condition_value(
            "epp_sufficient", {"epp_report": {"epp_sufficient": False}}
        )
        assert value is False
        assert source == "epp_report"

    def test_string_values_coerced(self) -> None:
        value, _ = Orchestrator._resolve_condition_value(
            "normality", {"normality": "failed"}
        )
        assert value is False


# ---------------------------------------------------------------------------
# Routing behaviour in the standard workflow
# ---------------------------------------------------------------------------


class TestStandardWorkflowRouting:

    async def test_default_routes_to_generate_r_script(
        self, real_registry, mock_token_manager, mock_audit
    ) -> None:
        dispatched: list[str] = []
        orch = _make_orchestrator(real_registry, mock_token_manager, mock_audit, dispatched)
        result = await orch.run_workflow(str(uuid.uuid4()), _GENERIC_INTENT)
        assert result["final_state"] == WorkflowState.WAITING_FOR_HUMAN.value
        assert "generate_r_script" in dispatched
        assert "select_nonparametric" not in dispatched

    async def test_nonparametric_intent_routes_to_fallback(
        self, real_registry, mock_token_manager, mock_audit
    ) -> None:
        dispatched: list[str] = []
        orch = _make_orchestrator(real_registry, mock_token_manager, mock_audit, dispatched)
        intent = {**_GENERIC_INTENT, "distribution_assumptions": "non_parametric"}
        result = await orch.run_workflow(str(uuid.uuid4()), intent)
        # security_review depends on generate_r_script, which is pruned but
        # counted as satisfied — the approval gate must still be reached.
        assert result["final_state"] == WorkflowState.WAITING_FOR_HUMAN.value
        assert "select_nonparametric" in dispatched
        assert "generate_r_script" not in dispatched

    async def test_assumption_report_context_routes_false(
        self, real_registry, mock_token_manager, mock_audit
    ) -> None:
        dispatched: list[str] = []
        orch = _make_orchestrator(real_registry, mock_token_manager, mock_audit, dispatched)
        await orch.run_workflow(
            str(uuid.uuid4()),
            _GENERIC_INTENT,
            dataset_context={"assumption_report": {"normality": False}},
        )
        assert "select_nonparametric" in dispatched
        assert "generate_r_script" not in dispatched

    async def test_decision_routed_audit_event(
        self, real_registry, mock_token_manager, mock_audit
    ) -> None:
        dispatched: list[str] = []
        orch = _make_orchestrator(real_registry, mock_token_manager, mock_audit, dispatched)
        await orch.run_workflow(str(uuid.uuid4()), _GENERIC_INTENT)
        actions = [
            call.args[0].action
            for call in mock_audit.write.call_args_list
            if call.args
        ]
        assert "DECISION_ROUTED:decision_assumption" in actions


# ---------------------------------------------------------------------------
# Prediction workflow (decision node carrying both agent and rules)
# ---------------------------------------------------------------------------


class TestPredictionWorkflowRouting:

    async def test_default_epp_routes_standard_logistic(
        self, real_registry, mock_token_manager, mock_audit
    ) -> None:
        dispatched: list[str] = []
        orch = _make_orchestrator(real_registry, mock_token_manager, mock_audit, dispatched)
        intent = {**_GENERIC_INTENT, "objective": "prediction_model"}
        result = await orch.run_workflow(str(uuid.uuid4()), intent)
        assert result["workflow_id_selected"] == "clinical_analysis_prediction"
        assert "select_prediction_method" in dispatched  # agent ran first
        assert "generate_standard_logistic" in dispatched
        assert "generate_firth_logistic" not in dispatched

    async def test_epp_insufficient_routes_firth(
        self, real_registry, mock_token_manager, mock_audit
    ) -> None:
        dispatched: list[str] = []
        orch = _make_orchestrator(real_registry, mock_token_manager, mock_audit, dispatched)
        intent = {**_GENERIC_INTENT, "objective": "prediction_model"}
        await orch.run_workflow(
            str(uuid.uuid4()),
            intent,
            dataset_context={"epp_report": {"epp_sufficient": False}},
        )
        assert "generate_firth_logistic" in dispatched
        assert "generate_standard_logistic" not in dispatched


# ---------------------------------------------------------------------------
# Approval → resume → full completion (evaluation node dispatched)
# ---------------------------------------------------------------------------


class TestResumeToEvaluation:

    async def test_resume_completes_through_evaluation(
        self, real_registry, mock_token_manager, mock_audit
    ) -> None:
        dispatched: list[str] = []
        orch = _make_orchestrator(real_registry, mock_token_manager, mock_audit, dispatched)
        execution_id = str(uuid.uuid4())

        result = await orch.run_workflow(execution_id, _GENERIC_INTENT)
        assert result["final_state"] == WorkflowState.WAITING_FOR_HUMAN.value
        assert "evaluation" not in dispatched

        resume_result = await orch.resume_workflow(
            execution_id, {"execution_permission": True}
        )
        assert resume_result["final_state"] == WorkflowState.COMPLETED.value
        for node_id in ("runtime_execution", "visualization", "reporting",
                        "reviewer", "evaluation"):
            assert node_id in dispatched, node_id

    async def test_resume_returns_node_results(
        self, real_registry, mock_token_manager, mock_audit
    ) -> None:
        dispatched: list[str] = []
        orch = _make_orchestrator(real_registry, mock_token_manager, mock_audit, dispatched)
        execution_id = str(uuid.uuid4())
        await orch.run_workflow(execution_id, _GENERIC_INTENT)
        resume_result = await orch.resume_workflow(execution_id, {})
        assert resume_result["execution_id"] == execution_id
        resumed_nodes = {r.node_id for r in resume_result["node_results"]}
        assert "evaluation" in resumed_nodes
