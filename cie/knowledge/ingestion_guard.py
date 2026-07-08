from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from cie.core.exceptions import CIEError
from cie.security.pii_detector import PIIDetectorLayer1

# Reference material accepts only prose/document formats (embedding-rag-spec §3.1,
# ADR-0005 原則4). Tabular / statistical-data formats belong in the *dataset*
# uploader (POST /api/dataset), never in knowledge ingestion.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".md", ".txt", ".docx"})
# "Weak first wall": these are patient-data shaped and are rejected up front with
# a targeted message routing the user to the dataset entrance.
TABULAR_DATA_EXTENSIONS: frozenset[str] = frozenset(
    {".csv", ".tsv", ".xlsx", ".xls", ".sav", ".dta", ".por", ".sas7bdat", ".parquet"}
)
MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024  # 50MB

# Lightweight PII patterns for raw document text. These complement the shared
# Layer-1 column-name detector (PIIDetectorLayer1) with document-body-specific
# signals (raw ID digit runs, date-near-subject) that the column-name patterns
# do not carry.
_PII_TEXT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\d{8,}"),                          # 8+ consecutive digits (patient ID)
    re.compile(r"(氏名|患者名|患者ID|生年月日|住所)", re.IGNORECASE),  # Japanese PII keywords
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b.*\b(患者|subject|patient)\b", re.IGNORECASE),
    # English patient identifiers with separators (patient_id / patient-id) and
    # medical record numbers — the shared column patterns only match the
    # whitespace form, so cover the underscore/hyphen forms here for bodies.
    re.compile(r"patient[\s_\-]*id|medical\s*record\s*(?:number|no)\b|\bmrn\b", re.IGNORECASE),
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
        # Reuse the shared Layer-1 regex detector for document-body scanning.
        self._pii_layer1 = PIIDetectorLayer1()

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
        if passed:
            reason = f"Extension '{suffix}' is allowed."
        elif suffix in TABULAR_DATA_EXTENSIONS:
            reason = (
                f"Extension '{suffix}' is tabular/statistical data and is not a "
                "reference document. Patient data must be uploaded via the "
                "dataset entrance (POST /api/dataset), not knowledge ingestion. "
                f"Reference material accepts only: {sorted(ALLOWED_EXTENSIONS)}."
            )
        else:
            reason = (
                f"Extension '{suffix}' is not in the allowed list: "
                f"{sorted(ALLOWED_EXTENSIONS)}"
            )
        return InspectionCheck(
            check_name="FILE_TYPE_NOT_ALLOWED",
            passed=passed,
            reason=reason,
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
        """Scan the full document body for PII (embedding-rag-spec §3.2).

        Layers the existing PII assets over the raw text so a patient-data
        document is rejected *before* it is written anywhere (not even pending/):

        1. ``PIIDetectorLayer1.detect_column_name`` — the shared column-name
           regex set (patient/case IDs, name, DOB, phone, address, email …),
           applied to the whole body.
        2. ``_PII_TEXT_PATTERNS`` — document-body signals (long ID digit runs,
           date-near-subject) not covered by the column-name set.

        Only the *signal identity* is reported (pattern id / description); the
        matched text is never surfaced, to avoid echoing PII into logs.
        """
        text = file_bytes.decode("utf-8", errors="ignore")
        signals: list[str] = []

        for finding in self._pii_layer1.detect_column_name(text):
            if finding.severity == "CRITICAL" and finding.pattern_id:
                signals.append(finding.pattern_id)

        for pattern in _PII_TEXT_PATTERNS:
            if pattern.search(text):
                signals.append("document_text_pattern")
                break

        if signals:
            # De-duplicate while preserving order for a stable reason string.
            unique = list(dict.fromkeys(signals))
            return InspectionCheck(
                check_name="PII_DETECTED_IN_DOCUMENT",
                passed=False,
                reason=(
                    "Potential PII detected in document text; rejected before "
                    f"staging. Signals: {unique}"
                ),
            )
        return InspectionCheck(
            check_name="PII_DETECTED_IN_DOCUMENT",
            passed=True,
            reason="No PII signals detected in document text.",
        )
