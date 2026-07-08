"""Phase 5 (R5-1) — local embedding retriever regression tests.

Covers spec/knowledge/embedding-rag-spec.md §2: semantic retrieval, notation
variant robustness (the before/after win over keyword search), the empty-query
contract, ReferenceDoc parity, offline persistence and reindex.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cie.knowledge.embedding_index import (
    EmbeddingReferenceLibrary,
    TfidfVectorizer,
    chunk_markdown,
)
from cie.knowledge.reference_library import MarkdownReferenceLibrary, ReferenceDoc

KNOWLEDGE_ROOT = Path("knowledge")


@pytest.fixture()
def library(tmp_path) -> EmbeddingReferenceLibrary:
    # Persist the store under tmp_path so the real knowledge tree stays clean.
    return EmbeddingReferenceLibrary(
        KNOWLEDGE_ROOT, store_path=tmp_path / "index.json"
    )


def _names(docs: list[ReferenceDoc]) -> list[str]:
    return [Path(d.path).name for d in docs]


def test_retrieve_returns_reference_docs(library):
    docs = library.retrieve(["Mann-Whitney U test", "wilcox.test"], top_k=4)
    assert docs, "expected results for a canonical statistical query"
    assert all(isinstance(d, ReferenceDoc) for d in docs)
    # Same 4-part contract as MarkdownReferenceLibrary: .title / .excerpt().
    assert docs[0].title
    assert docs[0].excerpt(200)


def test_semantic_query_surfaces_correct_doc(library):
    docs = library.retrieve(["Mann-Whitney U test", "wilcox.test"], top_k=4)
    assert _names(docs)[0] == "comparison_correlation_reference.md"


def test_notation_variant_beats_keyword(library):
    """The embedding retriever hits on a separator/paraphrase variant that the
    keyword retriever misses entirely (before/after)."""
    variant = ["Mann Whitney", "rank sum comparison of two groups"]
    emb = library.retrieve(variant, top_k=4)
    kw = MarkdownReferenceLibrary(KNOWLEDGE_ROOT).retrieve(variant, top_k=4)

    assert "comparison_correlation_reference.md" in _names(emb)
    # Keyword scoring cannot bridge the separators / paraphrase.
    assert "comparison_correlation_reference.md" not in _names(kw)


def test_empty_query_returns_empty_list(library):
    assert library.retrieve([], top_k=4) == []
    assert library.retrieve([""], top_k=4) == []


def test_top_k_is_respected(library):
    docs = library.retrieve(["regression", "linear model", "coefficient"], top_k=2)
    assert len(docs) <= 2


def test_dedup_one_chunk_per_document(library):
    docs = library.retrieve(["ggplot2", "boxplot", "chart"], top_k=5)
    paths = [str(d.path) for d in docs]
    assert len(paths) == len(set(paths)), "results must be de-duplicated by source path"


def test_store_is_persisted_and_reloaded(tmp_path):
    store = tmp_path / "index.json"
    lib1 = EmbeddingReferenceLibrary(KNOWLEDGE_ROOT, store_path=store)
    assert store.exists()
    first = _names(lib1.retrieve(["survival analysis", "Cox proportional hazards"], top_k=3))

    # A second instance must load from the persisted store (same manifest) and
    # return identical results.
    lib2 = EmbeddingReferenceLibrary(KNOWLEDGE_ROOT, store_path=store)
    second = _names(lib2.retrieve(["survival analysis", "Cox proportional hazards"], top_k=3))
    assert first == second


def test_reindex_returns_chunk_count(library):
    count = library.reindex()
    assert count == len(library.docs) > 0


def test_chunk_markdown_splits_on_headings():
    text = "# Title\n\nintro\n\n## A\n\nalpha body\n\n## B\n\nbeta body\n"
    chunks = chunk_markdown(text)
    headings = [h for h, _ in chunks]
    assert "A" in headings and "B" in headings


def test_chunk_markdown_headingless_returns_one_chunk():
    chunks = chunk_markdown("just some prose with no headings at all")
    assert len(chunks) == 1


def test_tfidf_downweights_common_terms():
    vec = TfidfVectorizer().fit(
        ["the wilcox test", "the anova test", "the regression test"]
    )
    # "the" and "test" appear in every doc -> lower idf than the distinctive "wilcox".
    assert vec.idf["w:wilcox"] > vec.idf["w:test"]
    assert vec.idf["w:wilcox"] > vec.idf["w:the"]
