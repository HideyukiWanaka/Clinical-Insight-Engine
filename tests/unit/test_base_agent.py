"""Unit tests for cie.agents.base.

Test matrix:
- test_scope_enforced                       — enforce_multi called with correct args
- test_input_validated                      — SchemaValidationError on input → status="failed"
- test_output_validated                     — SchemaValidationError on output → status="failed"
- test_audit_written                        — AuditService.write() called on success
- test_execution_error_returns_failed_status — exception in _execute → status="failed"
- test_audit_failure_does_not_surface       — write() failure is silently swallowed
- test_failed_output_carries_error_fields   — error_code and error_message populated
- test_clarification_required_passes_through — clarification_required status returned as-is
- test_output_schema_validated_after_execute — validate called twice (input + output)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.exceptions import AgentError, SchemaValidationError
from cie.security.capability_token import CapabilityScope, CapabilityToken

# ---------------------------------------------------------------------------
# Concrete test agent (minimal BaseAgent implementation)
# ---------------------------------------------------------------------------

EXEC_ID = str(uuid.uuid4())
NODE_ID = "test_node"
INPUT_SCHEMA = "cie://schemas/task.schema.json"
OUTPUT_SCHEMA = "cie://schemas/analysis-request.schema.json"


class ConcreteTestAgent(BaseAgent):
    """Minimal concrete agent used exclusively for unit testing."""

    @property
    def agent_id(self) -> str:
        return "planner"

    @property
    def input_schema_ref(self) -> str:
        return INPUT_SCHEMA

    @property
    def output_schema_ref(self) -> str:
        return OUTPUT_SCHEMA

    @property
    def required_scopes(self) -> list[CapabilityScope]:
        return [CapabilityScope.AUDIT_WRITE_ENTRY]

    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status="success",
            output_payload={"intent": "t_test"},
            output_schema_ref=self.output_schema_ref,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_policy_engine() -> MagicMock:
    pe = MagicMock()
    pe.enforce_multi = AsyncMock()  # succeeds by default
    return pe


@pytest.fixture
def mock_schema_registry() -> MagicMock:
    sr = MagicMock()
    sr.validate = MagicMock()  # synchronous; no-op by default
    return sr


@pytest.fixture
def mock_audit() -> MagicMock:
    svc = MagicMock()
    svc.write = AsyncMock()  # succeeds by default
    return svc


@pytest.fixture
def agent(
    mock_policy_engine: MagicMock,
    mock_schema_registry: MagicMock,
    mock_audit: MagicMock,
) -> ConcreteTestAgent:
    return ConcreteTestAgent(mock_policy_engine, mock_schema_registry, mock_audit)


@pytest.fixture
def valid_token() -> CapabilityToken:
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id="planner",
        bound_step_id=NODE_ID,
        granted_scopes=frozenset({CapabilityScope.AUDIT_WRITE_ENTRY}),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=300),
    )


@pytest.fixture
def agent_input(valid_token: CapabilityToken) -> AgentInput:
    return AgentInput(
        execution_id=EXEC_ID,
        node_id=NODE_ID,
        capability_token=valid_token,
        payload={"user_natural_language_prompt": "compare groups"},
        input_schema_ref=INPUT_SCHEMA,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBaseAgentRun:

    # ------------------------------------------------------------------
    # Scope enforcement (step 1)
    # ------------------------------------------------------------------

    async def test_scope_enforced(
        self,
        agent: ConcreteTestAgent,
        agent_input: AgentInput,
        mock_policy_engine: MagicMock,
        valid_token: CapabilityToken,
    ) -> None:
        """enforce_multi must be called with the agent's required_scopes."""
        await agent.run(agent_input)

        mock_policy_engine.enforce_multi.assert_called_once_with(
            token=valid_token,
            required_scopes=[CapabilityScope.AUDIT_WRITE_ENTRY],
            execution_id=EXEC_ID,
            agent_id="planner",
            step_id=NODE_ID,
        )

    async def test_scope_failure_returns_failed_status(
        self,
        agent: ConcreteTestAgent,
        agent_input: AgentInput,
        mock_policy_engine: MagicMock,
    ) -> None:
        """A scope violation must produce status='failed', not propagate."""
        from cie.core.exceptions import PermissionDeniedError

        mock_policy_engine.enforce_multi.side_effect = PermissionDeniedError(
            "missing scope",
            required_permission="audit.write_entry",
        )
        result = await agent.run(agent_input)
        assert result.status == "failed"
        assert result.error_code == "PERMISSION_DENIED"

    # ------------------------------------------------------------------
    # Input schema validation (step 2)
    # ------------------------------------------------------------------

    async def test_input_validated(
        self,
        agent: ConcreteTestAgent,
        agent_input: AgentInput,
        mock_schema_registry: MagicMock,
    ) -> None:
        """SchemaValidationError on input payload → status='failed'."""
        mock_schema_registry.validate.side_effect = SchemaValidationError(
            "missing required field",
            schema_id=INPUT_SCHEMA,
        )
        result = await agent.run(agent_input)
        assert result.status == "failed"
        assert result.error_code == "SCHEMA_VALIDATION_ERROR"

    async def test_input_schema_ref_used(
        self,
        agent: ConcreteTestAgent,
        agent_input: AgentInput,
        mock_schema_registry: MagicMock,
    ) -> None:
        """validate() must be called with the input schema ref from AgentInput."""
        await agent.run(agent_input)
        # First validate call is for input
        first_call = mock_schema_registry.validate.call_args_list[0]
        _, kwargs_or_args = first_call
        assert INPUT_SCHEMA in first_call.args or INPUT_SCHEMA in first_call.kwargs.values()

    # ------------------------------------------------------------------
    # Output schema validation (step 4)
    # ------------------------------------------------------------------

    async def test_output_validated(
        self,
        agent: ConcreteTestAgent,
        agent_input: AgentInput,
        mock_schema_registry: MagicMock,
    ) -> None:
        """SchemaValidationError on output payload → status='failed'."""
        mock_schema_registry.validate.side_effect = [
            None,                                      # input validation passes
            SchemaValidationError("bad output", schema_id=OUTPUT_SCHEMA),  # output fails
        ]
        result = await agent.run(agent_input)
        assert result.status == "failed"
        assert result.error_code == "SCHEMA_VALIDATION_ERROR"

    async def test_output_schema_validated_after_execute(
        self,
        agent: ConcreteTestAgent,
        agent_input: AgentInput,
        mock_schema_registry: MagicMock,
    ) -> None:
        """validate() must be called twice: once for input, once for output."""
        await agent.run(agent_input)
        assert mock_schema_registry.validate.call_count == 2
        # Second call is for output
        second_call = mock_schema_registry.validate.call_args_list[1]
        assert OUTPUT_SCHEMA in second_call.args or OUTPUT_SCHEMA in second_call.kwargs.values()

    # ------------------------------------------------------------------
    # _execute delegation (step 3)
    # ------------------------------------------------------------------

    async def test_execution_error_returns_failed_status(
        self,
        mock_policy_engine: MagicMock,
        mock_schema_registry: MagicMock,
        mock_audit: MagicMock,
        agent_input: AgentInput,
    ) -> None:
        """An exception raised inside _execute() must be converted to status='failed'."""

        class FailingAgent(BaseAgent):
            @property
            def agent_id(self) -> str:
                return "planner"

            @property
            def input_schema_ref(self) -> str:
                return INPUT_SCHEMA

            @property
            def output_schema_ref(self) -> str:
                return OUTPUT_SCHEMA

            @property
            def required_scopes(self) -> list[CapabilityScope]:
                return [CapabilityScope.AUDIT_WRITE_ENTRY]

            async def _execute(self, agent_input: AgentInput) -> AgentOutput:
                raise AgentError("Internal compute failure", agent_id="planner")

        fa = FailingAgent(mock_policy_engine, mock_schema_registry, mock_audit)
        result = await fa.run(agent_input)

        assert result.status == "failed"
        assert "Internal compute failure" in (result.error_message or "")
        assert result.error_code == "AGENT_ERROR"

    async def test_execution_error_logged_server_side(
        self,
        mock_policy_engine: MagicMock,
        mock_schema_registry: MagicMock,
        mock_audit: MagicMock,
        agent_input: AgentInput,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An unexpected exception must be logged (with traceback) server-side,
        not only returned in the API-facing error_message (OWASP A09:2025 —
        logging failures: previously only the HTTP response carried any trace
        of the failure)."""

        class FailingAgent(BaseAgent):
            @property
            def agent_id(self) -> str:
                return "planner"

            @property
            def input_schema_ref(self) -> str:
                return INPUT_SCHEMA

            @property
            def output_schema_ref(self) -> str:
                return OUTPUT_SCHEMA

            @property
            def required_scopes(self) -> list[CapabilityScope]:
                return [CapabilityScope.AUDIT_WRITE_ENTRY]

            async def _execute(self, agent_input: AgentInput) -> AgentOutput:
                raise AgentError("Internal compute failure", agent_id="planner")

        fa = FailingAgent(mock_policy_engine, mock_schema_registry, mock_audit)
        with caplog.at_level("ERROR"):
            await fa.run(agent_input)

        assert any(
            "Internal compute failure" in r.message and r.levelname == "ERROR"
            for r in caplog.records
        )

    async def test_failed_output_carries_error_fields(
        self,
        agent: ConcreteTestAgent,
        agent_input: AgentInput,
        mock_policy_engine: MagicMock,
    ) -> None:
        """error_code and error_message must be set when status='failed'."""
        from cie.core.exceptions import SecurityViolationError

        mock_policy_engine.enforce_multi.side_effect = SecurityViolationError(
            "token revoked", policy_id="SC-002"
        )
        result = await agent.run(agent_input)
        assert result.status == "failed"
        assert result.error_code is not None
        assert result.error_message is not None
        assert result.execution_id == EXEC_ID
        assert result.agent_id == "planner"

    # ------------------------------------------------------------------
    # Audit write (step 5)
    # ------------------------------------------------------------------

    async def test_audit_written(
        self,
        agent: ConcreteTestAgent,
        agent_input: AgentInput,
        mock_audit: MagicMock,
    ) -> None:
        """AuditService.write() must be called exactly once after successful execution."""
        result = await agent.run(agent_input)
        assert result.status == "success"
        mock_audit.write.assert_called_once()

    async def test_audit_written_on_failure_too(
        self,
        agent: ConcreteTestAgent,
        agent_input: AgentInput,
        mock_audit: MagicMock,
        mock_policy_engine: MagicMock,
    ) -> None:
        """Audit must be written even when execution fails."""
        from cie.core.exceptions import PermissionDeniedError

        mock_policy_engine.enforce_multi.side_effect = PermissionDeniedError("denied")
        result = await agent.run(agent_input)
        assert result.status == "failed"
        mock_audit.write.assert_called_once()

    async def test_audit_failure_does_not_surface(
        self,
        agent: ConcreteTestAgent,
        agent_input: AgentInput,
        mock_audit: MagicMock,
    ) -> None:
        """A write() failure must be silently swallowed — caller still gets AgentOutput."""
        from cie.core.exceptions import CIEError

        mock_audit.write.side_effect = CIEError(
            "Audit DB unavailable", execution_id=EXEC_ID
        )
        # Must not raise; must still return a valid output
        result = await agent.run(agent_input)
        assert result.status == "success"

    # ------------------------------------------------------------------
    # Pass-through behaviours
    # ------------------------------------------------------------------

    async def test_clarification_required_passes_through(
        self,
        mock_policy_engine: MagicMock,
        mock_schema_registry: MagicMock,
        mock_audit: MagicMock,
        agent_input: AgentInput,
    ) -> None:
        """status='clarification_required' returned from _execute must be preserved."""

        class ClarifyingAgent(BaseAgent):
            @property
            def agent_id(self) -> str:
                return "planner"

            @property
            def input_schema_ref(self) -> str:
                return INPUT_SCHEMA

            @property
            def output_schema_ref(self) -> str:
                return OUTPUT_SCHEMA

            @property
            def required_scopes(self) -> list[CapabilityScope]:
                return [CapabilityScope.AUDIT_WRITE_ENTRY]

            async def _execute(self, agent_input: AgentInput) -> AgentOutput:
                return AgentOutput(
                    execution_id=agent_input.execution_id,
                    agent_id=self.agent_id,
                    status="clarification_required",
                    output_payload={"clarification_question": "Is this paired?"},
                    output_schema_ref=self.output_schema_ref,
                    requires_human_clarification=True,
                    clarification_options=[{"option": "yes"}, {"option": "no"}],
                )

        ca = ClarifyingAgent(mock_policy_engine, mock_schema_registry, mock_audit)
        result = await ca.run(agent_input)

        assert result.status == "clarification_required"
        assert result.requires_human_clarification is True
        assert len(result.clarification_options) == 2

    async def test_success_output_fields_preserved(
        self,
        agent: ConcreteTestAgent,
        agent_input: AgentInput,
    ) -> None:
        """On success, execution_id and agent_id in AgentOutput match the input."""
        result = await agent.run(agent_input)
        assert result.status == "success"
        assert result.execution_id == EXEC_ID
        assert result.agent_id == "planner"
        assert result.error_code is None
        assert result.error_message is None
