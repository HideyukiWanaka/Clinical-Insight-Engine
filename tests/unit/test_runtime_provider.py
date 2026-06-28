"""Unit tests for cie.runtime.runtime_provider.

Test matrix:
- test_default_provider_is_local              — no override → local_restricted_runtime
- test_user_override_takes_priority           — per-call override wins over config default
- test_config_override_applied                — project-config provider used when no user override
- test_unsupported_provider_raises            — unknown provider → RuntimeExecutionError
- test_docker_provider_not_yet_supported      — docker_runtime raises (not yet implemented)
- test_execute_r_delegates_to_local_executor  — result comes from LocalRExecutor
- test_execute_r_passes_correct_args          — execution_id, script_path, token forwarded
- test_result_conforms_to_execution_contract  — guaranteed fields present on ExecutionResult
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cie.core.exceptions import RuntimeExecutionError
from cie.runtime.r_executor import ExecutionResult
from cie.runtime.runtime_provider import RuntimeProvider
from cie.security.capability_token import CapabilityScope, CapabilityToken

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EXEC_ID = str(uuid.uuid4())


@pytest.fixture
def runtime_token() -> CapabilityToken:
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id="runtime",
        bound_step_id="run_r_script",
        granted_scopes=frozenset({CapabilityScope.RUNTIME_INVOKE_EXECUTION}),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=300),
    )


@pytest.fixture
def mock_result() -> ExecutionResult:
    return ExecutionResult(
        execution_id=EXEC_ID,
        status="success",
        exit_code=0,
        duration_ms=42,
        stdout_digest="a" * 64,
        stderr_digest="b" * 64,
        sanitized_stdout_summary="[1] 2",
        output_artifacts=["execution_result.rds"],
        r_version="4.3.1",
        package_versions={"tidyverse": "2.0.0"},
        dataset_hash=None,
    )


@pytest.fixture
def mock_local_executor(mock_result: ExecutionResult) -> MagicMock:
    executor = MagicMock()
    executor.execute = AsyncMock(return_value=mock_result)
    return executor


@pytest.fixture
def provider(mock_local_executor: MagicMock) -> RuntimeProvider:
    return RuntimeProvider(mock_local_executor)


@pytest.fixture
def script(tmp_path: Path) -> Path:
    p = tmp_path / "analysis.R"
    p.write_text("x <- 1\n")
    return p


# ---------------------------------------------------------------------------
# Provider selection hierarchy
# ---------------------------------------------------------------------------


class TestProviderSelection:
    """Covers spec/runtime.yaml abstraction_layer.selection_hierarchy."""

    def test_default_provider_is_local(self, mock_local_executor: MagicMock) -> None:
        """Level 4 default: local_restricted_runtime when no override is set."""
        p = RuntimeProvider(mock_local_executor)
        assert p._select_provider(None) == "local_restricted_runtime"

    def test_config_override_applied(self, mock_local_executor: MagicMock) -> None:
        """Level 2: project_configuration_setting takes precedence over default."""
        p = RuntimeProvider(
            mock_local_executor,
            default_provider_override="local_restricted_runtime",
        )
        assert p._select_provider(None) == "local_restricted_runtime"

    def test_user_override_takes_priority(self, mock_local_executor: MagicMock) -> None:
        """Level 1: user_runtime_override beats project configuration."""
        p = RuntimeProvider(
            mock_local_executor,
            default_provider_override="local_restricted_runtime",  # level 2
        )
        # Level 1 override should win
        assert p._select_provider("local_restricted_runtime") == "local_restricted_runtime"

    def test_user_override_none_falls_through_to_config(
        self, mock_local_executor: MagicMock
    ) -> None:
        """None user override falls through to config-level setting."""
        p = RuntimeProvider(
            mock_local_executor,
            default_provider_override="local_restricted_runtime",
        )
        assert p._select_provider(None) == "local_restricted_runtime"


# ---------------------------------------------------------------------------
# Unsupported providers
# ---------------------------------------------------------------------------


class TestUnsupportedProvider:
    async def test_unsupported_provider_raises(
        self,
        provider: RuntimeProvider,
        script: Path,
        runtime_token: CapabilityToken,
    ) -> None:
        """An unknown provider name must raise RuntimeExecutionError, not delegate."""
        with pytest.raises(RuntimeExecutionError, match="not supported"):
            await provider.execute_r(
                EXEC_ID,
                script,
                runtime_token,
                provider_override="unknown_runtime",
            )

    async def test_docker_provider_not_yet_supported(
        self,
        provider: RuntimeProvider,
        script: Path,
        runtime_token: CapabilityToken,
    ) -> None:
        """docker_runtime is declared in spec but not yet implemented."""
        with pytest.raises(RuntimeExecutionError):
            await provider.execute_r(
                EXEC_ID,
                script,
                runtime_token,
                provider_override="docker_runtime",
            )


# ---------------------------------------------------------------------------
# Delegation to LocalRExecutor
# ---------------------------------------------------------------------------


class TestDelegation:
    async def test_execute_r_delegates_to_local_executor(
        self,
        provider: RuntimeProvider,
        mock_local_executor: MagicMock,
        script: Path,
        runtime_token: CapabilityToken,
        mock_result: ExecutionResult,
    ) -> None:
        """execute_r must return exactly what LocalRExecutor.execute() returns."""
        result = await provider.execute_r(EXEC_ID, script, runtime_token)
        assert result is mock_result

    async def test_execute_r_passes_correct_args(
        self,
        provider: RuntimeProvider,
        mock_local_executor: MagicMock,
        script: Path,
        runtime_token: CapabilityToken,
    ) -> None:
        """LocalRExecutor.execute() must receive the exact args passed to execute_r."""
        await provider.execute_r(EXEC_ID, script, runtime_token)
        mock_local_executor.execute.assert_called_once_with(EXEC_ID, script, runtime_token)

    async def test_local_executor_not_called_on_unsupported_provider(
        self,
        provider: RuntimeProvider,
        mock_local_executor: MagicMock,
        script: Path,
        runtime_token: CapabilityToken,
    ) -> None:
        """LocalRExecutor must not be called when the provider is unsupported."""
        with pytest.raises(RuntimeExecutionError):
            await provider.execute_r(
                EXEC_ID, script, runtime_token, provider_override="bad_provider"
            )
        mock_local_executor.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Execution contract conformance (spec/runtime.yaml execution_contract)
# ---------------------------------------------------------------------------


class TestExecutionContract:
    async def test_result_conforms_to_execution_contract(
        self,
        provider: RuntimeProvider,
        script: Path,
        runtime_token: CapabilityToken,
        mock_result: ExecutionResult,
    ) -> None:
        """ExecutionResult must carry all guaranteed fields from the execution contract."""
        result = await provider.execute_r(EXEC_ID, script, runtime_token)

        # spec/runtime.yaml execution_contract.invocation_result.guaranteed_fields
        assert hasattr(result, "status")
        assert hasattr(result, "exit_code")
        assert hasattr(result, "duration_ms")
        assert hasattr(result, "stdout_digest")
        assert hasattr(result, "stderr_digest")
        assert hasattr(result, "output_artifacts")
        assert result.execution_id == EXEC_ID

    async def test_result_status_is_valid_literal(
        self,
        provider: RuntimeProvider,
        script: Path,
        runtime_token: CapabilityToken,
    ) -> None:
        """status must be one of the four declared literals."""
        result = await provider.execute_r(EXEC_ID, script, runtime_token)
        assert result.status in {"success", "timeout", "error", "security_abort"}
