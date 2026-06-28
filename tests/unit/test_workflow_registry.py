"""Unit tests for cie.workflow — WorkflowRegistry, WorkflowStateMachine.

Test matrix:
- test_load_4_workflows              — all 4 workflow IDs present after load
- test_select_survival_ws001         — outcome_type=survival → clinical_analysis_survival
- test_select_meta_ws002             — objective=systematic_review → clinical_analysis_meta
- test_select_prediction_ws003       — objective=prediction_model → clinical_analysis_prediction
- test_select_default_ws004          — no special fields → clinical_analysis_standard
- test_requires_clarification_suspended — requires_human_clarification=True → error
- test_state_valid_transition        — DRAFT → VALIDATED succeeds
- test_state_invalid_transition      — COMPLETED → RUNNING raises StateTransitionError
- test_get_next_nodes                — depends_on chain resolved correctly
- test_get_node_existing             — get_node() returns correct WorkflowNodeDef
- test_get_node_missing              — get_node() on unknown id raises WorkflowError
- test_get_workflow_missing          — registry.get() on unknown id raises WorkflowError
- test_workflow_id_in_intent_ignored — workflow_id in intent_object is silently ignored
- test_ws001_priority_over_ws002     — outcome_type=survival + objective=systematic_review → WS-001 wins
- test_state_machine_terminal_to_archived — COMPLETED → ARCHIVED succeeds
- test_state_machine_archived_is_terminal — ARCHIVED → any raises StateTransitionError
- test_all_4_workflows_have_entrypoint   — entrypoint node exists in each workflow's nodes
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cie.core.exceptions import WorkflowError
from cie.workflow.registry import WorkflowDefinition, WorkflowRegistry
from cie.workflow.states import (
    StateTransitionError,
    WorkflowState,
    WorkflowStateMachine,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WORKFLOW_YAML = Path(__file__).parent.parent.parent / "spec" / "workflow.yaml"

_ALL_WORKFLOW_IDS = frozenset({
    "clinical_analysis_standard",
    "clinical_analysis_survival",
    "clinical_analysis_meta",
    "clinical_analysis_prediction",
})


@pytest.fixture(scope="module")
def registry() -> WorkflowRegistry:
    return WorkflowRegistry.load_from_yaml(_WORKFLOW_YAML)


@pytest.fixture(scope="module")
def sm() -> WorkflowStateMachine:
    return WorkflowStateMachine()


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------


class TestRegistryLoad:

    def test_load_4_workflows(self, registry: WorkflowRegistry) -> None:
        """All four workflow IDs must be present after loading the YAML."""
        loaded = set(registry.list_workflow_ids())
        assert _ALL_WORKFLOW_IDS == loaded

    def test_all_4_workflows_have_entrypoint(self, registry: WorkflowRegistry) -> None:
        """Each workflow's entrypoint must reference an existing node."""
        for wf_id in _ALL_WORKFLOW_IDS:
            defn: WorkflowDefinition = registry.get(wf_id)
            assert defn.entrypoint in defn.nodes, (
                f"{wf_id}: entrypoint '{defn.entrypoint}' not in nodes"
            )

    def test_get_workflow_missing(self, registry: WorkflowRegistry) -> None:
        """get() with an unknown workflow_id raises WorkflowError."""
        with pytest.raises(WorkflowError) as exc_info:
            registry.get("clinical_analysis_nonexistent")
        assert "WORKFLOW_NOT_FOUND" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Workflow selection — WS-001 to WS-004
# ---------------------------------------------------------------------------


