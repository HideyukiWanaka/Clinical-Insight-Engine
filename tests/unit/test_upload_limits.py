"""Unit tests for cie.api.upload_limits (OWASP A03:2025 — unbounded upload DoS).

read_upload_bounded must reject an oversized upload once it has read past
max_bytes, without ever buffering the full unbounded body first.
"""

from __future__ import annotations

import io

import pytest
from fastapi import HTTPException, UploadFile

from cie.api.upload_limits import read_upload_bounded


def _upload(data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="test.csv")


async def test_reads_content_under_limit() -> None:
    data = b"a" * 1000
    result = await read_upload_bounded(_upload(data), max_bytes=2000)
    assert result == data


async def test_rejects_content_over_limit() -> None:
    data = b"a" * 3000
    with pytest.raises(HTTPException) as exc_info:
        await read_upload_bounded(_upload(data), max_bytes=2000)
    assert exc_info.value.status_code == 413
    assert exc_info.value.detail["error_code"] == "FILE_TOO_LARGE"


async def test_boundary_exact_limit_succeeds() -> None:
    data = b"a" * 2000
    result = await read_upload_bounded(_upload(data), max_bytes=2000)
    assert result == data


async def test_empty_upload_returns_empty_bytes() -> None:
    result = await read_upload_bounded(_upload(b""), max_bytes=2000)
    assert result == b""
