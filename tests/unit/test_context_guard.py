"""Unit tests for cie.security.context_guard.

Test matrix:
- test_context_guard_raw_data_blocked   — "raw_data_rows" key raises SecurityViolationError
- test_sanitize_stdout_redacts_pii      — PII keywords replaced with [REDACTED]
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from cie.core.exceptions import SecurityViolationError
from cie.security.context_guard import ContextGuard
from cie.security.pii_filter import PIIFilter

EXEC_ID = str(uuid.uuid4())


@pytest.fixture
def mock_audit() -> AsyncMock:
    svc = MagicMock()
    svc.write = AsyncMock()
    return svc


@pytest.fixture
def guard(mock_audit: AsyncMock) -> ContextGuard:
    return ContextGuard(pii_filter=PIIFilter(enable_layer2=False), audit_service=mock_audit)


@pytest.mark.asyncio
async def test_context_guard_raw_data_blocked(guard: ContextGuard) -> None:
    payload = {"analysis_type": "t_test", "raw_data_rows": [{"var_1": 1.0}]}
    with pytest.raises(SecurityViolationError) as exc_info:
        await guard.sanitize_context_payload(payload, EXEC_ID, "statistics")
    assert "INJECT_RAW_DATA_ROWS_ATTEMPTED" in str(exc_info.value)


@pytest.mark.asyncio
async def test_sanitize_stdout_redacts_pii(guard: ContextGuard) -> None:
    stdout = "列: 電話番号, 値: 090-1234-5678\n結果: 正常"
    sanitized = await guard.sanitize_stdout(stdout, EXEC_ID)
    assert "電話番号" not in sanitized
    assert "[REDACTED]" in sanitized
