"""Unit tests for cie.workflow.orchestrator.Orchestrator.

All agents are mocked. Tests verify the Orchestrator's coordination logic,
not the agents' domain behaviour.

Test matrix:
- test_workflow_selection_ws004_default    — standard workflow selected for generic intent
- test_workflow_id_not_set_by_planner      — workflow_id in intent_object is ignored (ADR-0001)
- test_token_revoked_after_node            — token.revoke() called even on success
- test_token_revoked_on_agent_failure      — revocation still happens on agent error
- test_recoverable_error_retries           — runtime_timeout triggers up to 3 retries
- test_non_recoverable_aborts              — schema_validation_failure → immediate FAILED
- test_human_approval_pauses_loop          — approval node → WAITING_FOR_HUMAN state
- test_all_nodes_audited                   — audit.write() called for every node
- test_workflow_selection_ws001_survival   — outcome_type=survival → survival workflow
- test_final_state_completed_on_success    — happy path returns COMPLETED
- test_requires_clarification_suspends     — requires_human_clarification → WAITING_FOR_HUMAN
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cie.agents.base import AgentInput, AgentOutput
from cie.core.audit import AuditService
from cie.core.exceptions import AgentError
from cie.security.capability_token import (
    CapabilityScope,
    CapabilityToken,
    CapabilityTokenManager,
)
from cie.security.context_guard import ContextGuard
from cie.security.policy_engine import PolicyEngine
from cie.workflow.orchestrator import Orchestrator
from cie.workflow.registry import WorkflowDefinition, WorkflowNodeDef, WorkflowRegistry
from cie.workflow.states import WorkflowState, WorkflowStateMachine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WORKFLOW_YAML = Path(__file__).parent.parent.parent / "spec" / "workflow.yaml"

_GENERIC_INTENT = {
    "objective": "between_group_comparison",
    "outcome_type": "continuous",
    "requires_human_clarification": False,
}

_SURVIVAL_INTENT = {
    "objective": "between_group_comparison",
    "outcome_type": "survival",
    "requires_human_clarification": False,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_registry() -> WorkflowRegistry:
    return WorkflowRegistry.load_from_yaml(_WORKFLOW_YAML)


@pytest.fixture(scope="module")
def real_sm() -> WorkflowStateMachine:
    return WorkflowStateMachine()


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

    def _revoke(token: CapabilityToken) -> CapabilityToken:
        from dataclasses import replace
        return replace(token, revoked=True, revoked_at=datetime.now(timezone.utc))

    mgr.issue.side_effect = _issue
    mgr.revoke.side_effect = _revoke
    return mgr


@pytest.fixture
def mock_context_guard() -> ContextGuard:
    cg = MagicMock(spec=ContextGuard)
    cg.sanitize_context_payload = AsyncMock(side_effect=lambda p: p)
    return cg


@pytest.fixture
def mock_policy_engine() -> PolicyEngine:
    pe = MagicMock(spec=PolicyEngine)
    pe.enforce_multi = AsyncMock()
    return pe


def _make_success_agent(output_override: dict | None = None) -> MagicMock:
    """Return a mock agent that always succeeds."""
    agent = MagicMock()
    agent.agent_id = "mock_agent"
    agent.required_scopes = [CapabilityScope.AUDIT_WRITE_ENTRY]
    agent.input_schema_ref = "cie://schemas/task.schema.json"
    agent.output_schema_ref = "cie://schemas/task.schema.json"

    async def _run(_agent_input: AgentInput) -> AgentOutput:
        return AgentOutput(
            execution_id=_agent_input.execution_id,
            agent_id="mock_agent",
            status="success",
            output_payload=output_override or {"ok": True},
            output_schema_ref="cie://schemas/task.schema.json",
        )

    agent.run = _run
    return agent


def _make_failing_agent(error_code: str) -> MagicMock:
    """Return a mock agent that raises AgentError with the given code."""
    agent = MagicMock()
    agent.agent_id = "mock_agent"
    agent.required_scopes = []

    async def _run(_agent_input: AgentInput) -> AgentOutput:
        raise AgentError(f"{error_code}: test error", agent_id="mock_agent")

    agent.run = _run
    return agent


# ---------------------------------------------------------------------------
# A minimal two-node workflow with NO approval gates (for COMPLETED tests)
# ---------------------------------------------------------------------------

_SIMPLE_WORKFLOW = WorkflowDefinition(
    workflow_id="simple_test",
    version="1.0",
    category="test",
    entrypoint="step1",
    nodes={
        "step1": WorkflowNodeDef(
            node_id="step1",
            node_type="task",
            agent_id="planner",
            depends_on=[],
            outputs=["result1"],
        ),
        "step2": WorkflowNodeDef(
            node_id="step2",
            node_type="task",
            agent_id="statistics",
            depends_on=["step1"],
            outputs=["result2"],
        ),
    },
)


def _make_simple_registry() -> MagicMock:
    """Registry that returns a two-node no-approval workflow."""
    reg = MagicMock(spec=WorkflowRegistry)
    reg.select_workflow.return_value = ("simple_test", "WS-004", "test justification")
    reg.get.return_value = _SIMPLE_WORKFLOW
    return reg


def _make_orchestrator(
    registry: WorkflowRegistry,
    sm: WorkflowStateMachine,
    token_manager: CapabilityTokenManager,
    audit: AuditService,
    agent_override: Any | None = None,
) -> Orchestrator:
    """Build an Orchestrator wired with one catch-all mock agent."""
    success_agent = agent_override or _make_success_agent()
    # Map every agent_id that appears in the workflow to the same mock
    agent_registry = {
        "planner": success_agent,
        "data_quality": success_agent,
        "statistics": success_agent,
        "visualization": success_agent,
        "reporting": success_agent,
        "reviewer": success_agent,
        "security": success_agent,
        "runtime": success_agent,
        "evaluation": success_agent,
    }
    return Orchestrator(
        workflow_registry=registry,
        state_machine=sm,
        token_manager=token_manager,
        policy_engine=MagicMock(),
        context_guard=MagicMock(),
        audit_service=audit,
        agent_registry=agent_registry,
    )


# ---------------------------------------------------------------------------
# Workflow selection
# ---------------------------------------------------------------------------


class TestWorkflowSelection:

    async def test_workflow_selection_ws004_default(
        self,
        real_registry: WorkflowRegistry,
        real_sm: WorkflowStateMachine,
        mock_token_manager: CapabilityTokenManager,
        mock_audit: AuditService,
    ) -> None:
        """Generic intent → clinical_analysis_standard (WS-004)."""
        orch = _make_orchestrator(real_registry, real_sm, mock_token_manager, mock_audit)
        result = await orch.run_workflow(str(uuid.uuid4()), _GENERIC_INTENT)
        assert result["workflow_id_selected"] == "clinical_analysis_standard"
        assert result["rule_id"] == "WS-004"

    async def test_workflow_selection_ws001_survival(
        self,
        real_registry: WorkflowRegistry,
        real_sm: WorkflowStateMachine,
        mock_token_manager: CapabilityTokenManager,
        mock_audit: AuditService,
    ) -> None:
        """outcome_type=survival → clinical_analysis_survival (WS-001)."""
        orch = _make_orchestrator(real_registry, real_sm, mock_token_manager, mock_audit)
        result = await orch.run_workflow(str(uuid.uuid4()), _SURVIVAL_INTENT)
        assert result["workflow_id_selected"] == "clinical_analysis_survival"
        assert result["rule_id"] == "WS-001"

    async def test_workflow_id_not_set_by_planner(
        self,
        real_registry: WorkflowRegistry,
        real_sm: WorkflowStateMachine,
        mock_token_manager: CapabilityTokenManager,
        mock_audit: AuditService,
    ) -> None:
        """workflow_id in intent_object is silently ignored (ADR-0001)."""
        intent_with_wf_id = {
            **_GENERIC_INTENT,
            "workflow_id": "clinical_analysis_survival",  # should be ignored
        }
        orch = _make_orchestrator(real_registry, real_sm, mock_token_manager, mock_audit)
        result = await orch.run_workflow(str(uuid.uuid4()), intent_with_wf_id)
        # outcome_type is 'continuous', not 'survival' → WS-004 must win
        assert result["workflow_id_selected"] == "clinical_analysis_standard"

    async def test_requires_clarification_suspends(
        self,
        real_registry: WorkflowRegistry,
        real_sm: WorkflowStateMachine,
        mock_token_manager: CapabilityTokenManager,
        mock_audit: AuditService,
    ) -> None:
        """requires_human_clarification=True → WAITING_FOR_HUMAN before selection."""
        intent = {**_GENERIC_INTENT, "requires_human_clarification": True}
        orch = _make_orchestrator(real_registry, real_sm, mock_token_manager, mock_audit)
        result = await orch.run_workflow(str(uuid.uuid4()), intent)
        assert result["final_state"] == WorkflowState.WAITING_FOR_HUMAN.value
        assert result["workflow_id_selected"] is None


# ---------------------------------------------------------------------------
# Token lifecycle (step 7: try/finally)
# ---------------------------------------------------------------------------


class TestTokenLifecycle:

    async def test_token_revoked_after_node(
        self,
        real_registry: WorkflowRegistry,
        real_sm: WorkflowStateMachine,
        mock_token_manager: CapabilityTokenManager,
        mock_audit: AuditService,
    ) -> None:
        """token_manager.revoke() must be called for every dispatched node."""
        orch = _make_orchestrator(real_registry, real_sm, mock_token_manager, mock_audit)
        await orch.run_workflow(str(uuid.uuid4()), _GENERIC_INTENT)
        # Each node causes one issue() + one revoke()
        issue_count = mock_token_manager.issue.call_count
        revoke_count = mock_token_manager.revoke.call_count
        assert issue_count > 0
        assert revoke_count == issue_count

    async def test_token_revoked_on_agent_failure(
        self,
        real_registry: WorkflowRegistry,
        real_sm: WorkflowStateMachine,
        mock_token_manager: CapabilityTokenManager,
        mock_audit: AuditService,
    ) -> None:
        """Token must be revoked even when the agent raises an exception."""
        failing_agent = _make_failing_agent("schema_validation_failure")
        orch = _make_orchestrator(
            real_registry, real_sm, mock_token_manager, mock_audit, agent_override=failing_agent
        )
        await orch.run_workflow(str(uuid.uuid4()), _GENERIC_INTENT)
        # At least one revoke must have been called
        assert mock_token_manager.revoke.call_count >= 1
        # revoke must equal issue even on failure
        assert mock_token_manager.revoke.call_count == mock_token_manager.issue.call_count


# ---------------------------------------------------------------------------
# Resilience routing
# ---------------------------------------------------------------------------


class TestResilienceRouting:

    async def test_recoverable_error_retries(
        self,
        real_registry: WorkflowRegistry,
        real_sm: WorkflowStateMachine,
        mock_token_manager: CapabilityTokenManager,
        mock_audit: AuditService,
    ) -> None:
        """runtime_timeout triggers up to MAX_RETRY_ATTEMPTS retries."""
        call_count = 0

        async def _run(_agent_input: AgentInput) -> AgentOutput:
            nonlocal call_count
            call_count += 1
            raise AgentError("runtime_timeout: test", agent_id="mock_agent")

        agent = MagicMock()
        agent.agent_id = "mock_agent"
        agent.required_scopes = []
        agent.run = _run

        with patch("cie.workflow.orchestrator._RETRY_BASE_DELAY_SECONDS", 0):
            orch = _make_orchestrator(
                real_registry, real_sm, mock_token_manager, mock_audit, agent_override=agent
            )
            result = await orch.run_workflow(str(uuid.uuid4()), _GENERIC_INTENT)

        # MAX_RETRY_ATTEMPTS=3 means 1 original + 3 retries = 4 total attempts
        assert call_count == Orchestrator.MAX_RETRY_ATTEMPTS + 1
        assert result["final_state"] == WorkflowState.FAILED.value

    async def test_non_recoverable_aborts(
        self,
        real_registry: WorkflowRegistry,
        real_sm: WorkflowStateMachine,
        mock_token_manager: CapabilityTokenManager,
        mock_audit: AuditService,
    ) -> None:
        """schema_validation_failure triggers immediate FAILED (no retry)."""
        call_count = 0

        async def _run(_agent_input: AgentInput) -> AgentOutput:
            nonlocal call_count
            call_count += 1
            raise AgentError("schema_validation_failure: invalid", agent_id="mock_agent")

        agent = MagicMock()
        agent.agent_id = "mock_agent"
        agent.required_scopes = []
        agent.run = _run

        orch = _make_orchestrator(
            real_registry, real_sm, mock_token_manager, mock_audit, agent_override=agent
        )
        result = await orch.run_workflow(str(uuid.uuid4()), _GENERIC_INTENT)

        # Non-recoverable: exactly 1 attempt, no retry
        assert call_count == 1
        assert result["final_state"] == WorkflowState.FAILED.value

    async def test_final_state_completed_on_success(
        self,
        real_sm: WorkflowStateMachine,
        mock_token_manager: CapabilityTokenManager,
        mock_audit: AuditService,
    ) -> None:
        """All nodes succeed with no approval gates → final_state='completed'."""
        simple_registry = _make_simple_registry()
        orch = _make_orchestrator(simple_registry, real_sm, mock_token_manager, mock_audit)
        result = await orch.run_workflow(str(uuid.uuid4()), _GENERIC_INTENT)
        assert result["final_state"] == WorkflowState.COMPLETED.value


# ---------------------------------------------------------------------------
# Human approval gate
# ---------------------------------------------------------------------------


class TestHumanApproval:

    async def test_human_approval_pauses_loop(
        self,
        real_registry: WorkflowRegistry,
        real_sm: WorkflowStateMachine,
        mock_token_manager: CapabilityTokenManager,
        mock_audit: AuditService,
    ) -> None:
        """approval node type triggers WAITING_FOR_HUMAN state."""
        # The standard workflow has a 'security_review' node with type=approval.
        # All non-approval nodes succeed; the approval node suspends.
        orch = _make_orchestrator(real_registry, real_sm, mock_token_manager, mock_audit)
        result = await orch.run_workflow(str(uuid.uuid4()), _GENERIC_INTENT)
        # Because security_review is an approval node, loop should pause
        assert result["final_state"] == WorkflowState.WAITING_FOR_HUMAN.value

    async def test_human_approval_node_in_results(
        self,
        real_registry: WorkflowRegistry,
        real_sm: WorkflowStateMachine,
        mock_token_manager: CapabilityTokenManager,
        mock_audit: AuditService,
    ) -> None:
        """A TaskDispatchResult with status='waiting_for_human' must be in node_results."""
        orch = _make_orchestrator(real_registry, real_sm, mock_token_manager, mock_audit)
        result = await orch.run_workflow(str(uuid.uuid4()), _GENERIC_INTENT)
        waiting = [r for r in result["node_results"] if r.status == "waiting_for_human"]
        assert len(waiting) >= 1


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


class TestAuditLogging:

    async def test_all_nodes_audited(
        self,
        real_registry: WorkflowRegistry,
        real_sm: WorkflowStateMachine,
        mock_token_manager: CapabilityTokenManager,
        mock_audit: AuditService,
    ) -> None:
        """audit.write() must be called at least once per dispatched node."""
        orch = _make_orchestrator(real_registry, real_sm, mock_token_manager, mock_audit)
        result = await orch.run_workflow(str(uuid.uuid4()), _GENERIC_INTENT)
        # At minimum: WORKFLOW_SELECTED + one entry per node result
        node_count = len(result["node_results"])
        assert mock_audit.write.call_count >= node_count + 1

    async def test_workflow_selection_audited(
        self,
        real_registry: WorkflowRegistry,
        real_sm: WorkflowStateMachine,
        mock_token_manager: CapabilityTokenManager,
        mock_audit: AuditService,
    ) -> None:
        """WORKFLOW_SELECTED must appear in audit calls."""
        orch = _make_orchestrator(real_registry, real_sm, mock_token_manager, mock_audit)
        await orch.run_workflow(str(uuid.uuid4()), _GENERIC_INTENT)

        actions = [
            call.args[0].action
            for call in mock_audit.write.call_args_list
            if call.args
        ]
        assert "WORKFLOW_SELECTED" in actions
