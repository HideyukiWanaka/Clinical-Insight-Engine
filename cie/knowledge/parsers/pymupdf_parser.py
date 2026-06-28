from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from cie.core.exceptions import KnowledgeError
from cie.knowledge.parsers.base import AbstractDocumentParser, ParsedDocument


class PyMuPDFParser(AbstractDocumentParser):
    """PDF parser backed by pymupdf4llm (AGPL-3.0).

    This is the only module that imports pymupdf4llm.
    KnowledgeIngestionAgent depends solely on AbstractDocumentParser and must
    never reference this class by name (ADR-0003, PROJECT_RULES.md S.16).
    """

    PARSER_NAME = "pymupdf4llm"
    PARSER_VERSION = "0.0.17"

    def can_parse(self, suffix: str) -> bool:
        return suffix.lower() == ".pdf"

    def get_name(self) -> str:
        return self.PARSER_NAME

    def parse(self, file_path: Path, file_bytes: bytes) -> ParsedDocument:
        try:
            import pymupdf4llm  # localised import — do not hoist to module level
        except ImportError as exc:
            raise KnowledgeError(
                "pymupdf4llm is not installed. "
                "Install the 'pdf' optional dependency: pip install cie-platform[pdf]",
                error_code="PARSER_DEPENDENCY_MISSING",
            ) from exc

        source_hash = hashlib.sha256(file_bytes).hexdigest()

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = Path(tmp.name)

            try:
                md_text: str = pymupdf4llm.to_markdown(str(tmp_path))
            except Exception as exc:
                raise KnowledgeError(
                    f"pymupdf4llm failed to parse '{file_path.name}': {exc}",
                    error_code="PARSER_FAILURE",
                ) from exc

            import pymupdf  # bundled with pymupdf4llm

            with pymupdf.open(str(tmp_path)) as doc:
                page_count: int = doc.page_count
                raw_text: str = "\n".join(page.get_text() for page in doc)

        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink()

        return ParsedDocument(
            raw_text=raw_text,
            structured_markdown=md_text,
            page_count=page_count,
            source_hash=source_hash,
            parser_name=self.PARSER_NAME,
            parser_version=self.PARSER_VERSION,
        )


class PlainTextParser(AbstractDocumentParser):
    """.md and .txt parser requiring no third-party libraries."""

    PARSER_NAME = "plain_text"
    PARSER_VERSION = "1.0.0"

    def can_parse(self, suffix: str) -> bool:
        return suffix.lower() in {".md", ".txt"}

    def get_name(self) -> str:
        return self.PARSER_NAME

    def parse(self, file_path: Path, file_bytes: bytes) -> ParsedDocument:
        source_hash = hashlib.sha256(file_bytes).hexdigest()
        text = file_bytes.decode("utf-8", errors="replace")
        return ParsedDocument(
            raw_text=text,
            structured_markdown=text,
            page_count=1,
            source_hash=source_hash,
            parser_name=self.PARSER_NAME,
            parser_version=self.PARSER_VERSION,
        )
