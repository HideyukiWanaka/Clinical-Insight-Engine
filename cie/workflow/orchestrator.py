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
from cie.knowledge.loader import KnowledgeLoader
from cie.workflow.registry import WorkflowDefinition, WorkflowNodeDef, WorkflowRegistry
from cie.workflow.system_registry import SystemWorkflowRegistry
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
        system_registry: SystemWorkflowRegistry | None = None,
        knowledge_loader: KnowledgeLoader | None = None,
    ) -> None:
        self._registry = workflow_registry
        self._state_machine = state_machine
        self._token_manager = token_manager
        self._policy_engine = policy_engine
        self._context_guard = context_guard
        self._audit = audit_service
        self._agent_registry = agent_registry
        self._system_registry = system_registry
        self._knowledge_loader = knowledge_loader

        # In-memory checkpoint for suspended workflows keyed by execution_id
        self._suspended: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_workflow(
        self,
        execution_id: str,
        intent_object: dict,
        dataset_context: dict | None = None,
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
        # PROJECT_RULES.md S.12: load knowledge once before any agent dispatch
        frozen_knowledge = None
        if self._knowledge_loader is not None:
            frozen_knowledge = self._knowledge_loader.load_for_execution(execution_id)

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
        initial_payload = {
            "intent_object": intent_object,
            "execution_id": execution_id,
            "frozen_knowledge": frozen_knowledge,  # immutable; None if loader not configured
        }
        # Dataset context (column metadata, dataset path, etc.) supplied by the
        # caller so downstream agents can read real data and reference real
        # column names. Never overrides intent_object/execution_id.
        if dataset_context:
            for key, value in dataset_context.items():
                if key not in ("intent_object", "execution_id"):
                    initial_payload[key] = value

        # The entrypoint node re-derives the intent via the Planner. When the
        # caller already supplies a computed intent_object (the normal UI flow),
        # skip that node and seed its declared outputs so the DAG starts at the
        # first data node instead of re-invoking the LLM.
        skip_nodes: set[str] | None = None
        entry_node = workflow_def.get_node(workflow_def.entrypoint)
        if entry_node.agent_id == "planner" and intent_object:
            skip_nodes = {workflow_def.entrypoint}
            initial_payload["analysis_request"] = intent_object
            initial_payload["project_metadata"] = {
                "execution_id": execution_id,
                "seeded_from_precomputed_intent": True,
            }

        loop_result = await self._task_dispatch_loop(
            execution_id=execution_id,
            workflow_def=workflow_def,
            initial_payload=initial_payload,
            current_state=current_state,
            skip_nodes=skip_nodes,
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
    ) -> dict:
        """Resume a suspended workflow after human decision.

        Args:
            execution_id: The execution that is in WAITING_FOR_HUMAN state.
            human_decision: Structured decision payload from the human operator.

        Returns:
            A result dict ``{"execution_id", "final_state", "node_results"}``
            covering the nodes executed after resumption.
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
        loop_result = await self._task_dispatch_loop(
            execution_id=execution_id,
            workflow_def=checkpoint["workflow_def"],
            initial_payload=checkpoint["context"],
            current_state=WorkflowState.RUNNING,
            skip_nodes=checkpoint["completed_nodes"],
        )
        return {
            "execution_id": execution_id,
            "final_state": loop_result["final_state"],
            "node_results": loop_result["node_results"],
        }

    async def run_system_workflow(
        self,
        workflow_id: str,
        input_data: dict,
        triggered_by: str,
    ) -> dict:
        """Execute a system (administrative) workflow bypassing the Planner.

        SystemWorkflowRegistry is queried directly; PlannerAgent is never
        invoked (ADR-0003 principle 5, ADR-0001 boundary).

        Args:
            workflow_id: ID registered in spec/system-workflow.yaml.
            input_data: Caller-supplied payload for the workflow stages.
            triggered_by: User or system identity that initiated the workflow.

        Returns:
            Result dict with ``workflow_id``, ``triggered_by``, and ``status``.

        Raises:
            WorkflowError: If ``system_registry`` was not injected or the
                workflow_id is unknown.
        """
        if self._system_registry is None:
            raise WorkflowError(
                "[SYSTEM_REGISTRY_NOT_CONFIGURED] SystemWorkflowRegistry is not configured on this Orchestrator.",
            )

        import uuid
        execution_id = str(uuid.uuid4())

        workflow_def = self._system_registry.get_workflow(workflow_id)

        await self._write_audit(
            execution_id=execution_id,
            agent_id="orchestrator",
            action="SYSTEM_WORKFLOW_STARTED",
            status="success",
            payload={
                "workflow_id": workflow_id,
                "triggered_by": triggered_by,
                "input_keys": list(input_data.keys()),
                "stage_count": len(workflow_def.get("stages", [])),
            },
        )

        return {
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "triggered_by": triggered_by,
            "stages": workflow_def.get("stages", []),
            "status": "started",
        }

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

        # BFS queue: start from entrypoint normally; when resuming from a
        # checkpoint (skip_nodes non-empty) compute the frontier directly so
        # the BFS doesn't dead-end on a chain of already-completed nodes.
        if skip_nodes:
            ready_queue: list[str] = [
                node.node_id
                for node in workflow_def.nodes.values()
                if node.node_id not in completed_nodes
                and all(dep in completed_nodes for dep in node.depends_on)
            ]
        else:
            ready_queue = [workflow_def.entrypoint]

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
                # Agentless decision nodes route purely on their static rules
                # (e.g. decision_assumption normality branch). The non-selected
                # branch targets are pruned so only one path executes.
                if node_def.node_type == "decision" and node_def.rules:
                    pruned = await self._apply_decision_rules(
                        execution_id=execution_id,
                        node_def=node_def,
                        workflow_def=workflow_def,
                        accumulated_context=accumulated_context,
                        completed_nodes=completed_nodes,
                    )
                    completed_nodes.update(pruned)
                    completed_nodes.add(node_id)
                    ready_queue.extend(self._find_ready(node_id, workflow_def, completed_nodes))
                    # Nodes downstream of a pruned branch (e.g. security_review
                    # after generate_r_script) are unblocked by the pruning and
                    # must be queued AFTER the selected branch so the selected
                    # branch executes first (FIFO order).
                    for pruned_id in sorted(pruned):
                        ready_queue.extend(
                            self._find_ready(pruned_id, workflow_def, completed_nodes)
                        )
                    continue
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
                # Persist checkpoint for resume_workflow.
                # Approval nodes are considered "done" once the human approves,
                # so include them in completed_nodes to skip on resume.
                suspended_completed = set(completed_nodes)
                if node_def.node_type == "approval":
                    suspended_completed.add(node_id)
                self._suspended[execution_id] = {
                    "workflow_def": workflow_def,
                    "completed_nodes": suspended_completed,
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
            # Decision nodes that carry both an agent and static rules
            # (e.g. select_prediction_method) route AFTER the agent output has
            # been merged so rule conditions can read it.
            pruned: set[str] = set()
            if node_def.node_type == "decision" and node_def.rules:
                pruned = await self._apply_decision_rules(
                    execution_id=execution_id,
                    node_def=node_def,
                    workflow_def=workflow_def,
                    accumulated_context=accumulated_context,
                    completed_nodes=completed_nodes,
                )
                completed_nodes.update(pruned)
            ready_queue.extend(self._find_ready(node_id, workflow_def, completed_nodes))
            # Queue nodes unblocked by pruned branches after the selected
            # branch so the selected branch executes first (FIFO order).
            for pruned_id in sorted(pruned):
                ready_queue.extend(
                    self._find_ready(pruned_id, workflow_def, completed_nodes)
                )

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
                severity=AuditEventSeverity.CRITICAL,
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

                # Step 5 — dispatch to agent.
                # The injected payload is the flat accumulated_context that agents
                # read directly (intent_object + prior node outputs), validated
                # against the permissive task-context schema. task.schema.json
                # describes the full task *envelope* and does not match this
                # internally-assembled, trusted context payload.
                agent_input = AgentInput(
                    execution_id=execution_id,
                    node_id=node_def.node_id,
                    capability_token=token,
                    payload=context_payload,
                    input_schema_ref="cie://schemas/task-context.schema.json",
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

    async def _apply_decision_rules(
        self,
        execution_id: str,
        node_def: WorkflowNodeDef,
        workflow_def: WorkflowDefinition,
        accumulated_context: dict,
        completed_nodes: set[str],
    ) -> set[str]:
        """Evaluate a decision node's static rules and prune unselected branches.

        Rule shape (spec/workflow.yaml)::

            rules:
              normality:
                true: generate_r_script
                false: select_nonparametric

        The condition value is resolved deterministically from the
        accumulated context (never invented). The selected route is recorded
        under ``accumulated_context["decision_routes"][node_id]`` and every
        non-selected branch target that exists as a DAG node is returned so
        the dispatch loop can mark it completed (= skipped). Branch targets
        that are labels rather than node IDs (e.g. ``random_effects`` in the
        meta workflow) are recorded in the route only.

        Returns:
            Set of node IDs to prune (may be empty).
        """
        pruned: set[str] = set()
        routes: dict = accumulated_context.setdefault("decision_routes", {})

        for condition_key, branches in node_def.rules.items():
            if not isinstance(branches, dict):
                continue
            value, source = self._resolve_condition_value(
                condition_key, accumulated_context
            )
            # YAML parses `true:` / `false:` keys as booleans, but tolerate
            # string keys ("true"/"false") in hand-written definitions.
            normalized = {
                (k if isinstance(k, bool) else str(k).strip().lower() == "true"): v
                for k, v in branches.items()
            }
            selected = normalized.get(value)
            not_selected = [v for k, v in normalized.items() if k != value]

            routes[node_def.node_id] = {
                "condition": condition_key,
                "value": value,
                "value_source": source,
                "selected": selected,
                "pruned": [t for t in not_selected if t in workflow_def.nodes],
            }

            for target in not_selected:
                if target in workflow_def.nodes and target not in completed_nodes:
                    pruned.add(target)

            await self._write_audit(
                execution_id=execution_id,
                agent_id="orchestrator",
                action=f"DECISION_ROUTED:{node_def.node_id}",
                status="success",
                payload={
                    "node_id": node_def.node_id,
                    "condition": condition_key,
                    "value": value,
                    "value_source": source,
                    "selected_branch": selected,
                    "pruned_nodes": sorted(pruned),
                },
            )

        return pruned

    @staticmethod
    def _resolve_condition_value(condition_key: str, context: dict) -> tuple[bool, str]:
        """Resolve a decision condition to a boolean from the accumulated context.

        Resolution order (first hit wins; fully deterministic):
          1. Top-level context key (e.g. a prior node wrote ``normality``).
          2. Well-known report containers that upstream nodes merge into the
             context (``assumption_report``, ``epp_report``, ``analysis_plan``,
             ``data_quality_report``, ``intent_object``).
          3. Semantic fallback for ``normality``: the Planner's
             ``distribution_assumptions`` field (``assumed_normal`` → True,
             ``non_parametric`` → False).
          4. Default ``True`` — the primary (parametric / sufficient) branch.
             This is the documented default, not a guess: the selected branch
             re-validates its own assumptions downstream.

        Returns:
            ``(value, source)`` where ``source`` names where the value came
            from (for the audit trail).
        """
        def _to_bool(raw: object) -> bool:
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                lowered = raw.strip().lower()
                if lowered in {"true", "yes", "passed", "normal", "assumed_normal", "sufficient"}:
                    return True
                if lowered in {"false", "no", "failed", "non_parametric", "nonparametric", "insufficient"}:
                    return False
            return bool(raw)

        if condition_key in context and not isinstance(context[condition_key], dict):
            return _to_bool(context[condition_key]), "context_top_level"

        for container_key in (
            "assumption_report",
            "epp_report",
            "analysis_plan",
            "data_quality_report",
            "intent_object",
        ):
            container = context.get(container_key)
            if isinstance(container, dict) and condition_key in container:
                return _to_bool(container[condition_key]), container_key

        if condition_key == "normality":
            intent = context.get("intent_object") or {}
            distribution = str(intent.get("distribution_assumptions") or "").lower()
            if distribution == "assumed_normal":
                return True, "intent_object.distribution_assumptions"
            if distribution in {"non_parametric", "nonparametric"}:
                return False, "intent_object.distribution_assumptions"

        return True, "default_primary_branch"

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
