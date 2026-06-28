"""Unit tests for cie.security.var_alias.

Test matrix:
- test_register_creates_var_n        — column names → var_1, var_2, …
- test_get_var_n                     — original → var_n lookup
- test_restore_requires_scope        — no r_code.restore_variables → PermissionDeniedError
- test_restore_with_valid_scope      — valid security token returns original names
- test_restore_locked_after_first    — second restore() call → AlreadyRestoredError
- test_proxy_metadata_masks_values   — to_proxy_metadata() returns "---" values
- test_alias_store_lifecycle         — create / get / drop lifecycle
- test_double_register_fails         — calling register() twice → VarNAlreadyRegisteredError
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from cie.core.exceptions import PermissionDeniedError
from cie.security.capability_token import CapabilityScope, CapabilityToken, CapabilityTokenManager
from cie.security.var_alias import AlreadyRestoredError, AliasStore, VarNAlreadyRegisteredError, VarNAliasMap

EXEC_ID = str(uuid.uuid4())
COLS = ["患者ID", "収縮期血圧", "拡張期血圧"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _security_token(
    granted: set[CapabilityScope] | None = None,
) -> CapabilityToken:
    """Build a capability token with the given granted scopes."""
    now = datetime.now(timezone.utc)
    scopes = granted if granted is not None else {CapabilityScope.R_CODE_RESTORE_VARIABLES}
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id="security",
        bound_step_id="restore_step",
        granted_scopes=frozenset(scopes),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=300),
    )


# ---------------------------------------------------------------------------
# VarNAliasMap — register / get_var_n
# ---------------------------------------------------------------------------


def test_register_creates_var_n() -> None:
    alias_map = VarNAliasMap()
    result = alias_map.register(COLS)
    assert result["var_1"] == "患者ID"
    assert result["var_2"] == "収縮期血圧"
    assert result["var_3"] == "拡張期血圧"


def test_get_var_n() -> None:
    alias_map = VarNAliasMap()
    alias_map.register(COLS)
    assert alias_map.get_var_n("患者ID") == "var_1"
    assert alias_map.get_var_n("収縮期血圧") == "var_2"


def test_get_var_n_missing_raises() -> None:
    alias_map = VarNAliasMap()
    alias_map.register(COLS)
    with pytest.raises(KeyError):
        alias_map.get_var_n("存在しない列")


# ---------------------------------------------------------------------------
# restore()
# ---------------------------------------------------------------------------


def test_restore_requires_scope() -> None:
    """A token without r_code.restore_variables must be rejected."""
    alias_map = VarNAliasMap()
    alias_map.register(COLS)
    token = _security_token(granted={CapabilityScope.AUDIT_WRITE_ENTRY})
    with pytest.raises(PermissionDeniedError):
        alias_map.restore(token)


def test_restore_with_valid_scope() -> None:
    """Security token with the correct scope returns the original mapping."""
    alias_map = VarNAliasMap()
    alias_map.register(COLS)
    token = _security_token()
    restored = alias_map.restore(token)
    assert restored["var_1"] == "患者ID"
    assert restored["var_2"] == "収縮期血圧"


def test_restore_locked_after_first() -> None:
    """Calling restore() a second time raises AlreadyRestoredError."""
    alias_map = VarNAliasMap()
    alias_map.register(COLS)
    token = _security_token()
    alias_map.restore(token)
    # Second token (still valid)
    token2 = _security_token()
    with pytest.raises(AlreadyRestoredError):
        alias_map.restore(token2)


# ---------------------------------------------------------------------------
# to_proxy_metadata
# ---------------------------------------------------------------------------


def test_proxy_metadata_masks_values() -> None:
    alias_map = VarNAliasMap()
    alias_map.register(COLS)
    proxy = alias_map.to_proxy_metadata()
    assert set(proxy.keys()) == {"var_1", "var_2", "var_3"}
    assert all(v == "---" for v in proxy.values()), "All values must be masked as '---'"


# ---------------------------------------------------------------------------
# double register
# ---------------------------------------------------------------------------


def test_double_register_fails() -> None:
    alias_map = VarNAliasMap()
    alias_map.register(COLS)
    with pytest.raises(VarNAlreadyRegisteredError):
        alias_map.register(["別の列"])


# ---------------------------------------------------------------------------
# AliasStore lifecycle
# ---------------------------------------------------------------------------


def test_alias_store_lifecycle() -> None:
    store = AliasStore()
    alias_map = store.create(EXEC_ID)
    alias_map.register(COLS)

    retrieved = store.get(EXEC_ID)
    assert retrieved is alias_map

    store.drop(EXEC_ID)
    with pytest.raises(KeyError):
        store.get(EXEC_ID)
