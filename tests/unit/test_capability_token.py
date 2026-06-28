"""Unit tests for cie.security.capability_token.

Test matrix:
- test_issue_valid_token               — successful token issuance
- test_scope_filtering                 — out-of-policy scopes land in denied_scopes
- test_has_scope_valid                 — granted scope returns True
- test_has_scope_denied                — not-granted scope returns False
- test_token_expires                   — past-expiry token is_valid()=False
- test_revoke_immutable                — revoke() leaves the original unchanged
- test_revoked_token_invalid           — revoked token is_valid()=False
- test_unknown_agent_rejected          — unknown agent_id raises SecurityViolationError
- test_binding_validation              — execution_id mismatch raises SecurityViolationError
- test_planner_cannot_get_read_raw     — planner scope set excludes dataset.read_raw
- test_security_agent_gets_restore_variables — security agent may hold r_code.restore_variables
- test_statistics_cannot_restore_variables   — statistics agent may not hold r_code.restore_variables
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from cie.core.exceptions import PermissionDeniedError, SecurityViolationError
from cie.security.capability_token import (
    CapabilityScope,
    CapabilityToken,
    CapabilityTokenManager,
)

EXEC_ID = str(uuid.uuid4())
STEP_ID = "validate_dataset"


@pytest.fixture(scope="module")
def manager() -> CapabilityTokenManager:
    return CapabilityTokenManager()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _expired_token(agent_id: str = "planner") -> CapabilityToken:
    """Construct a syntactically valid but already-expired token."""
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id=agent_id,
        bound_step_id=STEP_ID,
        granted_scopes=frozenset({CapabilityScope.AUDIT_WRITE_ENTRY}),
        denied_scopes=frozenset(),
        issued_at=past - timedelta(seconds=300),
        expires_at=past,
    )


# ---------------------------------------------------------------------------
# Issuance
# ---------------------------------------------------------------------------


def test_issue_valid_token(manager: CapabilityTokenManager) -> None:
    token = manager.issue(
        execution_id=EXEC_ID,
        agent_id="planner",
        step_id=STEP_ID,
        requested_scopes={CapabilityScope.DATASET_PROXY_METADATA, CapabilityScope.AUDIT_WRITE_ENTRY},
    )
    assert token.bound_execution_id == EXEC_ID
    assert token.bound_agent_id == "planner"
    assert token.bound_step_id == STEP_ID
    assert token.is_valid()
    assert not token.revoked
    assert token.revoked_at is None


def test_scope_filtering(manager: CapabilityTokenManager) -> None:
    """Scopes outside the agent's allow-list must appear in denied_scopes."""
    token = manager.issue(
        execution_id=EXEC_ID,
        agent_id="planner",
        step_id=STEP_ID,
        requested_scopes={
            CapabilityScope.DATASET_PROXY_METADATA,
            CapabilityScope.DATASET_READ_RAW,        # not allowed for planner
            CapabilityScope.RUNTIME_INVOKE_EXECUTION, # not allowed for planner
        },
    )
    assert CapabilityScope.DATASET_PROXY_METADATA in token.granted_scopes
    assert CapabilityScope.DATASET_READ_RAW in token.denied_scopes
    assert CapabilityScope.RUNTIME_INVOKE_EXECUTION in token.denied_scopes


# ---------------------------------------------------------------------------
# has_scope / require_scope
# ---------------------------------------------------------------------------


def test_has_scope_valid(manager: CapabilityTokenManager) -> None:
    token = manager.issue(
        execution_id=EXEC_ID,
        agent_id="planner",
        step_id=STEP_ID,
        requested_scopes={CapabilityScope.AUDIT_WRITE_ENTRY},
    )
    assert token.has_scope(CapabilityScope.AUDIT_WRITE_ENTRY) is True


def test_has_scope_denied(manager: CapabilityTokenManager) -> None:
    token = manager.issue(
        execution_id=EXEC_ID,
        agent_id="planner",
        step_id=STEP_ID,
        requested_scopes={CapabilityScope.AUDIT_WRITE_ENTRY},
    )
    assert token.has_scope(CapabilityScope.DATASET_READ_RAW) is False


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


def test_token_expires() -> None:
    token = _expired_token()
    assert not token.is_valid()
    assert not token.has_scope(CapabilityScope.AUDIT_WRITE_ENTRY)


def test_require_scope_raises_on_expired_token() -> None:
    token = _expired_token()
    with pytest.raises(SecurityViolationError):
        token.require_scope(CapabilityScope.AUDIT_WRITE_ENTRY)


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------


