"""CIE Platform — Workflow State Machine.

Defines the ten workflow states (spec/workflow.yaml), the valid transition
map (orchestrator.yaml state_machine), and the WorkflowStateMachine helper
that enforces those transitions.

Rules enforced here:
  - Only transitions listed in VALID_TRANSITIONS are permitted.
  - COMPLETED, FAILED, and CANCELLED are terminal: only ARCHIVED is reachable.
  - ARCHIVED has no outgoing transitions.
"""

from __future__ import annotations

from enum import Enum

from cie.core.exceptions import WorkflowError


class WorkflowState(str, Enum):
    """All valid workflow lifecycle states from spec/workflow.yaml."""

    DRAFT = "draft"
    VALIDATED = "validated"
    PLANNED = "planned"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


# ---------------------------------------------------------------------------
# Valid transition map (derived from orchestrator.yaml state_machine +
# spec/workflow.yaml lifecycle semantics)
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    # DRAFT — initial state; transitions after intent_object received
    WorkflowState.DRAFT: {
        WorkflowState.VALIDATED,
        WorkflowState.WAITING_FOR_HUMAN,  # clarification required before selection
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    # VALIDATED — workflow selected; planning in progress
    WorkflowState.VALIDATED: {
        WorkflowState.PLANNED,
        WorkflowState.WAITING_FOR_HUMAN,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    # PLANNED — DAG loaded; ready to run
    WorkflowState.PLANNED: {
        WorkflowState.RUNNING,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    # RUNNING — dispatch loop active
    WorkflowState.RUNNING: {
        WorkflowState.WAITING_FOR_HUMAN,
        WorkflowState.RETRYING,
        WorkflowState.COMPLETED,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    # WAITING_FOR_HUMAN — suspended at approval node or clarification
    WorkflowState.WAITING_FOR_HUMAN: {
        WorkflowState.RUNNING,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    # RETRYING — exponential back-off in progress
    WorkflowState.RETRYING: {
        WorkflowState.RUNNING,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    },
    # Terminal states — only archival is permitted
    WorkflowState.COMPLETED: {WorkflowState.ARCHIVED},
    WorkflowState.FAILED: {WorkflowState.ARCHIVED},
    WorkflowState.CANCELLED: {WorkflowState.ARCHIVED},
    # ARCHIVED — absolute terminal; no outgoing transitions
    WorkflowState.ARCHIVED: set(),
}


class StateTransitionError(WorkflowError):
    """Raised when a requested state transition is not in VALID_TRANSITIONS.

    Attributes:
        from_state: The current workflow state.
        to_state: The requested (invalid) target state.
        trigger_event: The event that triggered the attempted transition.
    """

    error_code: str = "STATE_TRANSITION_ERROR"

    def __init__(
        self,
        from_state: WorkflowState,
        to_state: WorkflowState,
        trigger_event: str,
        *,
        workflow_id: str | None = None,
        execution_id: str | None = None,
    ) -> None:
        message = (
            f"STATE_TRANSITION_ERROR: transition {from_state.value!r} → "
            f"{to_state.value!r} is not permitted "
            f"(trigger_event={trigger_event!r})."
        )
        super().__init__(message, workflow_id=workflow_id, execution_id=execution_id)
        self.from_state = from_state
        self.to_state = to_state
        self.trigger_event = trigger_event


class WorkflowStateMachine:
    """Enforces valid state transitions for workflow instances.

    Usage::

        sm = WorkflowStateMachine()
        new_state = sm.transition(
            current=WorkflowState.DRAFT,
            target=WorkflowState.VALIDATED,
            trigger_event="intent_object_received_and_validated",
        )
    """

    def transition(
        self,
        current: WorkflowState,
        target: WorkflowState,
        trigger_event: str,
        *,
        workflow_id: str | None = None,
        execution_id: str | None = None,
    ) -> WorkflowState:
        """Attempt a state transition and return the new state if valid.

        Args:
            current: The current workflow state.
            target: The desired next state.
            trigger_event: Descriptive name of the event requesting the transition.
            workflow_id: Optional workflow identifier (included in error context).
            execution_id: Optional execution identifier (included in error context).

        Returns:
            ``target`` if the transition is permitted.

        Raises:
            StateTransitionError: If ``target`` is not in
                ``VALID_TRANSITIONS[current]``.
        """
        allowed = VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise StateTransitionError(
                from_state=current,
                to_state=target,
                trigger_event=trigger_event,
                workflow_id=workflow_id,
                execution_id=execution_id,
            )
        return target
