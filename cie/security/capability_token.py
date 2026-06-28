"""CIE Platform — Ephemeral Capability Token (CCT) system.

Every agent invocation is governed by a single-use, time-limited token that
is bound to an exact ``{execution_id, agent_id, step_id}`` triple.

Design references:
- ``spec/permissions.yaml`` — capability definitions and agent_permission_matrix
- ``agents/security.yaml``  — SC-001 (deny-first), SC-002 (ephemeral binding),
                              SC-003 (revoke on breach), SC-007 (immutable log)
- ``agents/orchestrator.yaml`` — task_dispatch_loop steps 3 and 7

TTL is 300 seconds (hard limit per ``spec/permissions.yaml token_ttl_expired``).
Tokens are frozen dataclasses; mutation is impossible — revocation produces a
new copy via ``dataclasses.replace()``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum

from cie.core.exceptions import PermissionDeniedError, SecurityViolationError

TOKEN_TTL_SECONDS: int = 300


class CapabilityScope(str, Enum):
    """All declared capability scopes from ``spec/permissions.yaml``."""

    # Dataset domain
    DATASET_READ_RAW = "dataset.read_raw"
    DATASET_PROXY_METADATA = "dataset.proxy_metadata"
    DATASET_READ_VALIDATED = "dataset.read_validated"

    # Workflow & state domain
    WORKFLOW_STATE_READ = "workflow.state_read"
    WORKFLOW_STATE_WRITE = "workflow.state_write"

    # Statistical code domain
    R_CODE_GENERATE_TEMPLATE = "r_code.generate_template"
    R_CODE_RESTORE_VARIABLES = "r_code.restore_variables"

    # Runtime domain
    RUNTIME_INVOKE_EXECUTION = "runtime.invoke_execution"

    # Reporting domain
    REPORT_COMPILE_MANUSCRIPT = "report.compile_manuscript"
    REPORT_EXPORT_EXTERNAL = "report.export_external"

    # Governance & audit domain
    HUMAN_REQUEST_APPROVAL = "human.request_approval"
    AUDIT_WRITE_ENTRY = "audit.write_entry"

    # Skill lifecycle domain (ADR-0002)
    SKILL_UPDATE_CORE = "skill.update_core"
    SKILL_REGISTER_USER = "skill.register_user"
    SKILL_READ_PERFORMANCE = "skill.read_performance_records"


@dataclass(frozen=True)
class CapabilityToken:
    """Ephemeral Cryptographic Capability Token.

    Immutable by design (``frozen=True``).  All fields are set at issuance;
    revocation produces a new instance via :func:`~dataclasses.replace`.

    Attributes:
        token_id: UUID string uniquely identifying this token.
        bound_execution_id: Execution context this token is locked to.
        bound_agent_id: Agent that may use this token.
        bound_step_id: DAG node / workflow step this token is locked to.
        granted_scopes: Permission scopes the agent may exercise.
        denied_scopes: Scopes that were requested but not allowed.
        issued_at: UTC timestamp of issuance.
        expires_at: UTC timestamp of hard expiry (``issued_at + 300 s``).
        revoked: Set to ``True`` upon node completion or security event.
        revoked_at: UTC timestamp of revocation; ``None`` while active.
    """

    token_id: str
    bound_execution_id: str
    bound_agent_id: str
    bound_step_id: str
    granted_scopes: frozenset[CapabilityScope]
    denied_scopes: frozenset[CapabilityScope]
    issued_at: datetime
    expires_at: datetime
    revoked: bool = False
    revoked_at: datetime | None = None

    def is_valid(self) -> bool:
        """Return ``True`` when the token is neither revoked nor expired."""
        return not self.revoked and datetime.now(timezone.utc) < self.expires_at

    def has_scope(self, scope: CapabilityScope) -> bool:
        """Return ``True`` when the token is valid and grants *scope*.

        Args:
            scope: The capability scope to check.
        """
        return self.is_valid() and scope in self.granted_scopes

    def require_scope(self, scope: CapabilityScope) -> None:
        """Assert that this token grants *scope*.

        Checks revocation and expiry first (``SecurityViolationError``), then
        checks the granted set (``PermissionDeniedError``).

        Args:
            scope: The capability scope that must be present.

        Raises:
            SecurityViolationError: When the token has been revoked or has
                expired (SC-002).
            PermissionDeniedError: When the token is valid but *scope* is not
                in ``granted_scopes`` (SC-001 deny-first).
        """
        if self.revoked:
            raise SecurityViolationError(
                "Capability token has been revoked and cannot be used.",
                policy_id="SC-002",
            )
        if datetime.now(timezone.utc) >= self.expires_at:
            raise SecurityViolationError(
                "Capability token has expired.",
                policy_id="SC-002",
            )
        if scope not in self.granted_scopes:
            raise PermissionDeniedError(
                f"Scope '{scope.value}' is not granted by this capability token.",
                required_permission=scope.value,
                actor=self.bound_agent_id,
            )


class CapabilityTokenManager:
    """Issues, revokes, and validates capability tokens.

    ``AGENT_ALLOWED_SCOPES`` is the Python representation of
    ``spec/permissions.yaml`` ``agent_permission_matrix`` (deny-first; only
    explicitly declared ``allow`` entries appear here).
    """

    AGENT_ALLOWED_SCOPES: dict[str, set[CapabilityScope]] = {
        "orchestrator": {
            CapabilityScope.WORKFLOW_STATE_READ,
            CapabilityScope.WORKFLOW_STATE_WRITE,
            CapabilityScope.HUMAN_REQUEST_APPROVAL,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
        "planner": {
            CapabilityScope.DATASET_PROXY_METADATA,
            CapabilityScope.WORKFLOW_STATE_READ,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
        "data_quality": {
            CapabilityScope.DATASET_READ_RAW,
            CapabilityScope.DATASET_PROXY_METADATA,
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
        "statistics": {
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.R_CODE_GENERATE_TEMPLATE,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
        "visualization": {
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.R_CODE_GENERATE_TEMPLATE,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
        "reporting": {
            CapabilityScope.REPORT_COMPILE_MANUSCRIPT,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
        "reviewer": {
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.AUDIT_WRITE_ENTRY,
            CapabilityScope.SKILL_READ_PERFORMANCE,
        },
        "security": {
            CapabilityScope.R_CODE_RESTORE_VARIABLES,
            CapabilityScope.HUMAN_REQUEST_APPROVAL,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
        "runtime": {
            CapabilityScope.RUNTIME_INVOKE_EXECUTION,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
    }

    def issue(
        self,
        execution_id: str,
        agent_id: str,
        step_id: str,
        requested_scopes: set[CapabilityScope],
    ) -> CapabilityToken:
        """Issue a new ephemeral token for *agent_id*.

        Only scopes declared in ``AGENT_ALLOWED_SCOPES[agent_id]`` are granted.
        Remaining requested scopes are placed in ``denied_scopes`` for
        auditability (SC-001).

        Args:
            execution_id: Parent execution context identifier.
            agent_id: Canonical agent identifier (must be in
                ``AGENT_ALLOWED_SCOPES``).
            step_id: DAG node identifier this token is bound to.
            requested_scopes: Scopes the caller wants to obtain.

        Returns:
            A new :class:`CapabilityToken` with TTL of 300 seconds.

        Raises:
            SecurityViolationError: When *agent_id* is not registered in
                ``AGENT_ALLOWED_SCOPES`` (unknown agent — potential breach).
        """
        if agent_id not in self.AGENT_ALLOWED_SCOPES:
            raise SecurityViolationError(
                f"Unknown agent '{agent_id}' cannot receive a capability token.",
                policy_id="SC-001",
            )
        allowed = self.AGENT_ALLOWED_SCOPES[agent_id]
        granted = frozenset(requested_scopes & allowed)
        denied = frozenset(requested_scopes - allowed)
        now = datetime.now(timezone.utc)
        return CapabilityToken(
            token_id=str(uuid.uuid4()),
            bound_execution_id=execution_id,
            bound_agent_id=agent_id,
            bound_step_id=step_id,
            granted_scopes=granted,
            denied_scopes=denied,
            issued_at=now,
            expires_at=now + timedelta(seconds=TOKEN_TTL_SECONDS),
        )

    def revoke(self, token: CapabilityToken) -> CapabilityToken:
        """Return a revoked copy of *token* without mutating the original.

        Per the immutable token design, a new :class:`CapabilityToken` instance
        is created via :func:`~dataclasses.replace`.  The original is unchanged.

        Args:
            token: The active token to revoke.

        Returns:
            A new ``CapabilityToken`` with ``revoked=True`` and
            ``revoked_at`` set to now (UTC).
        """
        return replace(
            token,
            revoked=True,
            revoked_at=datetime.now(timezone.utc),
        )

    def validate_binding(
        self,
        token: CapabilityToken,
        execution_id: str,
        agent_id: str,
        step_id: str,
    ) -> None:
        """Verify that *token* is bound to the given context triple.

        Called by the Orchestrator at task_dispatch_loop step 6 to confirm
        the token received from the agent matches the one issued at step 3.

        Args:
            token: The token to validate.
            execution_id: Expected bound execution context.
            agent_id: Expected bound agent identifier.
            step_id: Expected bound DAG step identifier.

        Raises:
            SecurityViolationError: On any binding mismatch or when the token
                is no longer valid (expired / revoked).
        """
        if token.bound_execution_id != execution_id:
            raise SecurityViolationError(
                f"Token execution_id mismatch: token='{token.bound_execution_id}',"
                f" expected='{execution_id}'.",
                policy_id="SC-002",
            )
        if token.bound_agent_id != agent_id:
            raise SecurityViolationError(
                f"Token agent_id mismatch: token='{token.bound_agent_id}',"
                f" expected='{agent_id}'.",
                policy_id="SC-002",
            )
        if token.bound_step_id != step_id:
            raise SecurityViolationError(
                f"Token step_id mismatch: token='{token.bound_step_id}',"
                f" expected='{step_id}'.",
                policy_id="SC-002",
            )
        if not token.is_valid():
            raise SecurityViolationError(
                "Token is expired or has been revoked.",
                policy_id="SC-002",
            )
