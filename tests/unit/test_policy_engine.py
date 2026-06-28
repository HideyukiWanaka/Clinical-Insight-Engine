"""Unit tests for cie.security.policy_engine.

Test matrix:
- test_enforce_valid_scope              — valid token passes enforce()
- test_enforce_invalid_scope            — undeclared scope raises PermissionDeniedError
- test_enforce_expired_token            — expired token raises SecurityViolationError
- test_enforce_wrong_binding            — wrong execution_id raises SecurityViolationError
- test_audit_written_on_success         — audit.write called on success
- test_audit_written_on_failure         — audit.write called on scope failure
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from cie.core.exceptions import PermissionDeniedError, SecurityViolationError
from cie.security.capability_token import (
    CapabilityScope,
    CapabilityToken,
    CapabilityTokenManager,
)
from cie.security.policy_engine import PolicyEngine

EXEC_ID = str(uuid.uuid4())
STEP_ID = "run_statistics"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_audit() -> AsyncMock:
    svc = MagicMock()
    svc.write = AsyncMock()
    return svc


@pytest.fixture
def manager() -> CapabilityTokenManager:
    return CapabilityTokenManager()


@pytest.fixture
def engine(manager: CapabilityTokenManager, mock_audit: AsyncMock) -> PolicyEngine:
    return PolicyEngine(token_manager=manager, audit_service=mock_audit)


def _make_token(
    agent_id: str = "statistics",
    granted: frozenset[CapabilityScope] | None = None,
    expired: bool = False,
) -> CapabilityToken:
    now = datetime.now(timezone.utc)
    expires = now - timedelta(seconds=1) if expired else now + timedelta(seconds=300)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id=agent_id,
        bound_step_id=STEP_ID,
        granted_scopes=granted if granted is not None else frozenset({CapabilityScope.AUDIT_WRITE_ENTRY}),
        denied_scopes=frozenset(),
        issued_at=now - timedelta(seconds=1),
        expires_at=expires,
    )


# ---------------------------------------------------------------------------
# enforce() — scope checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_valid_scope(engine: PolicyEngine, mock_audit: AsyncMock) -> None:
    token = _make_token(granted=frozenset({CapabilityScope.AUDIT_WRITE_ENTRY}))
    await engine.enforce(token, CapabilityScope.AUDIT_WRITE_ENTRY, EXEC_ID, "statistics", STEP_ID)
    # Should complete without exception


@pytest.mark.asyncio
async def test_enforce_invalid_scope(engine: PolicyEngine) -> None:
    token = _make_token(granted=frozenset({CapabilityScope.AUDIT_WRITE_ENTRY}))
    with pytest.raises(PermissionDeniedError):
        await engine.enforce(
            token, CapabilityScope.DATASET_READ_RAW, EXEC_ID, "statistics", STEP_ID
        )


@pytest.mark.asyncio
async def test_enforce_expired_token(engine: PolicyEngine) -> None:
    token = _make_token(expired=True)
    with pytest.raises(SecurityViolationError):
        await engine.enforce(
            token, CapabilityScope.AUDIT_WRITE_ENTRY, EXEC_ID, "statistics", STEP_ID
        )


@pytest.mark.asyncio
async def test_enforce_wrong_binding(engine: PolicyEngine) -> None:
    token = _make_token()
    with pytest.raises(SecurityViolationError):
        await engine.enforce(
            token, CapabilityScope.AUDIT_WRITE_ENTRY,
            "wrong-exec-id", "statistics", STEP_ID,
        )


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_written_on_success(engine: PolicyEngine, mock_audit: AsyncMock) -> None:
    token = _make_token(granted=frozenset({CapabilityScope.AUDIT_WRITE_ENTRY}))
    await engine.enforce(token, CapabilityScope.AUDIT_WRITE_ENTRY, EXEC_ID, "statistics", STEP_ID)
    assert mock_audit.write.call_count >= 1, "Audit must be written on success"


@pytest.mark.asyncio
async def test_audit_written_on_failure(engine: PolicyEngine, mock_audit: AsyncMock) -> None:
    token = _make_token(granted=frozenset({CapabilityScope.AUDIT_WRITE_ENTRY}))
    with pytest.raises(PermissionDeniedError):
        await engine.enforce(
            token, CapabilityScope.DATASET_READ_RAW, EXEC_ID, "statistics", STEP_ID
        )
    assert mock_audit.write.call_count >= 1, "Audit must be written on failure"

