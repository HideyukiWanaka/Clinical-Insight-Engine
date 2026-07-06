"""CIE Platform — Local embedding index for Knowledge retrieval (ADR-0005).

Scaffolding only. Implements no retrieval logic yet — see
spec/knowledge/embedding-rag-spec.md for the design this module will
follow in Phase 1+:

- Index ``knowledge/official/**/*.md`` plus approved ``institutional/``
  entries into a file-based, offline vector store.
- Expose ``EmbeddingReferenceLibrary.retrieve(query_terms, top_k)`` with
  the same signature as
  :meth:`cie.knowledge.reference_library.MarkdownReferenceLibrary.retrieve`,
  so callers in ``cie/agents/statistics.py``, ``visualization.py``, and
  ``reporting.py`` can be switched via dependency injection without
  changes to call sites.
- Embedding model runs fully offline (offline_first_mode); no document
  text is sent to an external service. Only the retrieval model is
  local — the R-code-generating LLM remains the existing cloud model.
"""

from __future__ import annotations

from pathlib import Path

from cie.knowledge.reference_library import ReferenceDoc


class EmbeddingReferenceLibrary:
    """Local-embedding-backed replacement for ``MarkdownReferenceLibrary``.

    Not yet implemented (Phase 0 scaffolding). See
    spec/knowledge/embedding-rag-spec.md Section 2.
    """

    def __init__(self, knowledge_root: Path | str) -> None:
        self._root = Path(knowledge_root)
        raise NotImplementedError("EmbeddingReferenceLibrary is scaffolded in Phase 0; implemented in Phase 1+.")

    def retrieve(self, query_terms: list[str], top_k: int = 3) -> list[ReferenceDoc]:
        """Return the *top_k* docs most semantically similar to *query_terms*."""
        raise NotImplementedError("EmbeddingReferenceLibrary is scaffolded in Phase 0; implemented in Phase 1+.")