class TestWorkflowSelection:

    def test_select_survival_ws001(self, registry: WorkflowRegistry) -> None:
        """outcome_type='survival' → clinical_analysis_survival (WS-001)."""
        intent = {"outcome_type": "survival", "objective": "between_group_comparison"}
        wf_id, rule_id, _ = registry.select_workflow(intent)
        assert wf_id == "clinical_analysis_survival"
        assert rule_id == "WS-001"

    def test_select_meta_ws002(self, registry: WorkflowRegistry) -> None:
        """objective='systematic_review' → clinical_analysis_meta (WS-002)."""
        intent = {"outcome_type": "continuous", "objective": "systematic_review"}
        wf_id, rule_id, _ = registry.select_workflow(intent)
        assert wf_id == "clinical_analysis_meta"
        assert rule_id == "WS-002"

    def test_select_prediction_ws003(self, registry: WorkflowRegistry) -> None:
        """objective='prediction_model' → clinical_analysis_prediction (WS-003)."""
        intent = {"outcome_type": "categorical_binary", "objective": "prediction_model"}
        wf_id, rule_id, _ = registry.select_workflow(intent)
        assert wf_id == "clinical_analysis_prediction"
        assert rule_id == "WS-003"

    def test_select_default_ws004(self, registry: WorkflowRegistry) -> None:
        """Generic intent with no special fields → clinical_analysis_standard (WS-004)."""
        intent = {"outcome_type": "continuous", "objective": "between_group_comparison"}
        wf_id, rule_id, _ = registry.select_workflow(intent)
        assert wf_id == "clinical_analysis_standard"
        assert rule_id == "WS-004"

    def test_select_default_ws004_empty_intent(self, registry: WorkflowRegistry) -> None:
        """Empty intent object → clinical_analysis_standard (WS-004 default)."""
        wf_id, rule_id, _ = registry.select_workflow({})
        assert wf_id == "clinical_analysis_standard"
        assert rule_id == "WS-004"

    def test_requires_clarification_suspended(self, registry: WorkflowRegistry) -> None:
        """requires_human_clarification=True raises WorkflowError before selection."""
        intent = {
            "outcome_type": "continuous",
            "requires_human_clarification": True,
        }
        with pytest.raises(WorkflowError) as exc_info:
            registry.select_workflow(intent)
        assert "WORKFLOW_SELECTION_SUSPENDED" in str(exc_info.value)

    def test_workflow_id_in_intent_ignored(self, registry: WorkflowRegistry) -> None:
        """workflow_id present in intent_object must be silently ignored (ADR-0001)."""
        intent = {
            "outcome_type": "continuous",
            "objective": "between_group_comparison",
            "workflow_id": "clinical_analysis_survival",  # must be ignored
        }
        wf_id, rule_id, _ = registry.select_workflow(intent)
        # outcome_type is not 'survival' so WS-001 must NOT match
        assert wf_id == "clinical_analysis_standard"
        assert rule_id == "WS-004"

    def test_ws001_priority_over_ws002(self, registry: WorkflowRegistry) -> None:
        """WS-001 wins when both outcome_type=survival and objective=systematic_review."""
        intent = {
            "outcome_type": "survival",
            "objective": "systematic_review",
        }
        wf_id, rule_id, _ = registry.select_workflow(intent)
        assert wf_id == "clinical_analysis_survival"
        assert rule_id == "WS-001"

    def test_justification_is_non_empty(self, registry: WorkflowRegistry) -> None:
        """select_workflow() must always return a non-empty justification string."""
        for intent in [
            {"outcome_type": "survival"},
            {"objective": "systematic_review"},
            {"objective": "prediction_model"},
            {"objective": "between_group_comparison"},
        ]:
            _, _, justification = registry.select_workflow(intent)
            assert isinstance(justification, str) and len(justification) > 0


# ---------------------------------------------------------------------------
# Node navigation
# ---------------------------------------------------------------------------


