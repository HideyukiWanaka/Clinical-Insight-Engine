"""Unit tests for cie.workflow.states — WorkflowState, VALID_TRANSITIONS,
StateTransitionError, WorkflowStateMachine.

Test matrix:
- test_all_10_states_defined          — enum has exactly 10 members
- test_valid_transitions_cover_all_states — every state has an entry in map
- test_draft_can_transition_to_validated  — happy-path DRAFT → VALIDATED
- test_draft_can_transition_to_waiting   — clarification path DRAFT → WAITING
- test_validated_to_planned              — VALIDATED → PLANNED
- test_planned_to_running               — PLANNED → RUNNING
- test_running_to_completed             — RUNNING → COMPLETED
- test_running_to_waiting_for_human     — approval node reached
- test_running_to_retrying              — recoverable error
- test_retrying_to_running              — retry resumes
- test_completed_to_archived            — terminal archival
- test_failed_to_archived               — FAILED terminal archival
- test_cancelled_to_archived            — CANCELLED terminal archival
- test_completed_cannot_rerun           — COMPLETED → RUNNING raises
- test_archived_is_absolute_terminal    — ARCHIVED → * all raise
- test_error_carries_context            — StateTransitionError fields correct
- test_error_code_constant              — error_code is STATE_TRANSITION_ERROR
"""

from __future__ import annotations

import pytest

