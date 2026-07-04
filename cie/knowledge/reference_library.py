"""CIE Platform — Markdown knowledge reference library (RAG source).

The structured KnowledgeLoader reads METADATA.yaml-described entries. The rich
R implementation patterns, however, live in the Markdown reference files under
``knowledge/official/`` (e.g. ``statistics/comparison_correlation_reference.md``).
This module loads those Markdown files directly and offers lightweight keyword
retrieval so the Statistics Agent can ground LLM-generated R scripts in the
documented reference patterns (RAG).

This is deliberately simple (no embeddings): reference docs are few and their
titles/bodies contain the method names, so keyword overlap scoring is enough to
surface the right reference(s) for a chosen statistical method.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReferenceDoc:
    """One Markdown reference document."""

    title: str
    domain: str
    path: Path
    content: str

    def excerpt(self, max_chars: int = 4000) -> str:
        """Return the content, truncated to *max_chars* for prompt budgeting."""
        if len(self.content) <= max_chars:
            return self.content
        return self.content[:max_chars] + "\n... [truncated] ..."


_TITLE_RE = re.compile(r"^#\s+(.*\S)\s*$", re.MULTILINE)
_DOMAIN_RE = re.compile(r"^#\s*Domain:\s*(.+?)\s*$", re.MULTILINE)
_TOKEN_RE = re.compile(r"[a-z0-9_.]+")


class MarkdownReferenceLibrary:
    """Loads and retrieves Markdown reference docs under a knowledge root.

    Args:
        knowledge_root: Directory containing the ``official/`` (and optionally
            ``institutional/``) Markdown reference tree.
        subdirs: Restrict loading to these sub-paths (relative to
            ``official/``). Defaults to the statistics + R references that the
            Statistics Agent needs.
    """

    def __init__(
        self,
        knowledge_root: Path | str,
        subdirs: tuple[str, ...] = ("statistics", "R"),
    ) -> None:
        self._root = Path(knowledge_root)
        self._subdirs = subdirs
        self._docs: list[ReferenceDoc] = []
        self._load()

    def _load(self) -> None:
        official = self._root / "official"
        search_dirs = [official / sd for sd in self._subdirs] or [official]
        for base in search_dirs:
            if not base.exists():
                continue
            for md_path in sorted(base.rglob("*.md")):
                try:
                    text = md_path.read_text(encoding="utf-8")
                except OSError:
                    continue
                title_match = _TITLE_RE.search(text)
                domain_match = _DOMAIN_RE.search(text)
                self._docs.append(
                    ReferenceDoc(
                        title=title_match.group(1) if title_match else md_path.stem,
                        domain=domain_match.group(1) if domain_match else "unknown",
                        path=md_path,
                        content=text,
                    )
                )

    @property
    def docs(self) -> list[ReferenceDoc]:
        return list(self._docs)

    def retrieve(self, query_terms: list[str], top_k: int = 2) -> list[ReferenceDoc]:
        """Return the *top_k* docs most relevant to *query_terms*.

        Scoring is keyword-overlap: each query term contributes its total
        occurrence count in a doc (title weighted higher). Docs with zero
        matches are excluded. Ties break by title for determinism.
        """
        normalized = [t.lower() for t in query_terms if t]
        if not normalized:
            return []

        scored: list[tuple[float, str, ReferenceDoc]] = []
        for doc in self._docs:
            body = doc.content.lower()
            title = doc.title.lower()
            score = 0.0
            for term in normalized:
                score += body.count(term)
                score += title.count(term) * 5  # title matches weigh more
            if score > 0:
                scored.append((score, doc.title, doc))

        scored.sort(key=lambda s: (-s[0], s[1]))
        return [doc for _, _, doc in scored[:top_k]]