class TestNodeNavigation:

    def test_get_node_existing(self, registry: WorkflowRegistry) -> None:
        """get_node() returns the correct WorkflowNodeDef."""
        defn = registry.get("clinical_analysis_standard")
        node = defn.get_node("intake")
        assert node.node_id == "intake"
        assert node.agent_id == "planner"

    def test_get_node_missing(self, registry: WorkflowRegistry) -> None:
        """get_node() with unknown id raises WorkflowError."""
        defn = registry.get("clinical_analysis_standard")
        with pytest.raises(WorkflowError) as exc_info:
            defn.get_node("nonexistent_node")
        assert "WORKFLOW_NODE_NOT_FOUND" in str(exc_info.value)

    def test_get_next_nodes(self, registry: WorkflowRegistry) -> None:
        """get_next_nodes('intake') returns nodes that depend on 'intake'."""
        defn = registry.get("clinical_analysis_standard")
        next_nodes = defn.get_next_nodes("intake")
        # validate_dataset depends_on [intake]
        ids = {n.node_id for n in next_nodes}
        assert "validate_dataset" in ids

    def test_get_next_nodes_for_terminal(self, registry: WorkflowRegistry) -> None:
        """get_next_nodes for the completion node returns an empty list."""
        defn = registry.get("clinical_analysis_standard")
        # evaluation is the completion node; nothing depends on it
        next_nodes = defn.get_next_nodes("evaluation")
        assert next_nodes == []

    def test_get_next_nodes_multi_dependency(self, registry: WorkflowRegistry) -> None:
        """security_review in prediction workflow depends on TWO preceding nodes."""
        defn = registry.get("clinical_analysis_prediction")
        # security_review depends_on: [generate_standard_logistic, generate_firth_logistic]
        # So both generate_* nodes should unblock security_review
        next_from_standard = {n.node_id for n in defn.get_next_nodes("generate_standard_logistic")}
        next_from_firth = {n.node_id for n in defn.get_next_nodes("generate_firth_logistic")}
        assert "security_review" in next_from_standard
        assert "security_review" in next_from_firth


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class TestStateMachine:

    def test_state_valid_transition(self, sm: WorkflowStateMachine) -> None:
        """DRAFT → VALIDATED is a permitted transition."""
        result = sm.transition(
            WorkflowState.DRAFT,
            WorkflowState.VALIDATED,
            "intent_object_received_and_validated",
        )
        assert result == WorkflowState.VALIDATED

    def test_state_invalid_transition(self, sm: WorkflowStateMachine) -> None:
        """COMPLETED → RUNNING is not permitted; raises StateTransitionError."""
        with pytest.raises(StateTransitionError) as exc_info:
            sm.transition(
                WorkflowState.COMPLETED,
                WorkflowState.RUNNING,
                "illegal_restart_attempt",
            )
        err = exc_info.value
        assert err.from_state == WorkflowState.COMPLETED
        assert err.to_state == WorkflowState.RUNNING
        assert "STATE_TRANSITION_ERROR" in str(err)

    def test_state_machine_terminal_to_archived(self, sm: WorkflowStateMachine) -> None:
        """COMPLETED → ARCHIVED is the only permitted terminal transition."""
        result = sm.transition(
            WorkflowState.COMPLETED,
            WorkflowState.ARCHIVED,
            "archive_completed_workflow",
        )
        assert result == WorkflowState.ARCHIVED

    def test_state_machine_archived_is_terminal(self, sm: WorkflowStateMachine) -> None:
        """ARCHIVED → anything raises StateTransitionError (absolute terminal)."""
        for target in WorkflowState:
            if target == WorkflowState.ARCHIVED:
                continue
            with pytest.raises(StateTransitionError):
                sm.transition(WorkflowState.ARCHIVED, target, "illegal")

    def test_state_machine_failed_to_archived(self, sm: WorkflowStateMachine) -> None:
        """FAILED → ARCHIVED is permitted."""
        result = sm.transition(
            WorkflowState.FAILED,
            WorkflowState.ARCHIVED,
            "archive_failed_workflow",
        )
        assert result == WorkflowState.ARCHIVED

    def test_state_machine_running_to_waiting(self, sm: WorkflowStateMachine) -> None:
        """RUNNING → WAITING_FOR_HUMAN is permitted (approval node reached)."""
        result = sm.transition(
            WorkflowState.RUNNING,
            WorkflowState.WAITING_FOR_HUMAN,
            "approval_node_reached",
        )
        assert result == WorkflowState.WAITING_FOR_HUMAN

    def test_state_machine_waiting_to_running(self, sm: WorkflowStateMachine) -> None:
        """WAITING_FOR_HUMAN → RUNNING resumes after human resolves."""
        result = sm.transition(
            WorkflowState.WAITING_FOR_HUMAN,
            WorkflowState.RUNNING,
            "clarification_resolved",
        )
        assert result == WorkflowState.RUNNING

    def test_state_machine_draft_to_waiting(self, sm: WorkflowStateMachine) -> None:
        """DRAFT → WAITING_FOR_HUMAN is permitted (clarification before selection)."""
        result = sm.transition(
            WorkflowState.DRAFT,
            WorkflowState.WAITING_FOR_HUMAN,
            "requires_clarification",
        )
        assert result == WorkflowState.WAITING_FOR_HUMAN
