"""CIE Platform — Audit logging service.

Provides :class:`AuditService`, the single authorised writer to the
``audit_log`` table.  All platform components that need to record a
decision or security event must go through this service.

Key invariants (enforced here, not by the DB layer):
- **Immutability**: ``AuditLog`` rows are INSERT-only; no UPDATE or DELETE
  is ever issued.
- **No raw payload in DB**: the ``payload`` dict is SHA-256 hashed;
  only the digest is persisted (``orchestrator.yaml audit_policy``).
- **No reasoning spans**: if ``payload`` contains a ``"reasoning"`` key,
  a :class:`KeyError` is raised before any DB write
  (``orchestrator.yaml capture_reasoning_spans: false``).
- **Audit integrity**: a write failure raises
  :class:`~cie.core.exceptions.CIEError` with code
  ``"AUDIT_INTEGRITY_FAILURE"`` so the Orchestrator can abort
  (``security.yaml on_audit_log_write_failure``).

Design notes (PROJECT_RULES.md Section 14):
- Pure functions where possible; ``AuditService`` only holds a session
  factory — no in-memory state.
- Business logic is minimal: hashing + DB write + BREACH flag.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from cie.core.database import AuditLog
from cie.core.exceptions import CIEError


# ---------------------------------------------------------------------------
# Severity enum
# ---------------------------------------------------------------------------


class AuditEventSeverity(str, Enum):
    """Severity levels for audit events.

    Values mirror the ``security_event_classification`` entries in
    ``agents/security.yaml``.

    Attributes:
        INFO: Routine operational events (e.g., token issued).
        WARNING: Anomalous but non-critical events (e.g., scope denied).
        CRITICAL: Events requiring immediate attention (e.g., PII access
            without approval).
        BREACH: Active security violations (e.g., audit log modification
            attempt).
    """

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    BREACH = "BREACH"


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------


@dataclass
class AuditEvent:
    """Structured description of a single audit-worthy platform event.

    Attributes:
        execution_id: Workflow / task execution context identifier.
        agent_id: Identifier of the agent that raised the event.
        action: Short machine-readable description of the action taken
            (e.g., ``"WORKFLOW_STARTED"``, ``"TOKEN_ISSUED"``).
        status: Outcome of the action
            (e.g., ``"success"``, ``"failure"``, ``"aborted"``).
        severity: Severity classification.
        payload: Structured payload describing the event details.
            **The payload is never persisted; only its SHA-256 digest is
            stored.** The dict must NOT contain a ``"reasoning"`` key —
            :meth:`AuditService.write` will raise :class:`KeyError` if
            it does.
        timestamp: UTC datetime of the event.  Defaults to *now* at
            dataclass creation time.
    """

    execution_id: str
    agent_id: str
    action: str
    status: str
    severity: AuditEventSeverity
    payload: dict[str, Any]
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# BREACH flag sentinel — stored as a second AuditLog row
# ---------------------------------------------------------------------------

_BREACH_FLAG_ACTION = "BREACH_DETECTED"


# ---------------------------------------------------------------------------
# AuditService
# ---------------------------------------------------------------------------


class AuditService:
    """Authorised writer to the ``audit_log`` table.

    All platform components must use this class to record decisions and
    security events.  The service enforces the three immutability and
    privacy invariants described in the module docstring.

    Args:
        session_factory: A zero-argument async callable that returns (or
            yields) a connected :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
            Typically this is the :func:`~cie.core.database.get_session`
            context manager bound to an engine, or a test double.

    Example:
        >>> service = AuditService(lambda: get_session(engine))
        >>> await service.write(event)
    """

    def __init__(
        self,
        session_factory: Callable[[], Any],
    ) -> None:
        """Initialise the audit service.

        Args:
            session_factory: Async callable / context manager factory that
                produces an :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        """
        self._session_factory: Callable[[], Any] = session_factory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def write(self, event: AuditEvent) -> None:
        """Append a single audit event to the immutable audit log.

        Steps:
        1. Reject ``payload`` dicts that contain a ``"reasoning"`` key
           (``orchestrator.yaml capture_reasoning_spans: false``).
        2. JSON-serialise the payload and compute its SHA-256 digest.
        3. INSERT a new ``AuditLog`` row.  Never UPDATE or DELETE.
        4. On any DB error, raise
           :class:`~cie.core.exceptions.CIEError` with
           ``error_code="AUDIT_INTEGRITY_FAILURE"``.

        Args:
            event: The :class:`AuditEvent` to record.

        Raises:
            KeyError: If ``event.payload`` contains the forbidden
                ``"reasoning"`` key.
            CIEError: If the database write fails for any reason.
        """
        if "reasoning" in event.payload:
            raise KeyError(
                "payload must not contain 'reasoning' key "
                "(orchestrator.yaml capture_reasoning_spans: false). "
                "Strip the reasoning span before calling AuditService.write()."
            )

        payload_hash = _hash_payload(event.payload)

        row = AuditLog(
            id=str(uuid.uuid4()),
            timestamp=event.timestamp,
            execution_id=event.execution_id,
            agent_id=event.agent_id,
            action=event.action,
            status=event.status,
            event_severity=event.severity.value,
            payload_hash=payload_hash,
        )

        try:
            async with self._session_factory() as session:  # type: AsyncSession
                session.add(row)
                await session.commit()
        except SQLAlchemyError as exc:
            raise CIEError(
                f"Audit log write failed: {exc}",
                execution_id=event.execution_id,
            ) from exc

    async def write_security_event(
        self,
        execution_id: str,
        agent_id: str,
        event_code: str,
        severity: AuditEventSeverity,
        details: dict[str, Any],
    ) -> None:
        """Record a security-classified event and, for BREACH, set a flag.

        Wraps :meth:`write` with a pre-assembled :class:`AuditEvent`.
        For ``severity=BREACH`` an additional ``BREACH_DETECTED`` marker
        row is inserted so that downstream consumers can detect breaches
        without re-scanning severity values.

        Args:
            execution_id: Workflow / task execution context identifier.
            agent_id: Identifier of the agent that detected the event.
            event_code: Machine-readable event code from
                ``agents/security.yaml security_event_classification``
                (e.g., ``"prompt_injection_detected"``).
            severity: Severity level of the security event.
            details: Structured detail dict for the event.  Must NOT
                contain a ``"reasoning"`` key.

        Raises:
            KeyError: If ``details`` contains the forbidden
                ``"reasoning"`` key (propagated from :meth:`write`).
            CIEError: If any database write fails.
        """
        event = AuditEvent(
            execution_id=execution_id,
            agent_id=agent_id,
            action=event_code,
            status="security_event",
            severity=severity,
            payload=details,
        )
        await self.write(event)

        if severity is AuditEventSeverity.BREACH:
            breach_flag = AuditEvent(
                execution_id=execution_id,
                agent_id=agent_id,
                action=_BREACH_FLAG_ACTION,
                status="breach_recorded",
                severity=AuditEventSeverity.BREACH,
                payload={"event_code": event_code},
            )
            await self.write(breach_flag)

    async def get_events(
        self,
        execution_id: str,
        severity_filter: list[AuditEventSeverity] | None = None,
    ) -> list[AuditLog]:
        """Retrieve audit log entries for a given execution context.

        Args:
            execution_id: The execution context identifier to query.
            severity_filter: Optional list of :class:`AuditEventSeverity`
                values to restrict results.  When ``None`` all severity
                levels are returned.

        Returns:
            A list of :class:`~cie.core.database.AuditLog` ORM instances
            ordered by ascending ``timestamp``.

        Raises:
            CIEError: If the database query fails.
        """
        try:
            async with self._session_factory() as session:  # type: AsyncSession
                stmt = select(AuditLog).where(
                    AuditLog.execution_id == execution_id
                )
                if severity_filter is not None:
                    allowed = [s.value for s in severity_filter]
                    stmt = stmt.where(AuditLog.event_severity.in_(allowed))
                stmt = stmt.order_by(AuditLog.timestamp)
                result = await session.execute(stmt)
                return list(result.scalars().all())
        except SQLAlchemyError as exc:
            raise CIEError(
                f"Audit log query failed: {exc}",
                execution_id=execution_id,
            ) from exc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _hash_payload(payload: dict[str, Any]) -> str:
    """Compute a SHA-256 digest of the JSON-serialised payload.

    Args:
        payload: Arbitrary JSON-serialisable dict.

    Returns:
        Digest string in the form ``sha256:<64-hex-chars>`` (71 chars).
    """
    serialised = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(serialised.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


__all__: list[str] = [
    "AuditEventSeverity",
    "AuditEvent",
    "AuditService",
]
