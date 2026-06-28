"""CIE Platform — Permission policy enforcement engine.

:class:`PolicyEngine` is the single authoritative gate that every agent
invocation must pass through before any action is taken.  It delegates the
actual permission check to the :class:`~cie.security.capability_token.CapabilityToken`
and records every decision — pass or fail — in the immutable audit log.

Design invariants:
- The engine contains no business logic; it only enforces access policy.
- Violations are always logged to audit *before* the exception is (re-)raised.
- An audit write failure must **not** prevent the exception from propagating;
  the policy violation is the primary signal.
- References: ``agents/security.yaml`` SC-001/SC-002/SC-003/SC-007,
  ``architecture/security-model.md`` SP-001/SP-002/SP-003/SP-004.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cie.core.audit import AuditEvent, AuditEventSeverity, AuditService
from cie.core.exceptions import SecurityViolationError
from cie.security.capability_token import (
    CapabilityScope,
    CapabilityToken,
    CapabilityTokenManager,
)


@dataclass
class PolicyDecision:
    """Structured result of a policy evaluation.

    Attributes:
        allowed: Whether all requested scopes were granted.
        granted_scopes: Scopes that were present and permitted.
        denied_scopes: Scopes that were requested but not granted.
        violations: Human-readable descriptions of each policy violation.
    """

    allowed: bool
    granted_scopes: frozenset[CapabilityScope]
    denied_scopes: frozenset[CapabilityScope]
    violations: list[str] = field(default_factory=list)


class PolicyEngine:
    """Enforces capability-based access control for every agent action.

    Args:
        token_manager: Used for ``validate_binding`` checks.
        audit_service: Receives an ``AuditEvent`` for every enforcement
            decision, successful or not.
    """

    def __init__(
        self,
        token_manager: CapabilityTokenManager,
        audit_service: AuditService,
    ) -> None:
        self._token_manager = token_manager
        self._audit = audit_service

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _try_audit(self, event: AuditEvent) -> None:
        """Write *event* to audit; swallow failures so the primary error propagates."""
        try:
            await self._audit.write(event)
        except Exception:  # noqa: BLE001
            pass  # audit failure must not hide the original security violation

    # ------------------------------------------------------------------
    # Public enforcement API
    # ------------------------------------------------------------------

    async def enforce(
        self,
        token: CapabilityToken,
        required_scope: CapabilityScope,
        execution_id: str,
        agent_id: str,
        step_id: str,
    ) -> None:
        """Assert that *token* is valid, correctly bound, and grants *required_scope*.

        Args:
            token: The capability token provided by the agent.
            required_scope: The single scope the agent is attempting to use.
            execution_id: Expected execution context binding.
            agent_id: Expected agent binding.
            step_id: Expected step / node binding.

        Raises:
            SecurityViolationError: On binding mismatch, expired token, or
                revoked token.  A ``SECURITY_BREACH_ATTEMPT`` audit event is
                written before the exception propagates.
            PermissionDeniedError: When the token is valid but does not grant
                *required_scope*.  A ``PERMISSION_DENIED`` audit event is
                written before the exception propagates.
        """
        # Step 1 — validate binding (SC-002)
        try:
            self._token_manager.validate_binding(token, execution_id, agent_id, step_id)
        except SecurityViolationError as exc:
            await self._try_audit(
                AuditEvent(
                    execution_id=execution_id,
                    agent_id=agent_id,
                    action="SECURITY_BREACH_ATTEMPT",
                    status="failure",
                    severity=AuditEventSeverity.BREACH,
                    payload={
                        "token_id": token.token_id,
                        "step_id": step_id,
                        "error": str(exc),
                    },
                )
            )
            raise

        # Step 2 — check scope (SC-001 deny-first)
        try:
            token.require_scope(required_scope)
        except Exception as exc:
            await self._try_audit(
                AuditEvent(
                    execution_id=execution_id,
                    agent_id=agent_id,
                    action="PERMISSION_DENIED",
                    status="failure",
                    severity=AuditEventSeverity.WARNING,
                    payload={
                        "token_id": token.token_id,
                        "required_scope": required_scope.value,
                        "error": str(exc),
                    },
                )
            )
            raise

        # Step 3 — success; log for SC-007 (all token lifecycle events)
        await self._try_audit(
            AuditEvent(
                execution_id=execution_id,
                agent_id=agent_id,
                action="SCOPE_GRANTED",
                status="success",
                severity=AuditEventSeverity.INFO,
                payload={
                    "token_id": token.token_id,
                    "scope": required_scope.value,
                    "step_id": step_id,
                },
            )
        )

    async def enforce_multi(
        self,
        token: CapabilityToken,
        required_scopes: list[CapabilityScope],
        execution_id: str,
        agent_id: str,
        step_id: str,
    ) -> None:
        """Assert that *token* grants all scopes in *required_scopes*.

        Stops at the first failure.

        Args:
            token: The capability token provided by the agent.
            required_scopes: All scopes the agent requires for this action.
            execution_id: Expected execution context binding.
            agent_id: Expected agent binding.
            step_id: Expected step / node binding.

        Raises:
            SecurityViolationError: Propagated from the first failing scope.
            PermissionDeniedError: Propagated from the first failing scope.
        """
        for scope in required_scopes:
            await self.enforce(token, scope, execution_id, agent_id, step_id)

    async def handle_breach(
        self,
        execution_id: str,
        agent_id: str,
        breach_code: str,
        details: dict,
    ) -> None:
        """Record a confirmed breach event and raise immediately.

        This method is called when the Orchestrator detects a BREACH-level
        event (e.g. token forgery, audit log modification attempt).  The caller
        is responsible for revoking all active tokens after this call.

        Args:
            execution_id: Affected execution context.
            agent_id: Agent involved in or triggering the breach.
            breach_code: Machine-readable breach classification code.
            details: Structured context for the audit record.

        Raises:
            SecurityViolationError: Always; carrying code
                ``"SECURITY_BREACH_DETECTED"``.
        """
        await self._try_audit(
            AuditEvent(
                execution_id=execution_id,
                agent_id=agent_id,
                action=breach_code,
                status="breach",
                severity=AuditEventSeverity.BREACH,
                payload=details,
            )
        )
        raise SecurityViolationError(
            "SECURITY_BREACH_DETECTED",
            policy_id="SC-003",
        )
