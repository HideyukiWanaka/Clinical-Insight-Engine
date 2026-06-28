from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from cie.core.exceptions import KnowledgeError


@dataclass
class ParsedDocument:
    """Output of any AbstractDocumentParser implementation."""

    raw_text: str
    structured_markdown: str
    page_count: int
    source_hash: str
    parser_name: str
    parser_version: str


class AbstractDocumentParser(ABC):
    """Interface for all document conversion backends.

    Concrete implementations must be dependency-injected; callers must never
    import a concrete parser class directly (ADR-0003, PROJECT_RULES.md S.16).
    """

    @abstractmethod
    def can_parse(self, suffix: str) -> bool:
        """Return True if this parser handles *suffix* (e.g. ``".pdf"``)."""
        ...

    @abstractmethod
    def parse(self, file_path: Path, file_bytes: bytes) -> ParsedDocument:
        """Parse *file_bytes* and return a :class:`ParsedDocument`.

        Library imports must be localised inside this method.
        Raise :class:`~cie.core.exceptions.KnowledgeError` on failure.
        """
        ...

    def get_name(self) -> str:
        """Return the parser identifier (defaults to the class name)."""
        return self.__class__.__name__


class DocumentParserRegistry:
    """Maps file extensions to registered :class:`AbstractDocumentParser` instances.

    Parsers are probed in list order; the first match wins.
    """

    def __init__(self, parsers: list[AbstractDocumentParser]) -> None:
        self._parsers = parsers

    def get_parser(self, suffix: str) -> AbstractDocumentParser:
        """Return the first registered parser that can handle *suffix*.

        Raises:
            KnowledgeError: With ``error_code="NO_PARSER_AVAILABLE"`` when no
                registered parser supports *suffix*.
        """
        for parser in self._parsers:
            if parser.can_parse(suffix):
                return parser
        raise KnowledgeError(
            f"No parser available for extension '{suffix}'.",
            error_code="NO_PARSER_AVAILABLE",
        )
