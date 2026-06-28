from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cie.knowledge.ingestion_guard import (
    IngestionError,
    IngestionGuard,
    MAX_FILE_SIZE_BYTES,
)

_CLEAN_PDF = b"%PDF-1.4 sample content without scripts"
_CLEAN_TXT = b"This is a clean text document with no PII."


def test_valid_pdf_passes():
    guard = IngestionGuard()
    result = guard.inspect(Path("report.pdf"), _CLEAN_PDF)
    assert result.passed is True
    assert len(result.failed_checks) == 0


def test_disallowed_extension_fails():
    guard = IngestionGuard()
    with pytest.raises(IngestionError) as exc_info:
        guard.inspect(Path("malware.exe"), _CLEAN_TXT)
    assert any(c.check_name == "FILE_TYPE_NOT_ALLOWED" for c in exc_info.value.failed_checks)


def test_file_too_large_fails():
    guard = IngestionGuard()
    big = b"x" * (MAX_FILE_SIZE_BYTES + 1)
    with pytest.raises(IngestionError) as exc_info:
        guard.inspect(Path("huge.pdf"), big)
    assert any(c.check_name == "FILE_TOO_LARGE" for c in exc_info.value.failed_checks)


def test_duplicate_hash_fails():
    content = b"%PDF-1.4 duplicate document"
    sha = hashlib.sha256(content).hexdigest()
    guard = IngestionGuard(known_hashes={sha})
    with pytest.raises(IngestionError) as exc_info:
        guard.inspect(Path("duplicate.pdf"), content)
    assert any(c.check_name == "DUPLICATE_DOCUMENT" for c in exc_info.value.failed_checks)


def test_pdf_with_embedded_js_fails():
    malicious = b"%PDF-1.4 /JavaScript alert('xss') /JS endobj"
    guard = IngestionGuard()
    with pytest.raises(IngestionError) as exc_info:
        guard.inspect(Path("malicious.pdf"), malicious)
    assert any(c.check_name == "EMBEDDED_SCRIPT_DETECTED" for c in exc_info.value.failed_checks)


def test_txt_skips_js_check():
    # A .txt file containing /JavaScript should NOT trigger the embedded script check
    txt_with_js_text = b"This text mentions /JavaScript as a topic."
    guard = IngestionGuard()
    result = guard.inspect(Path("notes.txt"), txt_with_js_text)
    assert result.passed is True
    js_check = next(c for c in result.checks if c.check_name == "EMBEDDED_SCRIPT_DETECTED")
    assert js_check.passed is True
    assert "skipped" in js_check.reason


def test_inspection_result_contains_sha256():
    guard = IngestionGuard()
    result = guard.inspect(Path("doc.pdf"), _CLEAN_PDF)
    expected = hashlib.sha256(_CLEAN_PDF).hexdigest()
    assert result.sha256 == expected


def test_ingestion_error_contains_failed_checks():
    guard = IngestionGuard()
    with pytest.raises(IngestionError) as exc_info:
        guard.inspect(Path("script.exe"), _CLEAN_TXT)
    err = exc_info.value
    assert isinstance(err.failed_checks, list)
    assert len(err.failed_checks) > 0
