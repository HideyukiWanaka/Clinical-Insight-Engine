from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from cie.knowledge.ingestion_agent import KnowledgeEntryDraft, KnowledgeIngestionAgent
from cie.knowledge.ingestion_guard import IngestionError, IngestionGuard, InspectionCheck, InspectionResult
from cie.knowledge.parsers.base import DocumentParserRegistry, ParsedDocument
from cie.knowledge.parsers.pymupdf_parser import PlainTextParser

_TXT_CONTENT = b"This is a plain text document about statistical methods. p-value and regression."


def _make_inspection_result(file_bytes: bytes) -> InspectionResult:
    sha = hashlib.sha256(file_bytes).hexdigest()
    check = InspectionCheck(check_name="ok", passed=True, reason="passed", sha256=sha)
    return InspectionResult(
        passed=True, sha256=sha, file_size_bytes=len(file_bytes),
        checks=[check], failed_checks=[],
    )


def _make_agent(tmp_path: Path, guard: IngestionGuard | None = None) -> KnowledgeIngestionAgent:
    if guard is None:
        guard = IngestionGuard()
    registry = DocumentParserRegistry([PlainTextParser()])
    return KnowledgeIngestionAgent(
        ingestion_guard=guard,
        parser_registry=registry,
        pending_dir=tmp_path / "pending",
        source_dir=tmp_path / "source",
    )


@pytest.mark.asyncio
async def test_ingest_valid_txt_creates_draft(tmp_path):
    agent = _make_agent(tmp_path)
    draft = await agent.ingest(Path("study.txt"), _TXT_CONTENT, uploaded_by="researcher@example.com")
    assert isinstance(draft, KnowledgeEntryDraft)
    assert draft.status == "pending_review"
    assert draft.source_filename == "study.txt"


@pytest.mark.asyncio
async def test_ingest_invalid_extension_raises(tmp_path):
    agent = _make_agent(tmp_path)
    with pytest.raises(IngestionError):
        await agent.ingest(Path("malware.exe"), b"binary content", uploaded_by="user@example.com")


@pytest.mark.asyncio
async def test_pending_dir_created_on_ingest(tmp_path):
    agent = _make_agent(tmp_path)
    draft = await agent.ingest(Path("doc.txt"), _TXT_CONTENT, uploaded_by="user@example.com")
    draft_dir = tmp_path / "pending" / draft.draft_id
    assert draft_dir.exists()
    assert (draft_dir / "EXTRACTED.md").exists()
    assert (draft_dir / "SOURCE_HASH.txt").exists()
    assert (draft_dir / "REVIEW_REQUEST.yaml").exists()


@pytest.mark.asyncio
async def test_draft_contains_source_hash(tmp_path):
    agent = _make_agent(tmp_path)
    expected_hash = hashlib.sha256(_TXT_CONTENT).hexdigest()
    draft = await agent.ingest(Path("study.txt"), _TXT_CONTENT, uploaded_by="user@example.com")
    assert draft.source_hash == expected_hash


@pytest.mark.asyncio
async def test_ingestion_guard_called_before_parse(tmp_path):
    call_order: list[str] = []

    mock_guard = MagicMock(spec=IngestionGuard)
    mock_guard.inspect.side_effect = lambda fp, fb: (
        call_order.append("guard") or _make_inspection_result(fb)
    )

    mock_parser = MagicMock(spec=PlainTextParser)
    mock_parser.can_parse.return_value = True
    mock_parser.parse.side_effect = lambda fp, fb: (
        call_order.append("parser")
        or ParsedDocument(
            raw_text="text", structured_markdown="text",
            page_count=1, source_hash=hashlib.sha256(fb).hexdigest(),
            parser_name="plain_text", parser_version="1.0.0",
        )
    )

    registry = DocumentParserRegistry([mock_parser])
    agent = KnowledgeIngestionAgent(
        ingestion_guard=mock_guard,
        parser_registry=registry,
        pending_dir=tmp_path / "pending",
        source_dir=tmp_path / "source",
    )

    await agent.ingest(Path("doc.txt"), _TXT_CONTENT, uploaded_by="user@example.com")

    assert call_order == ["guard", "parser"], (
        f"Expected guard before parser, got: {call_order}"
    )


def test_no_direct_parser_library_import():
    agent_src = (
        Path(__file__).parent.parent.parent / "cie" / "knowledge" / "ingestion_agent.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("pymupdf", "pymupdf4llm", "docx", "fitz"):
        assert forbidden not in agent_src, (
            f"ingestion_agent.py must not import '{forbidden}' directly (ADR-0003)"
        )
