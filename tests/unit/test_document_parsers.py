from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cie.core.exceptions import KnowledgeError
from cie.knowledge.parsers.base import DocumentParserRegistry, ParsedDocument
from cie.knowledge.parsers.pymupdf_parser import PlainTextParser, PyMuPDFParser

_MD_BYTES = b"# Title\n\nSome content."
_TXT_BYTES = b"Plain text content."


def test_plain_text_parser_can_parse_md():
    assert PlainTextParser().can_parse(".md") is True


def test_plain_text_parser_can_parse_txt():
    assert PlainTextParser().can_parse(".txt") is True


def test_plain_text_parser_cannot_parse_pdf():
    assert PlainTextParser().can_parse(".pdf") is False


def test_plain_text_parser_returns_parsed_document():
    result = PlainTextParser().parse(Path("doc.md"), _MD_BYTES)
    assert isinstance(result, ParsedDocument)
    assert "Title" in result.raw_text
    assert result.page_count == 1
    assert result.parser_name == "plain_text"


def test_plain_text_source_hash_consistent():
    parser = PlainTextParser()
    r1 = parser.parse(Path("a.txt"), _TXT_BYTES)
    r2 = parser.parse(Path("b.txt"), _TXT_BYTES)
    expected = hashlib.sha256(_TXT_BYTES).hexdigest()
    assert r1.source_hash == expected
    assert r2.source_hash == expected


def test_registry_selects_correct_parser():
    registry = DocumentParserRegistry([PlainTextParser(), PyMuPDFParser()])
    assert isinstance(registry.get_parser(".md"), PlainTextParser)
    assert isinstance(registry.get_parser(".txt"), PlainTextParser)
    assert isinstance(registry.get_parser(".pdf"), PyMuPDFParser)


def test_registry_raises_for_unknown_suffix():
    registry = DocumentParserRegistry([PlainTextParser()])
    with pytest.raises(KnowledgeError) as exc_info:
        registry.get_parser(".docx")
    assert exc_info.value.error_code == "NO_PARSER_AVAILABLE"


def test_pymupdf_parser_can_parse_pdf():
    assert PyMuPDFParser().can_parse(".pdf") is True
