from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from cie.core.exceptions import CIEError

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".md", ".txt", ".docx"})
MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024  # 50MB

# Lightweight PII patterns for raw document text.
# PIIDetectorLayer1 targets column names / category labels, not free-form text,
# so we maintain a minimal set of signals here for the document quarantine layer.
_PII_TEXT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\d{8,}"),                          # 8+ consecutive digits (patient ID)
    re.compile(r"(氏名|患者名|患者ID|生年月日|住所)", re.IGNORECASE),  # Japanese PII keywords
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b.*\b(患者|subject|patient)\b", re.IGNORECASE),
]


@dataclass
class InspectionCheck:
    check_name: str
    passed: bool
    reason: str
    sha256: str | None = None


@dataclass
class InspectionResult:
    passed: bool
    sha256: str
    file_size_bytes: int
    checks: list[InspectionCheck]
    failed_checks: list[InspectionCheck] = field(default_factory=list)


class IngestionError(CIEError):
    error_code: str = "INGESTION_ERROR"

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "INGESTION_ERROR",
        failed_checks: list[InspectionCheck] | None = None,
        execution_id: str | None = None,
    ) -> None:
        super().__init__(message, execution_id=execution_id)
        self.error_code = error_code
        self.failed_checks: list[InspectionCheck] = failed_checks or []


class IngestionGuard:
    """Five-stage document quarantine for the Knowledge Ingestion Pipeline.

    All checks must pass before a document advances to Phase 2 (AI extraction).
    This class performs no filesystem writes.
    """

    def __init__(self, known_hashes: set[str] | None = None) -> None:
        self._known_hashes: set[str] = known_hashes or set()

    def inspect(self, file_path: Path, file_bytes: bytes) -> InspectionResult:
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        suffix = file_path.suffix.lower()
        checks: list[InspectionCheck] = []

        checks.append(self._check_extension(suffix))
        checks.append(self._check_file_size(file_bytes))
        checks.append(self._check_duplicate(sha256))
        checks.append(self._check_embedded_scripts(suffix, file_bytes))
        checks.append(self._check_pii(file_bytes))

        failed = [c for c in checks if not c.passed]
        if failed:
            raise IngestionError(
                f"Document failed ingestion checks: {[c.check_name for c in failed]}",
                error_code=failed[0].check_name,
                failed_checks=failed,
            )

        return InspectionResult(
            passed=True,
            sha256=sha256,
            file_size_bytes=len(file_bytes),
            checks=checks,
            failed_checks=[],
        )

    def _check_extension(self, suffix: str) -> InspectionCheck:
        passed = suffix in ALLOWED_EXTENSIONS
        return InspectionCheck(
            check_name="FILE_TYPE_NOT_ALLOWED",
            passed=passed,
            reason=(
                f"Extension '{suffix}' is allowed."
                if passed
                else f"Extension '{suffix}' is not in the allowed list: {sorted(ALLOWED_EXTENSIONS)}"
            ),
        )

    def _check_file_size(self, file_bytes: bytes) -> InspectionCheck:
        size = len(file_bytes)
        passed = size <= MAX_FILE_SIZE_BYTES
        return InspectionCheck(
            check_name="FILE_TOO_LARGE",
            passed=passed,
            reason=(
                f"File size {size} bytes is within the limit."
                if passed
                else f"File size {size} bytes exceeds the {MAX_FILE_SIZE_BYTES}-byte limit."
            ),
        )

    def _check_duplicate(self, sha256: str) -> InspectionCheck:
        passed = sha256 not in self._known_hashes
        return InspectionCheck(
            check_name="DUPLICATE_DOCUMENT",
            passed=passed,
            sha256=sha256,
            reason=(
                "No duplicate detected."
                if passed
                else f"A document with SHA-256 {sha256} is already registered."
            ),
        )

    def _check_embedded_scripts(self, suffix: str, file_bytes: bytes) -> InspectionCheck:
        if suffix != ".pdf":
            return InspectionCheck(
                check_name="EMBEDDED_SCRIPT_DETECTED",
                passed=True,
                reason="Embedded script check applies to PDF files only; skipped.",
            )
        has_js = b"/JavaScript" in file_bytes or b"/JS" in file_bytes
        return InspectionCheck(
            check_name="EMBEDDED_SCRIPT_DETECTED",
            passed=not has_js,
            reason=(
                "No embedded scripts detected."
                if not has_js
                else "PDF contains embedded JavaScript (/JavaScript or /JS token)."
            ),
        )

    def _check_pii(self, file_bytes: bytes) -> InspectionCheck:
        text = file_bytes.decode("utf-8", errors="ignore")
        for pattern in _PII_TEXT_PATTERNS:
            if pattern.search(text):
                return InspectionCheck(
                    check_name="PII_DETECTED_IN_DOCUMENT",
                    passed=False,
                    reason="Potential PII signal detected in document text.",
                )
        return InspectionCheck(
            check_name="PII_DETECTED_IN_DOCUMENT",
            passed=True,
            reason="No PII signals detected in document text.",
        )
