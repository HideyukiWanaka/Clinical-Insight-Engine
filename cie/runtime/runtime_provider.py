"""CIE Platform — Runtime Provider abstraction layer.

Implements the provider selection hierarchy from spec/runtime.yaml
(abstraction_layer.selection_hierarchy) and routes execution requests to
the appropriate underlying executor.

No business logic lives here — this is pure routing per PROJECT_RULES.md
Section 7 (Runtime Rules: every execution environment is abstracted).

Selection hierarchy (spec/runtime.yaml):
  1. user_runtime_override   — caller-supplied per-call override
  2. project_configuration_setting — instance-level default from config
  3. runtime_availability_detection — (future: docker health-check)
  4. default_provider        — "local_restricted_runtime"
"""

from __future__ import annotations

from pathlib import Path

from cie.core.exceptions import RuntimeExecutionError
from cie.runtime.r_executor import ExecutionResult, LocalRExecutor
from cie.security.capability_token import CapabilityToken

# Provider identifiers that mirror spec/runtime.yaml provider_registry
_PROVIDER_LOCAL = "local_restricted_runtime"
_PROVIDER_DOCKER = "docker_runtime"


class RuntimeProvider:
    """Central runtime dispatch layer.

    Accepts a ``LocalRExecutor`` at construction; additional providers (Docker,
    remote) are registered via ``register_provider`` when available.

    Args:
        local_executor: The always-available Local Restricted Runtime executor.
        default_provider_override: Optional project-configuration-level provider
            preference (selection hierarchy level 2). Defaults to
            ``"local_restricted_runtime"``.
    """

    DEFAULT_PROVIDER: str = _PROVIDER_LOCAL

    # Providers supported in the current implementation
    _SUPPORTED_PROVIDERS: frozenset[str] = frozenset({_PROVIDER_LOCAL})

    def __init__(
        self,
        local_executor: LocalRExecutor,
        *,
        default_provider_override: str | None = None,
    ) -> None:
        self._local_executor = local_executor
        self._config_provider = default_provider_override

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------

    def _select_provider(self, user_override: str | None) -> str:
        """Apply the spec/runtime.yaml selection hierarchy.

        Args:
            user_override: Caller-supplied provider name (level 1); ``None``
                to continue down the hierarchy.

        Returns:
            The resolved provider identifier string.
        """
        if user_override is not None:         # Level 1: user_runtime_override
            return user_override
        if self._config_provider is not None:  # Level 2: project_configuration_setting
            return self._config_provider
        # Level 3 (availability detection) is a no-op for now — only local is implemented.
        return self.DEFAULT_PROVIDER           # Level 4: default_provider

    # ------------------------------------------------------------------
    # Public execution API
    # ------------------------------------------------------------------

    async def execute_r(
        self,
        execution_id: str,
        script_path: Path,
        capability_token: CapabilityToken,
        *,
        provider_override: str | None = None,
    ) -> ExecutionResult:
        """Execute an R script via the resolved runtime provider.

        Args:
            execution_id: Unique identifier for this execution run.
            script_path: Absolute path to the R script file.
            capability_token: Must grant ``RUNTIME_INVOKE_EXECUTION`` scope.
            provider_override: Optional per-call provider name (level 1 of the
                selection hierarchy). Accepted values: ``"local_restricted_runtime"``.

        Returns:
            An :class:`~cie.runtime.r_executor.ExecutionResult` with sanitized output.

        Raises:
            RuntimeExecutionError: When the resolved provider is not supported.
            SecurityViolationError: When the token is revoked or expired.
            PermissionDeniedError: When the token lacks the required scope.
        """
        provider = self._select_provider(provider_override)

        if provider not in self._SUPPORTED_PROVIDERS:
            raise RuntimeExecutionError(
                f"Runtime provider '{provider}' is not supported in this environment. "
                f"Supported providers: {sorted(self._SUPPORTED_PROVIDERS)}",
                runtime_provider=provider,
                execution_id=execution_id,
            )

        # Currently only local_restricted_runtime is implemented
        return await self._local_executor.execute(
            execution_id,
            script_path,
            capability_token,
        )
