"""CIE Platform — Orchestrator.

Implements the full workflow lifecycle: ADR-0001 workflow selection, DAG
dispatch loop (orchestrator.yaml 9 steps), retry/resilience routing, and
capability token lifecycle management.

Key invariants (orchestrator.yaml strictly_forbidden):
  - Orchestrator never mutates intent_object (reads it only).
  - DAG nodes are never added/removed at runtime (ADR-0001 Principle 1).
  - Step 7 (token revocation) executes unconditionally via try/finally.
  - Non-recoverable failures trigger IMMEDIATE_ABORT.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.audit import AuditEvent, AuditEventSeverity, AuditService
from cie.core.exceptions import AgentError, WorkflowError
from cie.security.capability_token import CapabilityScope, CapabilityToken, CapabilityTokenManager
from cie.security.context_guard import ContextGuard
from cie.security.policy_engine import PolicyEngine
from cie.workflow.registry import WorkflowDefinition, WorkflowNodeDef, WorkflowRegistry
from cie.workflow.states import WorkflowState, WorkflowStateMachine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (spec/workflow.yaml failure_policy)
# ---------------------------------------------------------------------------

MAX_RETRY_ATTEMPTS: int = 3

RECOVERABLE_ERRORS: frozenset[str] = frozenset({
    "runtime_timeout",
    "temporary_io_failure",
    "runtime_busy",
})

NON_RECOVERABLE_ERRORS: frozenset[str] = frozenset({
    "schema_validation_failure",
    "permission_denied",
    "security_violation",
    "corrupted_dataset",
})

_RETRY_BASE_DELAY_SECONDS: float = 1.0  # exponential base; tests may patch


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class TaskDispatchResult:
    """Record of a single DAG node execution attempt.

    Attributes:
        node_id: DAG node that was executed.
        agent_id: Agent responsible for the node.
        status: Terminal status of this execution attempt.
        output_payload: Agent's output on success; empty dict on failure.
        error_code: Machine-readable failure code, or ``None`` on success.
        retry_count: Number of retry attempts consumed (0 on first success).
    """

    node_id: str
    agent_id: str
    status: Literal["completed", "failed", "waiting_for_human"]
    output_payload: dict
    error_code: str | None = None
    retry_count: int = 0


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """Central engine: workflow selection → DAG dispatch → state management.

    Args:
        workflow_registry: Supplies static ``WorkflowDefinition`` objects.
        state_machine: Enforces valid state transitions.
        token_manager: Issues and revokes ephemeral capability tokens.
        policy_engine: Enforces scope checks (passed-through to agents via token).
        context_guard: Sanitizes context payloads before agent dispatch.
        audit_service: Immutable audit log writer.
        agent_registry: Maps ``agent_id`` strings to ``BaseAgent`` instances.
    """

    MAX_RETRY_ATTEMPTS: int = MAX_RETRY_ATTEMPTS
    RECOVERABLE_ERRORS: frozenset[str] = RECOVERABLE_ERRORS

    def __init__(
        self,
        workflow_registry: WorkflowRegistry,
        state_machine: WorkflowStateMachine,
        token_manager: CapabilityTokenManager,
        policy_engine: PolicyEngine,
        context_guard: ContextGuard,
        audit_service: AuditService,
        agent_registry: dict[str, BaseAgent],
    ) -> None:
        self._registry = workflow_registry
        self._state_machine = state_machine
        self._token_manager = token_manager
        self._policy_engine = policy_engine
        self._context_guard = context_guard
        self._audit = audit_service
        self._agent_registry = agent_registry

        # In-memory checkpoint for suspended workflows keyed by execution_id
        self._suspended: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_workflow(
        self,
        execution_id: str,
        intent_object: dict,
    ) -> dict:
        """Select a workflow and execute it end-to-end.

        ADR-0001 compliance:
          - ``intent_object`` is never mutated.
          - ``workflow_id`` is resolved here via deterministic selection rules.

        Args:
            execution_id: Unique identifier for this execution run.
            intent_object: Produced by PlannerAgent; must NOT contain
                ``workflow_id`` (ignored if present — ADR-0001).

        Returns:
            A result dict containing at minimum:
            ``{"execution_id", "workflow_id_selected", "rule_id",
               "justification", "final_state", "node_results"}``.
        """
        current_state = WorkflowState.DRAFT

        # Step 1 — ADR-0001: select workflow_id (Orchestrator-owned decision)
        try:
            workflow_id, rule_id, justification = self._registry.select_workflow(
                intent_object
            )
        except WorkflowError as exc:
            # requires_human_clarification=True → suspend before selection
            current_state = self._state_machine.transition(
                current_state,
                WorkflowState.WAITING_FOR_HUMAN,
                "requires_clarification_before_workflow_selection",
                execution_id=execution_id,
            )
            await self._write_audit(
                execution_id=execution_id,
                agent_id="orchestrator",
                action="WORKFLOW_SELECTION_SUSPENDED",
                status="suspended",
                payload={"reason": str(exc)},
            )
            return {
                "execution_id": execution_id,
                "workflow_id_selected": None,
                "rule_id": None,
                "justification": str(exc),
                "final_state": current_state.value,
                "node_results": [],
            }

        # Step 2 — record selection to audit (orchestrator.yaml audit_requirement)
        await self._write_audit(
            execution_id=execution_id,
            agent_id="orchestrator",
            action="WORKFLOW_SELECTED",
            status="success",
            payload={
                "workflow_id": workflow_id,
                "rule_id": rule_id,
                "justification": justification,
                "intent_object_snapshot": {
                    "objective": intent_object.get("objective"),
                    "outcome_type": intent_object.get("outcome_type"),
                },
            },
        )

        # Step 3 — DRAFT → VALIDATED
        current_state = self._state_machine.transition(
            current_state,
            WorkflowState.VALIDATED,
            "intent_object_received_and_validated",
            execution_id=execution_id,
        )

        # Step 4 — load workflow definition
        workflow_def = self._registry.get(workflow_id)

        # Step 5 — VALIDATED → PLANNED → RUNNING
        current_state = self._state_machine.transition(
            current_state,
            WorkflowState.PLANNED,
            "dag_loaded",
            execution_id=execution_id,
        )
        current_state = self._state_machine.transition(
            current_state,
            WorkflowState.RUNNING,
            "dispatch_loop_starting",
            execution_id=execution_id,
        )

        # Step 6 — execute the DAG
        initial_payload = {"intent_object": intent_object, "execution_id": execution_id}
        loop_result = await self._task_dispatch_loop(
            execution_id=execution_id,
            workflow_def=workflow_def,
            initial_payload=initial_payload,
            current_state=current_state,
        )

        return {
            "execution_id": execution_id,
            "workflow_id_selected": workflow_id,
            "rule_id": rule_id,
            "justification": justification,
            "final_state": loop_result["final_state"],
            "node_results": loop_result["node_results"],
        }

    async def resume_workflow(
        self,
        execution_id: str,
        human_decision: dict,
    ) -> None:
        """Resume a suspended workflow after human decision.

        Args:
            execution_id: The execution that is in WAITING_FOR_HUMAN state.
            human_decision: Structured decision payload from the human operator.
        """
        await self._write_audit(
            execution_id=execution_id,
            agent_id="orchestrator",
            action="HUMAN_DECISION_RECEIVED",
            status="success",
            payload={"human_decision": human_decision},
        )
        # In a full implementation this would reload the checkpoint from
        # persistent storage and re-enter _task_dispatch_loop.  The
        # in-memory checkpoint is sufficient for the current scope.
        checkpoint = self._suspended.pop(execution_id, None)
        if checkpoint is None:
            raise WorkflowError(
                f"RESUME_FAILED: no suspended checkpoint for execution_id={execution_id!r}",
                execution_id=execution_id,
            )
        # Merge human decision into context and continue from suspended node
        checkpoint["context"].update(human_decision)
        await self._task_dispatch_loop(
            execution_id=execution_id,
            workflow_def=checkpoint["workflow_def"],
            initial_payload=checkpoint["context"],
            current_state=WorkflowState.RUNNING,
            skip_nodes=checkpoint["completed_nodes"],
        )

    # ------------------------------------------------------------------
    # Task dispatch loop (orchestrator.yaml 9 steps)
    # ------------------------------------------------------------------

    async def _task_dispatch_loop(
        self,
        execution_id: str,
        workflow_def: WorkflowDefinition,
        initial_payload: dict,
        current_state: WorkflowState,
        skip_nodes: set[str] | None = None,
    ) -> dict:
        """Execute the DAG from the entrypoint to completion or halt.

        Implements orchestrator.yaml ``task_dispatch_loop`` steps 1–9.

        Args:
            execution_id: Execution context ID.
            workflow_def: Static workflow DAG definition.
            initial_payload: Context seed (intent_object + metadata).
            current_state: Current workflow state on entry.
            skip_nodes: Node IDs already completed (used by resume_workflow).

        Returns:
            Dict with ``"final_state"`` and ``"node_results"``.
        """
        accumulated_context: dict = dict(initial_payload)
        completed_nodes: set[str] = set(skip_nodes or set())
        node_results: list[TaskDispatchResult] = []

        # BFS queue: start from entrypoint
        ready_queue: list[str] = [workflow_def.entrypoint]

        while ready_queue:
            node_id = ready_queue.pop(0)

            # Skip already-completed nodes (e.g. after resume)
            if node_id in completed_nodes:
                continue

            node_def = workflow_def.get_node(node_id)

            # Step 1 — verify all dependencies are satisfied
            if not all(dep in completed_nodes for dep in node_def.depends_on):
                # Not ready yet; re-queue when deps complete
                ready_queue.append(node_id)
                continue

            # Step 2 — verify preconditions (node_type sanity)
            agent_id = node_def.agent_id
            if not agent_id:
                completed_nodes.add(node_id)
                ready_queue.extend(self._find_ready(node_id, workflow_def, completed_nodes))
                continue

            # Steps 3–9: execute with retry
            result = await self._execute_node_with_retry(
                execution_id=execution_id,
                node_def=node_def,
                accumulated_context=accumulated_context,
            )
            node_results.append(result)

            if result.status == "waiting_for_human":
                # Persist checkpoint for resume_workflow
                self._suspended[execution_id] = {
                    "workflow_def": workflow_def,
                    "completed_nodes": set(completed_nodes),
                    "context": dict(accumulated_context),
                }
                current_state = self._state_machine.transition(
                    current_state,
                    WorkflowState.WAITING_FOR_HUMAN,
                    f"approval_node_reached:{node_id}",
                    execution_id=execution_id,
                )
                return {"final_state": current_state.value, "node_results": node_results}

            if result.status == "failed":
                current_state = self._state_machine.transition(
                    current_state,
                    WorkflowState.FAILED,
                    f"node_failed:{node_id}",
                    execution_id=execution_id,
                )
                return {"final_state": current_state.value, "node_results": node_results}

            # Step 9 — advance: mark complete, accumulate context, find next nodes
            completed_nodes.add(node_id)
            accumulated_context.update(result.output_payload)
            ready_queue.extend(self._find_ready(node_id, workflow_def, completed_nodes))

        # All nodes processed
        current_state = self._state_machine.transition(
            current_state,
            WorkflowState.COMPLETED,
            "all_nodes_completed",
            execution_id=execution_id,
        )
        await self._write_audit(
            execution_id=execution_id,
            agent_id="orchestrator",
            action="WORKFLOW_COMPLETED",
            status="success",
            payload={"completed_nodes": sorted(completed_nodes)},
        )
        return {"final_state": current_state.value, "node_results": node_results}

    # ------------------------------------------------------------------
    # Per-node execution with retry
    # ------------------------------------------------------------------

    async def _execute_node_with_retry(
        self,
        execution_id: str,
        node_def: WorkflowNodeDef,
        accumulated_context: dict,
    ) -> TaskDispatchResult:
        """Execute a single node with exponential back-off retry.

        Token revocation (step 7) always runs in a ``try/finally`` block
        regardless of success or failure (orchestrator.yaml step 7 constraint).

        Args:
            execution_id: Execution context.
            node_def: The node to execute.
            accumulated_context: Current accumulated payload from prior nodes.

        Returns:
            A ``TaskDispatchResult`` representing the final outcome.
        """
        # approval node type → WAITING_FOR_HUMAN without agent dispatch
        if node_def.node_type == "approval":
            await self._write_audit(
                execution_id=execution_id,
                agent_id=node_def.agent_id or "orchestrator",
                action=f"APPROVAL_NODE_REACHED:{node_def.node_id}",
                status="waiting_for_human",
                payload={"node_id": node_def.node_id, "node_type": node_def.node_type},
            )
            return TaskDispatchResult(
                node_id=node_def.node_id,
                agent_id=node_def.agent_id,
                status="waiting_for_human",
                output_payload={},
                error_code=None,
                retry_count=0,
            )

        agent = self._agent_registry.get(node_def.agent_id)
        if agent is None:
            # Agent not registered — treat as non-recoverable
            await self._write_audit(
                execution_id=execution_id,
                agent_id="orchestrator",
                action="AGENT_NOT_FOUND",
                status="failure",
                payload={"node_id": node_def.node_id, "agent_id": node_def.agent_id},
                severity=AuditEventSeverity.ERROR,
            )
            return TaskDispatchResult(
                node_id=node_def.node_id,
                agent_id=node_def.agent_id,
                status="failed",
                output_payload={},
                error_code="AGENT_NOT_FOUND",
                retry_count=0,
            )

        last_error_code: str | None = None
        for attempt in range(self.MAX_RETRY_ATTEMPTS + 1):

            # Step 3 — issue ephemeral capability token
            required_scopes = self._scopes_for_agent(node_def.agent_id)
            token: CapabilityToken = self._token_manager.issue(
                execution_id=execution_id,
                agent_id=node_def.agent_id,
                step_id=node_def.node_id,
                requested_scopes=required_scopes,
            )

            output: AgentOutput | None = None
            error_code: str | None = None

            try:
                # Step 4 — build isolated context payload
                context_payload = dict(accumulated_context)

                # Step 5 — dispatch to agent
                agent_input = AgentInput(
                    execution_id=execution_id,
                    node_id=node_def.node_id,
                    capability_token=token,
                    payload=context_payload,
                    input_schema_ref="cie://schemas/task.schema.json",
                )
                output = await agent.run(agent_input)

                # Step 6 — check output for human clarification
                if output.requires_human_clarification:
                    return TaskDispatchResult(
                        node_id=node_def.node_id,
                        agent_id=node_def.agent_id,
                        status="waiting_for_human",
                        output_payload=output.output_payload,
                        error_code=None,
                        retry_count=attempt,
                    )

                # Step 6 — check for agent-level failure
                if output.status == "failed":
                    error_code = output.error_code or "AGENT_FAILED"

            except (AgentError, Exception) as exc:
                error_code = _extract_error_code(exc)

            finally:
                # Step 7 — ALWAYS revoke token (try/finally)
                self._token_manager.revoke(token)

                # Step 8 — write audit
                await self._write_audit(
                    execution_id=execution_id,
                    agent_id=node_def.agent_id,
                    action=f"NODE_EXECUTED:{node_def.node_id}",
                    status="success" if error_code is None else "failure",
                    payload={
                        "node_id": node_def.node_id,
                        "node_type": node_def.node_type,
                        "attempt": attempt,
                        "error_code": error_code,
                    },
                )

            if error_code is None and output is not None:
                # Success
                return TaskDispatchResult(
                    node_id=node_def.node_id,
                    agent_id=node_def.agent_id,
                    status="completed",
                    output_payload=output.output_payload,
                    error_code=None,
                    retry_count=attempt,
                )

            last_error_code = error_code

            # Step 9 — resilience routing
            if error_code in NON_RECOVERABLE_ERRORS:
                # IMMEDIATE_ABORT — no retry
                await self._write_audit(
                    execution_id=execution_id,
                    agent_id=node_def.agent_id,
                    action="NON_RECOVERABLE_FAILURE",
                    status="aborted",
                    payload={"error_code": error_code, "node_id": node_def.node_id},
                    severity=AuditEventSeverity.CRITICAL,
                )
                return TaskDispatchResult(
                    node_id=node_def.node_id,
                    agent_id=node_def.agent_id,
                    status="failed",
                    output_payload={},
                    error_code=error_code,
                    retry_count=attempt,
                )

            # Recoverable — exponential back-off before retry
            if attempt < self.MAX_RETRY_ATTEMPTS:
                delay = _RETRY_BASE_DELAY_SECONDS * (2 ** attempt)
                await asyncio.sleep(delay)
            else:
                # Exhausted retries
                break

        return TaskDispatchResult(
            node_id=node_def.node_id,
            agent_id=node_def.agent_id,
            status="failed",
            output_payload={},
            error_code=last_error_code,
            retry_count=self.MAX_RETRY_ATTEMPTS,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_ready(
        self,
        completed_node_id: str,
        workflow_def: WorkflowDefinition,
        completed_nodes: set[str],
    ) -> list[str]:
        """Return IDs of nodes newly unblocked by ``completed_node_id``."""
        ready = []
        for node in workflow_def.get_next_nodes(completed_node_id):
            if node.node_id not in completed_nodes and all(
                dep in completed_nodes for dep in node.depends_on
            ):
                ready.append(node.node_id)
        return ready

    def _scopes_for_agent(self, agent_id: str) -> set[CapabilityScope]:
        """Return the set of scopes that should be requested for an agent.

        Falls back to an empty set for unrecognised agents so the token
        manager can still issue a zero-scope token rather than raising.
        """
        allowed = CapabilityTokenManager.AGENT_ALLOWED_SCOPES.get(agent_id, set())
        return set(allowed)

    async def _write_audit(
        self,
        execution_id: str,
        agent_id: str,
        action: str,
        status: str,
        payload: dict,
        severity: AuditEventSeverity = AuditEventSeverity.INFO,
    ) -> None:
        """Fire-and-forget audit write; swallows exceptions so they never
        surface to the caller (orchestrator.yaml audit_failure policy)."""
        try:
            await self._audit.write(
                AuditEvent(
                    execution_id=execution_id,
                    agent_id=agent_id,
                    action=action,
                    status=status,
                    severity=severity,
                    payload=payload,
                )
            )
        except Exception:
            logger.warning("Audit write failed for action=%s", action, exc_info=True)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _extract_error_code(exc: Exception) -> str:
    """Extract a machine-readable error code from an exception.

    CIEError subclasses store the raw message in ``exc.message`` separately
    from the formatted ``str(exc)`` (which includes ``[CODE]`` prefix).
    We prefer ``exc.message`` for code extraction so the ``[AGENT_ERROR]``
    wrapper doesn't obscure the embedded error code prefix.
    """
    # Prefer the raw message attr (CIEError family) over str() representation
    raw = getattr(exc, "message", None) or str(exc)
    colon_idx = raw.find(":")
    if colon_idx > 0:
        prefix = raw[:colon_idx].strip().lower()
        if prefix in RECOVERABLE_ERRORS | NON_RECOVERABLE_ERRORS:
            return prefix
    if hasattr(exc, "error_code") and exc.error_code:
        return exc.error_code
    return type(exc).__name__.upper()