from cie.core.exceptions import WorkflowError
from cie.workflow.states import (
    VALID_TRANSITIONS,
    StateTransitionError,
    WorkflowState,
    WorkflowStateMachine,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sm() -> WorkflowStateMachine:
    return WorkflowStateMachine()


# ---------------------------------------------------------------------------
# Enum completeness
# ---------------------------------------------------------------------------


class TestWorkflowStateEnum:

    def test_all_10_states_defined(self) -> None:
        """spec/workflow.yaml lists exactly 10 states."""
        names = {s.value for s in WorkflowState}
        assert names == {
            "draft", "validated", "planned", "running",
            "waiting_for_human", "retrying",
            "completed", "failed", "cancelled", "archived",
        }

    def test_valid_transitions_cover_all_states(self) -> None:
        """Every WorkflowState must have an entry in VALID_TRANSITIONS."""
        for state in WorkflowState:
            assert state in VALID_TRANSITIONS, f"Missing entry for {state!r}"

    def test_terminal_states_only_allow_archived(self) -> None:
        """COMPLETED, FAILED, CANCELLED may only transition to ARCHIVED."""
        for terminal in (WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED):
            assert VALID_TRANSITIONS[terminal] == {WorkflowState.ARCHIVED}

    def test_archived_has_no_outgoing_transitions(self) -> None:
        """ARCHIVED is an absolute terminal — no outgoing transitions."""
        assert VALID_TRANSITIONS[WorkflowState.ARCHIVED] == set()


# ---------------------------------------------------------------------------
# Valid transitions (happy paths)
# ---------------------------------------------------------------------------


class TestValidTransitions:

    def test_draft_can_transition_to_validated(self, sm: WorkflowStateMachine) -> None:
        result = sm.transition(WorkflowState.DRAFT, WorkflowState.VALIDATED,
                               "intent_received")
        assert result == WorkflowState.VALIDATED

    def test_draft_can_transition_to_waiting(self, sm: WorkflowStateMachine) -> None:
        result = sm.transition(WorkflowState.DRAFT, WorkflowState.WAITING_FOR_HUMAN,
                               "clarification_needed")
        assert result == WorkflowState.WAITING_FOR_HUMAN

    def test_draft_can_transition_to_failed(self, sm: WorkflowStateMachine) -> None:
        result = sm.transition(WorkflowState.DRAFT, WorkflowState.FAILED, "init_error")
        assert result == WorkflowState.FAILED

    def test_validated_to_planned(self, sm: WorkflowStateMachine) -> None:
        result = sm.transition(WorkflowState.VALIDATED, WorkflowState.PLANNED, "dag_loaded")
        assert result == WorkflowState.PLANNED

    def test_planned_to_running(self, sm: WorkflowStateMachine) -> None:
        result = sm.transition(WorkflowState.PLANNED, WorkflowState.RUNNING, "dispatch_started")
        assert result == WorkflowState.RUNNING

    def test_running_to_completed(self, sm: WorkflowStateMachine) -> None:
        result = sm.transition(WorkflowState.RUNNING, WorkflowState.COMPLETED, "all_nodes_done")
        assert result == WorkflowState.COMPLETED

    def test_running_to_waiting_for_human(self, sm: WorkflowStateMachine) -> None:
        result = sm.transition(WorkflowState.RUNNING, WorkflowState.WAITING_FOR_HUMAN,
                               "approval_node_reached")
        assert result == WorkflowState.WAITING_FOR_HUMAN

    def test_running_to_retrying(self, sm: WorkflowStateMachine) -> None:
        result = sm.transition(WorkflowState.RUNNING, WorkflowState.RETRYING,
                               "recoverable_error")
        assert result == WorkflowState.RETRYING

    def test_retrying_to_running(self, sm: WorkflowStateMachine) -> None:
        result = sm.transition(WorkflowState.RETRYING, WorkflowState.RUNNING,
                               "retry_attempt")
        assert result == WorkflowState.RUNNING

    def test_waiting_for_human_to_running(self, sm: WorkflowStateMachine) -> None:
        result = sm.transition(WorkflowState.WAITING_FOR_HUMAN, WorkflowState.RUNNING,
                               "human_resolved")
        assert result == WorkflowState.RUNNING

    def test_completed_to_archived(self, sm: WorkflowStateMachine) -> None:
        result = sm.transition(WorkflowState.COMPLETED, WorkflowState.ARCHIVED, "archive")
        assert result == WorkflowState.ARCHIVED

    def test_failed_to_archived(self, sm: WorkflowStateMachine) -> None:
        result = sm.transition(WorkflowState.FAILED, WorkflowState.ARCHIVED, "archive")
        assert result == WorkflowState.ARCHIVED

    def test_cancelled_to_archived(self, sm: WorkflowStateMachine) -> None:
        result = sm.transition(WorkflowState.CANCELLED, WorkflowState.ARCHIVED, "archive")
        assert result == WorkflowState.ARCHIVED


# ---------------------------------------------------------------------------
# Invalid transitions (error paths)
# ---------------------------------------------------------------------------


class TestInvalidTransitions:

    def test_completed_cannot_rerun(self, sm: WorkflowStateMachine) -> None:
        """COMPLETED → RUNNING must raise StateTransitionError."""
        with pytest.raises(StateTransitionError):
            sm.transition(WorkflowState.COMPLETED, WorkflowState.RUNNING,
                          "illegal_restart")

    def test_failed_cannot_rerun(self, sm: WorkflowStateMachine) -> None:
        with pytest.raises(StateTransitionError):
            sm.transition(WorkflowState.FAILED, WorkflowState.RUNNING, "illegal")

    def test_archived_is_absolute_terminal(self, sm: WorkflowStateMachine) -> None:
        """ARCHIVED → any state must raise StateTransitionError."""
        for target in WorkflowState:
            if target == WorkflowState.ARCHIVED:
                continue
            with pytest.raises(StateTransitionError):
                sm.transition(WorkflowState.ARCHIVED, target, "illegal")

    def test_completed_cannot_go_to_failed(self, sm: WorkflowStateMachine) -> None:
        with pytest.raises(StateTransitionError):
            sm.transition(WorkflowState.COMPLETED, WorkflowState.FAILED, "illegal")

    def test_draft_cannot_jump_to_completed(self, sm: WorkflowStateMachine) -> None:
        with pytest.raises(StateTransitionError):
            sm.transition(WorkflowState.DRAFT, WorkflowState.COMPLETED, "illegal_skip")


# ---------------------------------------------------------------------------
# StateTransitionError contract
# ---------------------------------------------------------------------------


class TestStateTransitionError:

    def test_error_carries_from_to_states(self, sm: WorkflowStateMachine) -> None:
        """StateTransitionError must record from_state and to_state."""
        with pytest.raises(StateTransitionError) as exc_info:
            sm.transition(
                WorkflowState.COMPLETED,
                WorkflowState.RUNNING,
                "test_trigger",
            )
        err = exc_info.value
        assert err.from_state == WorkflowState.COMPLETED
        assert err.to_state == WorkflowState.RUNNING
        assert err.trigger_event == "test_trigger"

    def test_error_is_workflow_error_subclass(self, sm: WorkflowStateMachine) -> None:
        """StateTransitionError must be a subclass of WorkflowError."""
        with pytest.raises(WorkflowError):
            sm.transition(WorkflowState.COMPLETED, WorkflowState.RUNNING, "t")

    def test_error_code_constant(self, sm: WorkflowStateMachine) -> None:
        """error_code must be 'STATE_TRANSITION_ERROR'."""
        with pytest.raises(StateTransitionError) as exc_info:
            sm.transition(WorkflowState.COMPLETED, WorkflowState.RUNNING, "t")
        assert exc_info.value.error_code == "STATE_TRANSITION_ERROR"

    def test_error_message_contains_state_names(self, sm: WorkflowStateMachine) -> None:
        """Error string must mention both states."""
        with pytest.raises(StateTransitionError) as exc_info:
            sm.transition(WorkflowState.COMPLETED, WorkflowState.RUNNING, "t")
        msg = str(exc_info.value)
        assert "completed" in msg
        assert "running" in msg

    def test_optional_workflow_id_in_error(self) -> None:
        """workflow_id and execution_id are included in context when provided."""
        err = StateTransitionError(
            WorkflowState.COMPLETED,
            WorkflowState.RUNNING,
            "t",
            workflow_id="wf_123",
            execution_id="exec_abc",
        )
        assert err.workflow_id == "wf_123"
        assert err.execution_id == "exec_abc"
