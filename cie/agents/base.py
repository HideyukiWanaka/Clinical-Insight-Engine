"""CIE Platform — BaseAgent: template method contract for all domain agents.

Every domain agent (Planner, Statistics, Visualization, etc.) inherits from
:class:`BaseAgent` and implements :meth:`_execute`.  The public entry point
:meth:`run` enforces the orchestrator's task_dispatch_loop steps 4–6
(agents/orchestrator.yaml):

  Step 4 (assemble_isolated_context_payload) — caller responsibility.
  Step 5 (dispatch_request_to_target_domain_agent) — caller invokes run().
  Step 6 (await_and_validate_agent_response) — enforced here:
    1. Policy scope check  (PolicyEngine.enforce_multi)
    2. Input schema validation  (SchemaRegistry.validate)
    3. Concrete execution  (self._execute — abstract)
    4. Output schema validation  (SchemaRegistry.validate)
    5. Audit write  (AuditService.write — swallows failure)
    6. Return AgentOutput

Design constraints (PROJECT_RULES.md Section 9, spec prompt):
- _execute() must never be called directly; always go through run().
- Schema validation has no bypass option.
- audit_service.write() failure is silently suppressed so the caller always
  receives an AgentOutput, even on infrastructure degradation.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from cie.core.audit import AuditEvent, AuditEventSeverity, AuditService
from cie.core.exceptions import CIEError
from cie.schemas.validator import SchemaRegistry
from cie.security.capability_token import CapabilityScope, CapabilityToken
from cie.security.policy_engine import PolicyEngine

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# I/O contracts
# ---------------------------------------------------------------------------


@dataclass
class AgentInput:
    """Payload delivered to an agent by the Orchestrator (step 4 / step 5).

    Attributes:
        execution_id: Parent workflow execution context identifier.
        node_id: DAG node / step identifier this invocation corresponds to.
        capability_token: Ephemeral token issued by the Orchestrator for this
            node; must carry all scopes declared in the agent's
            ``required_scopes`` property.
        payload: Pre-assembled context payload (schema-validated before
            delivery by the Orchestrator's context guard).
        input_schema_ref: URI of the JSON schema used to validate *payload*,
            e.g. ``"cie://schemas/task.schema.json"``.
    """

    execution_id: str
    node_id: str
    capability_token: CapabilityToken
    payload: dict
    input_schema_ref: str


@dataclass
class AgentOutput:
    """Structured response returned from an agent to the Orchestrator (step 6).

    The Orchestrator validates this object against ``output_schema_ref``
    before advancing the state machine.  All fields are guaranteed to be
    present regardless of whether execution succeeded or failed.

    Attributes:
        execution_id: Correlates this output to the originating AgentInput.
        agent_id: Canonical identifier of the producing agent.
        status: Terminal state of this agent invocation.
        output_payload: Structured result data.  Empty dict on failure.
        output_schema_ref: URI of the JSON schema that *output_payload* must
            conform to (used by the Orchestrator at step 6).
        error_code: Machine-readable error identifier; ``None`` on success.
        error_message: Human-readable error description; ``None`` on success.
        requires_human_clarification: When ``True``, the Orchestrator must
            suspend the dispatch loop and enter ``waiting_for_human`` state
            (agents/orchestrator.yaml on_requires_human_clarification_true).
        clarification_options: Structured options presented to the human
            operator for resolution.  Empty list unless
            ``requires_human_clarification`` is ``True``.
    """

    execution_id: str
    agent_id: str
    status: Literal["success", "failed", "clarification_required"]
    output_payload: dict
    output_schema_ref: str
    error_code: str | None = None
    error_message: str | None = None
    requires_human_clarification: bool = False
    clarification_options: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class BaseAgent(ABC):
    """Abstract base for all CIE domain agents.

    Concrete subclasses must implement the four abstract properties and the
    :meth:`_execute` coroutine.  The :meth:`run` method is sealed — it
    orchestrates the fixed lifecycle and must not be overridden.

    Args:
        policy_engine: Enforces capability scope checks before execution.
        schema_registry: Validates input and output payloads against schemas.
        audit_service: Records execution outcomes to the immutable audit log.
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        schema_registry: SchemaRegistry,
        audit_service: AuditService,
    ) -> None:
        self._policy_engine = policy_engine
        self._schema_registry = schema_registry
        self._audit_service = audit_service

    # ------------------------------------------------------------------
    # Abstract interface — subclasses declare their identity and contract
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def agent_id(self) -> str:
        """Canonical agent identifier (matches agents/orchestrator.yaml)."""

    @property
    @abstractmethod
    def input_schema_ref(self) -> str:
        """URI of the JSON schema that validates the input payload."""

    @property
    @abstractmethod
    def output_schema_ref(self) -> str:
        """URI of the JSON schema that validates the output payload."""

    @property
    @abstractmethod
    def required_scopes(self) -> list[CapabilityScope]:
        """All capability scopes this agent requires to execute."""

    @abstractmethod
    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        """Concrete agent logic — implemented by each domain agent subclass.

        Args:
            agent_input: Validated and scope-checked invocation payload.

        Returns:
            An :class:`AgentOutput` whose ``output_payload`` conforms to the
            agent's ``output_schema_ref``.

        Note:
            Never call this directly.  Always invoke :meth:`run` so that
            the full policy / schema / audit lifecycle is enforced.
        """

    # ------------------------------------------------------------------
    # Sealed execution lifecycle (template method pattern)
    # ------------------------------------------------------------------

    async def run(self, agent_input: AgentInput) -> AgentOutput:
        """Execute the agent with full policy, schema, and audit enforcement.

        Implements agents/orchestrator.yaml task_dispatch_loop steps 5–6.
        Any exception from steps 1–4 is caught and returned as a structured
        ``status="failed"`` :class:`AgentOutput` so the Orchestrator always
        receives a typed response.

        Args:
            agent_input: The invocation payload assembled by the Orchestrator.

        Returns:
            :class:`AgentOutput` with ``status`` in
            ``{"success", "failed", "clarification_required"}``.
        """
        output: AgentOutput

        try:
            # Step 1 — scope enforcement (SC-001 deny-first via PolicyEngine)
            await self._policy_engine.enforce_multi(
                token=agent_input.capability_token,
                required_scopes=list(self.required_scopes),
                execution_id=agent_input.execution_id,
                agent_id=self.agent_id,
                step_id=agent_input.node_id,
            )

            # Step 2 — input schema validation (PROJECT_RULES.md Section 13)
            self._schema_registry.validate(agent_input.payload, agent_input.input_schema_ref)

            # Step 3 — delegate to concrete implementation
            output = await self._execute(agent_input)

            # Step 4 — output schema validation (RT-003 / step 6 enforce_contract)
            self._schema_registry.validate(output.output_payload, output.output_schema_ref)

        except Exception as exc:  # noqa: BLE001
            output = AgentOutput(
                execution_id=agent_input.execution_id,
                agent_id=self.agent_id,
                status="failed",
                output_payload={},
                output_schema_ref=self.output_schema_ref,
                error_code=getattr(exc, "error_code", type(exc).__name__),
                error_message=str(exc),
            )

        # Step 5 — audit write (swallow failures; audit must not block delivery)
        try:
            await self._audit_service.write(
                AuditEvent(
                    execution_id=agent_input.execution_id,
                    agent_id=self.agent_id,
                    action="AGENT_EXECUTION_COMPLETED",
                    status=output.status,
                    severity=(
                        AuditEventSeverity.INFO
                        if output.status == "success"
                        else AuditEventSeverity.WARNING
                    ),
                    payload={
                        "node_id": agent_input.node_id,
                        "output_status": output.status,
                        "error_code": output.error_code,
                    },
                )
            )
        except Exception:  # noqa: BLE001
            _log.warning(
                "Audit write failed for execution_id=%s agent=%s — result still delivered.",
                agent_input.execution_id,
                self.agent_id,
            )

        # Step 6 — return structured result to Orchestrator
        return output
