"""Phase 5 (R5-2) — reference-ingestion PII hardening & entrance separation.

Covers spec/knowledge/embedding-rag-spec.md §3: the strengthened document-body
PII scan (patient data is rejected before it is written anywhere, not even
pending/) and the tabular-data entrance separation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cie.knowledge.ingestion_agent import KnowledgeIngestionAgent
from cie.knowledge.ingestion_guard import IngestionError, IngestionGuard
from cie.knowledge.parsers.base import DocumentParserRegistry
from cie.knowledge.parsers.pymupdf_parser import PlainTextParser

# A legitimate reference paper excerpt — no patient PII.
_CLEAN_PAPER = (
    "# Two-group comparison\n\n"
    "We compared outcomes between arms using the Mann-Whitney U test "
    "(wilcox.test in R). Effect sizes are reported with 95% confidence "
    "intervals. DOI: 10.1000/example.2020.\n"
).encode("utf-8")

# A patient-data document (name / DOB / patient ID) that must be rejected.
_PATIENT_DOC = (
    "患者ID: 12345678\n氏名: 山田太郎\n生年月日: 1980-01-01\n"
    "Subject patient enrolled 2020-01-01.\n"
).encode("utf-8")


def _pii_failed(exc: IngestionError) -> bool:
    return any(c.check_name == "PII_DETECTED_IN_DOCUMENT" for c in exc.failed_checks)


def test_clean_paper_passes():
    guard = IngestionGuard()
    result = guard.inspect(Path("paper.md"), _CLEAN_PAPER)
    assert result.passed is True


def test_patient_document_rejected_on_pii():
    guard = IngestionGuard()
    with pytest.raises(IngestionError) as exc_info:
        guard.inspect(Path("patient_record.txt"), _PATIENT_DOC)
    assert _pii_failed(exc_info.value)


def test_japanese_name_and_dob_detected():
    guard = IngestionGuard()
    doc = "氏名: 田中花子\n生年月日: 1975-05-05\n".encode("utf-8")
    with pytest.raises(IngestionError) as exc_info:
        guard.inspect(Path("names.md"), doc)
    assert _pii_failed(exc_info.value)


def test_english_patient_id_column_detected():
    guard = IngestionGuard()
    doc = b"Table: patient_id, age, outcome\nP001, 45, responder\n"
    with pytest.raises(IngestionError) as exc_info:
        guard.inspect(Path("cohort.txt"), doc)
    assert _pii_failed(exc_info.value)


def test_tabular_extension_rejected_with_routing_message():
    guard = IngestionGuard()
    with pytest.raises(IngestionError) as exc_info:
        guard.inspect(Path("cohort.csv"), b"id,value\n1,2\n")
    checks = exc_info.value.failed_checks
    ext = next(c for c in checks if c.check_name == "FILE_TYPE_NOT_ALLOWED")
    assert ext.passed is False
    assert "dataset" in ext.reason.lower()  # routed to the dataset entrance


@pytest.mark.asyncio
async def test_patient_document_never_reaches_pending(tmp_path):
    """PII rejection must happen before any pending/ write (ADR-0003 gate)."""
    pending = tmp_path / "pending"
    source = tmp_path / "sources"
    pending.mkdir()
    source.mkdir()
    agent = KnowledgeIngestionAgent(
        IngestionGuard(),
        DocumentParserRegistry([PlainTextParser()]),
        pending,
        source,
    )
    with pytest.raises(IngestionError):
        await agent.ingest(Path("patient.txt"), _PATIENT_DOC, uploaded_by="test")
    # Nothing was staged.
    assert list(pending.iterdir()) == []
    assert list(source.iterdir()) == []
