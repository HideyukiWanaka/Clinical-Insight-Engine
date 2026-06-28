"""CIE Platform — Core exceptions.

All platform-wide exception classes are defined here.
Every exception carries a stable ``error_code`` (SCREAMING_SNAKE_CASE)
and an optional ``execution_id`` for trace correlation.

Design notes (PROJECT_RULES.md Section 14):
- Composition over inheritance: each subclass only adds the minimum it needs.
- Explicit over implicit: every field is typed and documented.
- Business logic is intentionally absent from this module (Phase 1 skeleton).
"""

from __future__ import annotations


class CIEError(Exception):
    """Base class for all CIE Platform exceptions.

    Attributes:
        error_code: Stable, machine-readable identifier in SCREAMING_SNAKE_CASE.
        message: Human-readable description of the error.
        execution_id: Optional workflow / task execution identifier used for
            distributed tracing and audit correlation.
    """

    error_code: str = "CIE_ERROR"

    def __init__(
        self,
        message: str,
        *,
        execution_id: str | None = None,
    ) -> None:
        """Initialise a CIE base exception.

        Args:
            message: Human-readable description of the error condition.
            execution_id: Optional execution context identifier. Defaults to
                ``None`` when no execution context is available.
        """
        super().__init__(message)
        self.message: str = message
        self.execution_id: str | None = execution_id

    def __str__(self) -> str:
        """Return a structured string representation.

        Returns:
            A formatted string that includes the error code, message, and
            optional execution ID.

        Example:
            >>> str(CIEError("something went wrong", execution_id="exec-001"))
            '[CIE_ERROR] something went wrong (execution_id=exec-001)'
        """
        parts = [f"[{self.error_code}] {self.message}"]
        if self.execution_id is not None:
            parts.append(f"(execution_id={self.execution_id})")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Schema / Validation
# ---------------------------------------------------------------------------


