"""Phase 5 (R5-1) E2E harness — local embedding RAG, offline verification.

Run: python scratchpad/harness_embedding_rag.py

Checks:
  1. Index knowledge/official/**/*.md with a socket guard installed
     (proves indexing performs ZERO external communication — offline_first).
  2. Semantic query "Mann-Whitney U test / wilcox.test" surfaces the right
     reference doc at the top.
  3. Notation-variant query ("mann_whitney_u_test" vs "Mann-Whitney") still hits
     the same reference — before/after vs the keyword retriever.
  4. StatisticsAgent._generate_r_script runs with the swapped-in retriever and
     records the references in provenance["knowledge_references"].
"""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cie.knowledge.embedding_index import EmbeddingReferenceLibrary  # noqa: E402
from cie.knowledge.reference_library import MarkdownReferenceLibrary  # noqa: E402

KNOWLEDGE_ROOT = ROOT / "knowledge"
STORE = ROOT / "scratchpad" / "_rag_store" / "index.json"


class _NoNetwork:
    """Context manager that makes any socket connection raise (offline proof)."""

    def __enter__(self):
        self._orig_connect = socket.socket.connect
        self._orig_connect_ex = socket.socket.connect_ex

        def _blocked(*_a, **_k):
            raise AssertionError("external network access attempted during RAG op")

        socket.socket.connect = _blocked  # type: ignore[method-assign]
        socket.socket.connect_ex = _blocked  # type: ignore[method-assign]
        return self

    def __exit__(self, *_exc):
        socket.socket.connect = self._orig_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = self._orig_connect_ex  # type: ignore[method-assign]


def _titles(docs) -> list[str]:
    return [d.title for d in docs]


def _paths(docs) -> list[str]:
    return [Path(d.path).name for d in docs]


def main() -> int:
    ok = True

    # --- 1. Build index fully offline -------------------------------------
    if STORE.exists():
        STORE.unlink()
    with _NoNetwork():
        lib = EmbeddingReferenceLibrary(KNOWLEDGE_ROOT, store_path=STORE)
        print(f"[1] indexed {len(lib.docs)} chunks offline; store -> {STORE}")
        assert len(lib.docs) > 0, "no chunks indexed"
        assert STORE.exists(), "vector store was not persisted"

        # --- 2. Canonical semantic query ---------------------------------
        q1 = ["Mann-Whitney U test", "wilcox.test"]
        r1 = lib.retrieve(q1, top_k=4)
        print(f"[2] query {q1} -> {_paths(r1)}")
        assert r1, "no results for canonical query"
        assert _paths(r1)[0] == "comparison_correlation_reference.md", (
            f"expected comparison_correlation_reference.md first, got {_paths(r1)}"
        )

        # --- 3. Notation-variant robustness: before/after ----------------
        variant = ["mann_whitney_u_test"]
        emb_hit = lib.retrieve(variant, top_k=4)
        kw = MarkdownReferenceLibrary(KNOWLEDGE_ROOT)
        kw_hit = kw.retrieve(variant, top_k=4)
        print(f"[3] variant {variant}")
        print(f"    embedding -> {_paths(emb_hit)}")
        print(f"    keyword   -> {_paths(kw_hit)}")
        assert emb_hit, "embedding retriever missed the notation variant"
        assert "comparison_correlation_reference.md" in _paths(emb_hit), (
            "embedding retriever did not surface the correct doc for the variant"
        )
        # The literal token 'mann_whitney_u_test' appears in the reference, so the
        # keyword method may also hit; the embedding win is robustness across
        # separators, shown next.
        sep_variant = ["Mann Whitney", "rank sum comparison of two groups"]
        emb_sep = lib.retrieve(sep_variant, top_k=4)
        kw_sep = kw.retrieve(sep_variant, top_k=4)
        print(f"    sep-variant {sep_variant}")
        print(f"    embedding -> {_paths(emb_sep)}")
        print(f"    keyword   -> {_paths(kw_sep)}")
        assert "comparison_correlation_reference.md" in _paths(emb_sep), (
            "embedding retriever failed on separator/paraphrase variant"
        )

        # --- 4. 0-hit query returns empty list ---------------------------
        empty = lib.retrieve([], top_k=4)
        assert empty == [], "empty query_terms must yield []"
        print("[4] empty query_terms -> [] (no grounding requested)")

    # --- 5. StatisticsAgent integration with swapped retriever ------------
    asyncio.run(_statistics_integration(lib))
    print("\nALL CHECKS PASSED" if ok else "\nFAILURES ABOVE")
    return 0 if ok else 1


async def _statistics_integration(lib: EmbeddingReferenceLibrary) -> None:
    from cie.agents.statistics import StatisticsAgent

    class _StubLLM:
        provider = "stub"
        model = "stub-1"

        async def complete(self, system, user, assistant_prefill=""):
            # Confirm the reference block reached the prompt.
            assert "KNOWLEDGE REFERENCE PATTERNS" in user
            assert "Mann-Whitney" in user or "wilcox" in user.lower()
            return "```r\nset.seed(42)\nresult <- wilcox.test(value ~ group)\n```"

    agent = StatisticsAgent(
        policy_engine=None,
        schema_registry=None,
        audit_service=None,
        llm_client=_StubLLM(),
        reference_library=lib,
        script_cache=None,
        skill_loader=None,
    )
    method = {
        "method_id": "mann_whitney_u",
        "r_function": "wilcox.test",
        "r_packages": [],
        "effect_size_measure": "rank-biserial",
    }
    intent = {"objective": "between_group_comparison", "outcome_type": "continuous"}
    payload = {"dataset_structural_metadata": {"columns": ["group", "value"]}}
    with _NoNetwork():
        script, provenance = await agent._generate_r_script(method, intent, payload)
    print(f"[5] provenance.knowledge_references = {provenance['knowledge_references']}")
    assert script is not None, "expected a generated R script from stub LLM"
    assert provenance["knowledge_references"], "no references recorded in provenance"


if __name__ == "__main__":
    raise SystemExit(main())
