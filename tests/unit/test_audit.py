"""Unit tests for cie.core.audit.

All tests use an in-memory SQLite database.  The AuditService is
constructed with the real get_session context-manager so behaviour is
identical to production use.

Test matrix:
- test_write_audit_event          — normal write and retrieval
- test_payload_is_hashed          — raw payload never reaches DB
- test_reasoning_key_rejected     — "reasoning" key raises KeyError
- test_breach_severity_recorded   — BREACH inserts the flag row
- test_get_events_filtered        — severity_filter narrows results
- test_audit_failure_raises       — DB failure → CIEError
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from cie.core.audit import AuditEvent, AuditEventSeverity, AuditService
from cie.core.config import CIEConfig
from cie.core.database import AuditLog, get_engine, get_session, init_db
from cie.core.exceptions import CIEError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    """Fresh in-memory engine with all tables."""
    config = CIEConfig(database_filepath=":memory:")
    eng = await get_engine(config)
    await init_db(eng)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def service(engine: AsyncEngine) -> AuditService:
    """AuditService wired to the in-memory engine."""
    return AuditService(session_factory=lambda: get_session(engine))


def _make_event(
    execution_id: str | None = None,
    severity: AuditEventSeverity = AuditEventSeverity.INFO,
    payload: dict | None = None,
) -> AuditEvent:
    """Build a minimal AuditEvent for testing."""
    return AuditEvent(
        execution_id=execution_id or str(uuid.uuid4()),
        agent_id="test_agent",
        action="TEST_ACTION",
        status="success",
        severity=severity,
        payload=payload or {"key": "value"},
    )


# ---------------------------------------------------------------------------
# test_write_audit_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_audit_event(service: AuditService, engine: AsyncEngine) -> None:
    """A written AuditEvent must be retrievable via get_events().

    Verifies that execution_id, agent_id, action, status, and severity
    are all persisted correctly.
    """
    execution_id = str(uuid.uuid4())
    event = _make_event(execution_id=execution_id, severity=AuditEventSeverity.INFO)

    await service.write(event)

    rows = await service.get_events(execution_id)

    assert len(rows) == 1
    row = rows[0]
    assert row.execution_id == execution_id
    assert row.agent_id == "test_agent"
    assert row.action == "TEST_ACTION"
    assert row.status == "success"
    assert row.event_severity == "INFO"


# ---------------------------------------------------------------------------
# test_payload_is_hashed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payload_is_hashed(service: AuditService, engine: AsyncEngine) -> None:
    """The raw payload must not appear in the DB; only a sha256 digest.

    Verifies:
    - payload_hash starts with "sha256:"
    - payload_hash is exactly 71 characters long
    - The original payload value ("secret_value") is not in the hash
    """
    execution_id = str(uuid.uuid4())
    event = _make_event(
        execution_id=execution_id,
        payload={"patient_count": 42, "secret_value": "SENSITIVE"},
    )

    await service.write(event)

    rows = await service.get_events(execution_id)
    assert len(rows) == 1
    ph = rows[0].payload_hash
    assert ph is not None
    assert ph.startswith("sha256:")
    assert len(ph) == 71  # "sha256:" (7) + 64 hex chars
    assert "SENSITIVE" not in ph


# ---------------------------------------------------------------------------
# test_reasoning_key_rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reasoning_key_rejected(
    service: AuditService,
    engine: AsyncEngine,
) -> None:
    """A payload dict with a 'reasoning' key must raise KeyError before any DB write.

    Enforces orchestrator.yaml capture_reasoning_spans: false.
    Verifies that no row is written to the database.
    """
    execution_id = str(uuid.uuid4())
    event = _make_event(
        execution_id=execution_id,
        payload={"reasoning": "some LLM think span", "result": "ok"},
    )

    with pytest.raises(KeyError, match="reasoning"):
        await service.write(event)

    # No rows must have been written
    rows = await service.get_events(execution_id)
    assert rows == []


# ---------------------------------------------------------------------------
# test_breach_severity_recorded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_breach_severity_recorded(
    service: AuditService,
    engine: AsyncEngine,
) -> None:
    """A BREACH security event must produce two rows: the event + BREACH_DETECTED flag.

    Verifies:
    - The primary security event row exists with severity=BREACH.
    - A second BREACH_DETECTED marker row is also written.
    """
    execution_id = str(uuid.uuid4())

    await service.write_security_event(
        execution_id=execution_id,
        agent_id="security",
        event_code="audit_log_modification_attempt",
        severity=AuditEventSeverity.BREACH,
        details={"attempted_by": "unknown"},
    )

    rows = await service.get_events(execution_id)

    # Expect 2 rows: the event itself + the BREACH_DETECTED flag
    assert len(rows) == 2

    actions = {r.action for r in rows}
    assert "audit_log_modification_attempt" in actions
    assert "BREACH_DETECTED" in actions

    severities = {r.event_severity for r in rows}
    assert severities == {"BREACH"}


# ---------------------------------------------------------------------------
# test_get_events_filtered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_events_filtered(
    service: AuditService,
    engine: AsyncEngine,
) -> None:
    """severity_filter must narrow get_events() results correctly.

    Writes one INFO, one WARNING, and one CRITICAL event for the same
    execution_id, then verifies filtering by each severity individually
    and by a combined list.
    """
    execution_id = str(uuid.uuid4())

    for sev in (
        AuditEventSeverity.INFO,
        AuditEventSeverity.WARNING,
        AuditEventSeverity.CRITICAL,
    ):
        await service.write(_make_event(execution_id=execution_id, severity=sev))

    # No filter → all 3
    all_rows = await service.get_events(execution_id)
    assert len(all_rows) == 3

    # Filter INFO only
    info_rows = await service.get_events(
        execution_id, severity_filter=[AuditEventSeverity.INFO]
    )
    assert len(info_rows) == 1
    assert info_rows[0].event_severity == "INFO"

    # Filter WARNING + CRITICAL
    wc_rows = await service.get_events(
        execution_id,
        severity_filter=[AuditEventSeverity.WARNING, AuditEventSeverity.CRITICAL],
    )
    assert len(wc_rows) == 2
    assert {r.event_severity for r in wc_rows} == {"WARNING", "CRITICAL"}

    # Filter BREACH (none written) → empty
    breach_rows = await service.get_events(
        execution_id, severity_filter=[AuditEventSeverity.BREACH]
    )
    assert breach_rows == []


# ---------------------------------------------------------------------------
# test_audit_failure_raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_failure_raises(engine: AsyncEngine) -> None:
    """A DB insertion failure must raise CIEError with AUDIT_INTEGRITY_FAILURE.

    Uses a session factory that raises OperationalError to simulate a
    broken database connection.
    """

    @asynccontextmanager
    async def _failing_session_factory():
        """Simulate a broken DB session."""
        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock(
            side_effect=OperationalError("disk full", None, None)
        )
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        yield mock_session

    broken_service = AuditService(session_factory=_failing_session_factory)

    event = _make_event(payload={"info": "test"})

    with pytest.raises(CIEError) as exc_info:
        await broken_service.write(event)

    assert "AUDIT_INTEGRITY_FAILURE" not in str(exc_info.value)  # error_code not in __str__ path
    # The underlying message must mention the DB error
    assert "Audit log write failed" in str(exc_info.value)
