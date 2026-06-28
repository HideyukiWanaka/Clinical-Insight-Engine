"""CIE Platform — Context hygiene guard.

:class:`ContextGuard` runs immediately before every LLM context assembly step
(``orchestrator.yaml`` task_dispatch_loop step 4: ``assemble_isolated_context_payload``).
It enforces two invariants at runtime:

1. **No raw data rows** — if any payload key is ``"raw_data_rows"``, the
   guard raises immediately.  This is the runtime enforcement of
   ``agent.schema.json inject_raw_data_rows = const: false``.

2. **PII-free string values** — every string value in the payload is scanned
   with Layer 1 PII patterns.  A CRITICAL hit raises :class:`PIIDetectedError`
   and logs a WARNING-level audit event (timing 2 in
   ``architecture/security-pii-filter.md`` Section 6).

``sanitize_stdout`` implements runtime.yaml RT-004: sanitize execution stdout
before it reaches the audit log or any downstream agent.
"""

from __future__ import annotations

from cie.core.audit import AuditEvent, AuditEventSeverity, AuditService
from cie.core.exceptions import PIIDetectedError, SecurityViolationError
from cie.security.pii_filter import PIIFilter
from cie.security.pii_patterns import PII_PATTERNS


class ContextGuard:
    """Guards LLM context payloads and runtime stdout against PII leakage.

    Args:
        pii_filter: Used to scan string values for PII patterns.
        audit_service: Receives an audit event whenever a violation is detected.
    """

    def __init__(
        self,
        pii_filter: PIIFilter,
        audit_service: AuditService,
    ) -> None:
        self._pii_filter = pii_filter
        self._audit = audit_service

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _try_audit(self, event: AuditEvent) -> None:
        try:
            await self._audit.write(event)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def sanitize_context_payload(
        self,
        payload: dict,
        execution_id: str,
        agent_id: str,
    ) -> dict:
        """Validate a context payload before it is injected into an LLM prompt.

        Scans all top-level string values for PII signals.  Also enforces the
        ``inject_raw_data_rows = const: false`` invariant by blocking any
        payload that carries a ``"raw_data_rows"`` key.

        Args:
            payload: The assembled context payload dict.
            execution_id: Current execution context (for audit).
            agent_id: Target agent receiving this context (for audit).

        Returns:
            The unmodified *payload* if no violations are found.

        Raises:
            SecurityViolationError: When ``"raw_data_rows"`` is present in
                *payload* (``agent.schema.json inject_raw_data_rows = const: false``).
            PIIDetectedError: When a CRITICAL PII pattern is found in any
                string value of *payload*.
        """
        # Hard block — raw data rows must never reach the context
        if "raw_data_rows" in payload:
            await self._try_audit(
                AuditEvent(
                    execution_id=execution_id,
                    agent_id=agent_id,
                    action="INJECT_RAW_DATA_ROWS_ATTEMPTED",
                    status="blocked",
                    severity=AuditEventSeverity.BREACH,
                    payload={"blocked_key": "raw_data_rows"},
                )
            )
            raise SecurityViolationError(
                "INJECT_RAW_DATA_ROWS_ATTEMPTED",
                policy_id="SC-001",
            )

        # PII scan on every string value
        for key, value in payload.items():
            if not isinstance(value, str):
                continue
            findings = self._pii_filter.run_on_prompt(value)
            critical = [f for f in findings if f.severity == "CRITICAL"]
            if critical:
                await self._try_audit(
                    AuditEvent(
                        execution_id=execution_id,
                        agent_id=agent_id,
                        action="PII_DETECTED_IN_CONTEXT_PAYLOAD",
                        status="blocked",
                        severity=AuditEventSeverity.WARNING,
                        payload={
                            "payload_key": key,
                            "pattern_ids": [f.pattern_id for f in critical if f.pattern_id],
                        },
                    )
                )
                raise PIIDetectedError(
                    f"CRITICAL PII pattern detected in context payload field '{key}'.",
                    severity="CRITICAL",
                    detection_layer=1,
                    field_hint=key,
                    execution_id=execution_id,
                )

        return payload

    async def sanitize_stdout(
        self,
        stdout: str,
        execution_id: str,
    ) -> str:
        """Redact PII patterns from runtime execution stdout (RT-004).

        Applies all column-name Layer 1 regex patterns to *stdout* using
        substitution.  Matched portions are replaced with ``"[REDACTED]"``.
        Value-target patterns (phone/email with ``^...$``) are skipped because
        they cannot match within longer text safely.

        Args:
            stdout: Raw stdout captured from the Runtime Provider.
            execution_id: Current execution context (for audit; unused here
                but kept for API consistency).

        Returns:
            The sanitized stdout string with PII patterns replaced.
        """
        sanitized = stdout
        for cfg in PII_PATTERNS.values():
            if cfg.get("target") == "category_label":
                continue  # skip full-string value patterns
            sanitized = cfg["pattern"].sub("[REDACTED]", sanitized)
        return sanitized