def test_revoke_immutable(manager: CapabilityTokenManager) -> None:
    """revoke() must return a new object; the original token is unchanged."""
    token = manager.issue(
        execution_id=EXEC_ID,
        agent_id="statistics",
        step_id=STEP_ID,
        requested_scopes={CapabilityScope.AUDIT_WRITE_ENTRY},
    )
    revoked = manager.revoke(token)

    assert not token.revoked, "Original token must not be mutated"
    assert token.revoked_at is None, "Original revoked_at must remain None"
    assert revoked.revoked is True
    assert revoked.revoked_at is not None
    assert revoked.token_id == token.token_id


def test_revoked_token_invalid(manager: CapabilityTokenManager) -> None:
    token = manager.issue(
        execution_id=EXEC_ID,
        agent_id="statistics",
        step_id=STEP_ID,
        requested_scopes={CapabilityScope.AUDIT_WRITE_ENTRY},
    )
    revoked = manager.revoke(token)
    assert not revoked.is_valid()
    with pytest.raises(SecurityViolationError):
        revoked.require_scope(CapabilityScope.AUDIT_WRITE_ENTRY)


# ---------------------------------------------------------------------------
# Unknown agent
# ---------------------------------------------------------------------------


def test_unknown_agent_rejected(manager: CapabilityTokenManager) -> None:
    with pytest.raises(SecurityViolationError):
        manager.issue(
            execution_id=EXEC_ID,
            agent_id="non_existent_agent",
            step_id=STEP_ID,
            requested_scopes={CapabilityScope.AUDIT_WRITE_ENTRY},
        )


# ---------------------------------------------------------------------------
# Binding validation
# ---------------------------------------------------------------------------


def test_binding_validation(manager: CapabilityTokenManager) -> None:
    token = manager.issue(
        execution_id=EXEC_ID,
        agent_id="orchestrator",
        step_id=STEP_ID,
        requested_scopes={CapabilityScope.AUDIT_WRITE_ENTRY},
    )
    with pytest.raises(SecurityViolationError):
        manager.validate_binding(
            token,
            execution_id="wrong-exec-id",
            agent_id="orchestrator",
            step_id=STEP_ID,
        )
    with pytest.raises(SecurityViolationError):
        manager.validate_binding(
            token,
            execution_id=EXEC_ID,
            agent_id="statistics",  # wrong agent
            step_id=STEP_ID,
        )
    with pytest.raises(SecurityViolationError):
        manager.validate_binding(
            token,
            execution_id=EXEC_ID,
            agent_id="orchestrator",
            step_id="wrong_step",
        )
    # Correct binding should not raise
    manager.validate_binding(token, EXEC_ID, "orchestrator", STEP_ID)


# ---------------------------------------------------------------------------
# Agent-specific permission matrix coverage
# ---------------------------------------------------------------------------


def test_planner_cannot_get_read_raw(manager: CapabilityTokenManager) -> None:
    """Planner is not allowed dataset.read_raw per permissions.yaml."""
    token = manager.issue(
        execution_id=EXEC_ID,
        agent_id="planner",
        step_id=STEP_ID,
        requested_scopes={CapabilityScope.DATASET_READ_RAW},
    )
    assert CapabilityScope.DATASET_READ_RAW not in token.granted_scopes
    assert CapabilityScope.DATASET_READ_RAW in token.denied_scopes


def test_security_agent_gets_restore_variables(manager: CapabilityTokenManager) -> None:
    """Security agent is explicitly allowed r_code.restore_variables."""
    token = manager.issue(
        execution_id=EXEC_ID,
        agent_id="security",
        step_id=STEP_ID,
        requested_scopes={CapabilityScope.R_CODE_RESTORE_VARIABLES},
    )
    assert CapabilityScope.R_CODE_RESTORE_VARIABLES in token.granted_scopes


def test_statistics_cannot_restore_variables(manager: CapabilityTokenManager) -> None:
    """Statistics agent is denied r_code.restore_variables per permissions.yaml."""
    token = manager.issue(
        execution_id=EXEC_ID,
        agent_id="statistics",
        step_id=STEP_ID,
        requested_scopes={CapabilityScope.R_CODE_RESTORE_VARIABLES},
    )
    assert CapabilityScope.R_CODE_RESTORE_VARIABLES not in token.granted_scopes
    assert CapabilityScope.R_CODE_RESTORE_VARIABLES in token.denied_scopes