class SchemaValidationError(CIEError):
    """Raised when a payload fails JSON Schema validation.

    This enforces the *schema-first* communication contract defined in
    PROJECT_RULES.md Section 13: every cross-component payload must have
    a validated schema.

    Attributes:
        error_code: ``SCHEMA_VALIDATION_ERROR``
        schema_id: Identifier of the schema that was violated.
        validation_errors: List of human-readable validation error messages.
    """

    error_code: str = "SCHEMA_VALIDATION_ERROR"

    def __init__(
        self,
        message: str,
        *,
        schema_id: str | None = None,
        validation_errors: list[str] | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Initialise a schema validation error.

        Args:
            message: Human-readable summary of the validation failure.
            schema_id: Optional identifier of the JSON schema that failed.
            validation_errors: Optional list of individual validation error
                messages returned by the validator.
            execution_id: Optional execution context identifier.
        """
        super().__init__(message, execution_id=execution_id)
        self.schema_id: str | None = schema_id
        self.validation_errors: list[str] = validation_errors or []

    def __str__(self) -> str:
        """Return a structured string representation.

        Returns:
            A formatted string that includes the base representation plus the
            schema ID and individual validation errors (if available).
        """
        base = super().__str__()
        extras: list[str] = []
        if self.schema_id:
            extras.append(f"schema={self.schema_id}")
        if self.validation_errors:
            joined = "; ".join(self.validation_errors)
            extras.append(f"errors=[{joined}]")
        if extras:
            return f"{base} {{{', '.join(extras)}}}"
        return base


# ---------------------------------------------------------------------------
# Security / Permissions
# ---------------------------------------------------------------------------


class PermissionDeniedError(CIEError):
    """Raised when an operation is blocked by the policy engine.

    Per PROJECT_RULES.md Section 8: the default policy is *deny first*.
    Every permission must be explicitly declared.

    Attributes:
        error_code: ``PERMISSION_DENIED``
        required_permission: The permission that was not granted.
        actor: Identifier of the agent or component that attempted the
            operation.
    """

    error_code: str = "PERMISSION_DENIED"

    def __init__(
        self,
        message: str,
        *,
        required_permission: str | None = None,
        actor: str | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Initialise a permission-denied error.

        Args:
            message: Human-readable description of the denied operation.
            required_permission: The permission identifier that was missing.
            actor: Identifier of the agent or component that was denied.
            execution_id: Optional execution context identifier.
        """
        super().__init__(message, execution_id=execution_id)
        self.required_permission: str | None = required_permission
        self.actor: str | None = actor

    def __str__(self) -> str:
        """Return a structured string representation.

        Returns:
            Base representation extended with actor and permission details.
        """
        base = super().__str__()
        extras: list[str] = []
        if self.actor:
            extras.append(f"actor={self.actor}")
        if self.required_permission:
            extras.append(f"permission={self.required_permission}")
        if extras:
            return f"{base} {{{', '.join(extras)}}}"
        return base


class SecurityViolationError(CIEError):
    """Raised when a security policy is actively violated at runtime.

    Unlike :class:`PermissionDeniedError`, this signals a *detected breach*
    rather than a pre-flight permission check failure.

    Attributes:
        error_code: ``SECURITY_VIOLATION``
        policy_id: The security policy rule that was violated.
    """

    error_code: str = "SECURITY_VIOLATION"

    def __init__(
        self,
        message: str,
        *,
        policy_id: str | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Initialise a security violation error.

        Args:
            message: Human-readable description of the violation.
            policy_id: Optional identifier of the violated security policy rule.
            execution_id: Optional execution context identifier.
        """
        super().__init__(message, execution_id=execution_id)
        self.policy_id: str | None = policy_id

    def __str__(self) -> str:
        """Return a structured string representation.

        Returns:
            Base representation extended with the policy ID (if available).
        """
        base = super().__str__()
        if self.policy_id:
            return f"{base} {{policy={self.policy_id}}}"
        return base


# ---------------------------------------------------------------------------
# PII Detection
# ---------------------------------------------------------------------------


class PIIDetectedError(CIEError):
    """Raised when a PII detection layer identifies sensitive patient data.

    CIE implements a three-layer PII detection pipeline
    (spec/system.yaml ``pii_detection_layers: 3``):
      - Layer 1: Regex guardrail
      - Layer 2: Statistical detection
      - Layer 3: ML-based detection (optional)

    Attributes:
        error_code: ``PII_DETECTED``
        severity: Either ``"CRITICAL"`` or ``"WARNING"``. A ``"CRITICAL"``
            severity must always block execution.
        detection_layer: The detection layer (1, 2, or 3) that raised this
            error.
        field_hint: An anonymised hint about the field or location where PII
            was found (must NOT contain the actual PII value).
    """

    error_code: str = "PII_DETECTED"

    def __init__(
        self,
        message: str,
        *,
        severity: str,
        detection_layer: int | None = None,
        field_hint: str | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Initialise a PII detected error.

        Args:
            message: Human-readable description of the PII finding.
            severity: Must be ``"CRITICAL"`` or ``"WARNING"``. Any other value
                is stored as-is but callers should treat unknown values as
                ``"CRITICAL"`` by default.
            detection_layer: The detection layer (1, 2, or 3) that identified
                the PII.
            field_hint: An anonymised description of where PII was found.
                Must **not** contain the actual sensitive value.
            execution_id: Optional execution context identifier.
        """
        super().__init__(message, execution_id=execution_id)
        self.severity: str = severity
        self.detection_layer: int | None = detection_layer
        self.field_hint: str | None = field_hint

    def __str__(self) -> str:
        """Return a structured string representation.

        Returns:
            Base representation extended with severity, detection layer, and
            field hint.
        """
        base = super().__str__()
        extras: list[str] = [f"severity={self.severity}"]
        if self.detection_layer is not None:
            extras.append(f"layer={self.detection_layer}")
        if self.field_hint:
            extras.append(f"field_hint={self.field_hint}")
        return f"{base} {{{', '.join(extras)}}}"


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


class WorkflowError(CIEError):
    """Raised when a workflow-level invariant is violated.

    Examples include attempting to mutate a DAG at runtime (ADR-0001) or
    referencing an unregistered workflow ID.

    Attributes:
        error_code: ``WORKFLOW_ERROR``
        workflow_id: The identifier of the affected workflow.
    """

    error_code: str = "WORKFLOW_ERROR"

    def __init__(
        self,
        message: str,
        *,
        workflow_id: str | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Initialise a workflow error.

        Args:
            message: Human-readable description of the workflow error.
            workflow_id: Optional identifier of the workflow that encountered
                the error.
            execution_id: Optional execution context identifier.
        """
        super().__init__(message, execution_id=execution_id)
        self.workflow_id: str | None = workflow_id

    def __str__(self) -> str:
        """Return a structured string representation.

        Returns:
            Base representation extended with the workflow ID (if available).
        """
        base = super().__str__()
        if self.workflow_id:
            return f"{base} {{workflow_id={self.workflow_id}}}"
        return base


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


class AgentError(CIEError):
    """Raised when an agent fails to fulfil its responsibility.

    Agents are single-responsibility components (PROJECT_RULES.md Section 9).
    This exception should be raised by the agent itself when it cannot recover
    from an internal error.

    Attributes:
        error_code: ``AGENT_ERROR``
        agent_id: Identifier of the failing agent.
    """

    error_code: str = "AGENT_ERROR"

    def __init__(
        self,
        message: str,
        *,
        agent_id: str | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Initialise an agent error.

        Args:
            message: Human-readable description of the agent failure.
            agent_id: Optional identifier of the agent that raised the error.
            execution_id: Optional execution context identifier.
        """
        super().__init__(message, execution_id=execution_id)
        self.agent_id: str | None = agent_id

    def __str__(self) -> str:
        """Return a structured string representation.

        Returns:
            Base representation extended with the agent ID (if available).
        """
        base = super().__str__()
        if self.agent_id:
            return f"{base} {{agent_id={self.agent_id}}}"
        return base


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


class RuntimeExecutionError(CIEError):
    """Raised when the runtime provider fails to execute a task.

    The runtime layer is responsible for execution isolation and resource
    management (spec/system.yaml ``layers.runtime``). This exception is raised
    when execution itself fails (e.g., sandbox crash, timeout, OOM).

    Attributes:
        error_code: ``RUNTIME_EXECUTION_ERROR``
        runtime_provider: Identifier of the runtime provider (e.g.,
            ``"local_restricted_runtime"``, ``"docker_runtime"``).
        exit_code: Optional process exit code returned by the runtime.
    """

    error_code: str = "RUNTIME_EXECUTION_ERROR"

    def __init__(
        self,
        message: str,
        *,
        runtime_provider: str | None = None,
        exit_code: int | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Initialise a runtime execution error.

        Args:
            message: Human-readable description of the execution failure.
            runtime_provider: Optional identifier of the runtime provider.
            exit_code: Optional process exit code returned by the provider.
            execution_id: Optional execution context identifier.
        """
        super().__init__(message, execution_id=execution_id)
        self.runtime_provider: str | None = runtime_provider
        self.exit_code: int | None = exit_code

    def __str__(self) -> str:
        """Return a structured string representation.

        Returns:
            Base representation extended with the provider and exit code.
        """
        base = super().__str__()
        extras: list[str] = []
        if self.runtime_provider:
            extras.append(f"provider={self.runtime_provider}")
        if self.exit_code is not None:
            extras.append(f"exit_code={self.exit_code}")
        if extras:
            return f"{base} {{{', '.join(extras)}}}"
        return base


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


class SkillError(CIEError):
    """Raised when a skill cannot be loaded, validated, or executed.

    Skills carry domain knowledge and procedures (PROJECT_RULES.md Section 11).
    This exception covers errors in any of the three namespaces:
    ``core/``, ``meta/``, and ``user/``.

    Attributes:
        error_code: ``SKILL_ERROR``
        skill_id: Identifier of the skill (e.g., ``"statistics/t-test"``).
        namespace: The namespace of the skill: ``"core"``, ``"meta"``, or
            ``"user"``.
    """

    error_code: str = "SKILL_ERROR"

    def __init__(
        self,
        message: str,
        *,
        skill_id: str | None = None,
        namespace: str | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Initialise a skill error.

        Args:
            message: Human-readable description of the skill error.
            skill_id: Optional identifier of the skill that raised the error.
            namespace: Optional namespace of the skill (``"core"``, ``"meta"``,
                or ``"user"``).
            execution_id: Optional execution context identifier.
        """
        super().__init__(message, execution_id=execution_id)
        self.skill_id: str | None = skill_id
        self.namespace: str | None = namespace

    def __str__(self) -> str:
        """Return a structured string representation.

        Returns:
            Base representation extended with skill ID and namespace.
        """
        base = super().__str__()
        extras: list[str] = []
        if self.namespace:
            extras.append(f"namespace={self.namespace}")
        if self.skill_id:
            extras.append(f"skill_id={self.skill_id}")
        if extras:
            return f"{base} {{{', '.join(extras)}}}"
        return base


# ---------------------------------------------------------------------------
# Human-in-the-loop
# ---------------------------------------------------------------------------


class HumanApprovalRequiredError(CIEError):
    """Raised when an operation requires human authority before proceeding.

    Per PROJECT_RULES.md Section 3.7 and the MANIFEST security policy, the
    following operations always require human approval:
    - Export
    - External API calls
    - Package installation
    - Skill file updates (ADR-0002)
    - User Skill registration (ADR-0002)

    Attributes:
        error_code: ``HUMAN_APPROVAL_REQUIRED``
        operation: A short, machine-readable name for the blocked operation
            (e.g., ``"skill_update"``, ``"package_install"``).
        approval_reason: A human-readable explanation of why approval is
            required.
    """

    error_code: str = "HUMAN_APPROVAL_REQUIRED"

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        approval_reason: str | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Initialise a human-approval-required error.

        Args:
            message: Human-readable description of the blocked operation.
            operation: Short machine-readable name for the operation that
                requires approval.
            approval_reason: Explanation of *why* this operation requires
                human approval.
            execution_id: Optional execution context identifier.
        """
        super().__init__(message, execution_id=execution_id)
        self.operation: str | None = operation
        self.approval_reason: str | None = approval_reason

    def __str__(self) -> str:
        """Return a structured string representation.

        Returns:
            Base representation extended with the operation and approval reason.
        """
        base = super().__str__()
        extras: list[str] = []
        if self.operation:
            extras.append(f"operation={self.operation}")
        if self.approval_reason:
            extras.append(f"reason={self.approval_reason}")
        if extras:
            return f"{base} {{{', '.join(extras)}}}"
        return base


__all__: list[str] = [
    "CIEError",
    "SchemaValidationError",
    "PermissionDeniedError",
    "SecurityViolationError",
    "PIIDetectedError",
    "WorkflowError",
    "AgentError",
    "RuntimeExecutionError",
    "SkillError",
    "HumanApprovalRequiredError",
]
