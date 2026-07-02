"""Unit tests for cie.cache — CacheStore, normalization, models (ADR-0004).

Test matrix (prompts/phase_semantic_cache.md):
- 同一プロンプト・同一データで2回目はキャッシュヒット
- 異なる表記（「比較したい」「比べたい」）が同じキーになる（Phase 2）
- dataset_fingerprint が異なればキャッシュミス（CA-006）
- confidence < 0.7 はキャッシュされない（CA-002）
- requires_clarification=True はキャッシュされない（CA-003）
- LLMモデルが異なるエントリは別管理（CA-005）
- clear_all() 後はヒットしない
- delete() で個別エントリを物理削除できる（CA-004）
- 壊れたキャッシュファイルは空として初期化される
- 正規化ルール（全角→半角・小文字化・助詞除去・句読点除去）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cie.cache.normalization import make_dataset_fingerprint, normalize_prompt
from cie.cache.store import CacheStore

# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

METADATA_A = {
    "columns": [
        {"var_n": "var_1", "inferred_type": "continuous"},
        {"var_n": "var_2", "inferred_type": "categorical_binary"},
    ]
}
METADATA_B = {
    "columns": [
        {"var_n": "var_1", "inferred_type": "categorical_nominal"},
    ]
}

INTENT = {"objective": "between_group_comparison", "outcome_type": "continuous"}


@pytest.fixture
def store(tmp_path: Path) -> CacheStore:
    return CacheStore(cache_dir=tmp_path)


def _put(store: CacheStore, prompt: str, metadata: dict = METADATA_A,
         model: str = "model-x", provider: str = "anthropic") -> None:
    key = store.make_key(prompt, metadata)
    store.put(
        key=key,
        original_prompt=prompt,
        intent_object=INTENT,
        confidence_score=0.9,
        llm_provider=provider,
        llm_model=model,
    )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:

    def test_polite_suffix_removed(self) -> None:
        assert normalize_prompt("A群とB群の比較をしたいです") == "a群とb群の比較"

    def test_same_key_for_variants(self) -> None:
        assert (
            normalize_prompt("A群とB群の比較をしたい")
            == normalize_prompt("A群とB群の比較をしたいです")
        )

    def test_volitional_suffix_removed(self) -> None:
        # 「治療前後」は SYNONYM_MAP（Phase 2）で「前後」に正規化される
        assert normalize_prompt("治療前後の変化を見たいです") == "前後の変化を見"

    def test_fullwidth_and_punctuation(self) -> None:
        assert normalize_prompt("ＡＢＣ群の比較。") == "abc群の比較"

    def test_synonym_map_unifies_variants(self) -> None:
        assert normalize_prompt("A群とB群を比べたい") == normalize_prompt(
            "A群とB群を比較したい"
        )

    def test_whitespace_collapsed(self) -> None:
        assert normalize_prompt("a   b\t c") == "a b c"


class TestDatasetFingerprint:

    def test_stable_regardless_of_column_order(self) -> None:
        reordered = {"columns": list(reversed(METADATA_A["columns"]))}
        assert make_dataset_fingerprint(METADATA_A) == make_dataset_fingerprint(reordered)

    def test_differs_for_different_structure(self) -> None:
        assert make_dataset_fingerprint(METADATA_A) != make_dataset_fingerprint(METADATA_B)

    def test_mapping_form_supported(self) -> None:
        mapping = {
            "var_1": {"inferred_type": "continuous"},
            "var_2": {"inferred_type": "categorical_binary"},
        }
        assert make_dataset_fingerprint(mapping) == make_dataset_fingerprint(
            dict(reversed(list(mapping.items())))
        )


# ---------------------------------------------------------------------------
# CacheStore behaviour
# ---------------------------------------------------------------------------


class TestCacheStore:

    def test_second_lookup_hits(self, store: CacheStore) -> None:
        prompt = "A群とB群の比較をしたいです"
        key = store.make_key(prompt, METADATA_A)
        assert store.get(key, "anthropic", "model-x") is None  # first: miss
        _put(store, prompt)
        entry = store.get(key, "anthropic", "model-x")
        assert entry is not None
        assert entry.intent_object == INTENT

    def test_notation_variants_share_entry(self, store: CacheStore) -> None:
        _put(store, "A群とB群を比較したいです")
        key = store.make_key("A群とB群を比べたい", METADATA_A)
        assert store.get(key, "anthropic", "model-x") is not None

    def test_different_fingerprint_misses(self, store: CacheStore) -> None:
        prompt = "A群とB群の比較をしたいです"
        _put(store, prompt, metadata=METADATA_A)
        key_b = store.make_key(prompt, METADATA_B)
        assert store.get(key_b, "anthropic", "model-x") is None  # CA-006

    def test_low_confidence_not_cached(self, store: CacheStore) -> None:
        assert store.should_cache(0.69, requires_clarification=False) is False  # CA-002
        assert store.should_cache(0.7, requires_clarification=False) is True

    def test_clarification_not_cached(self, store: CacheStore) -> None:
        assert store.should_cache(0.95, requires_clarification=True) is False  # CA-003

    def test_models_managed_separately(self, store: CacheStore) -> None:
        prompt = "A群とB群の比較をしたいです"
        _put(store, prompt, model="model-x")
        key = store.make_key(prompt, METADATA_A)
        assert store.get(key, "anthropic", "model-y") is None  # CA-005
        assert store.get(key, "anthropic", "model-x") is not None

    def test_clear_all_empties_cache(self, store: CacheStore) -> None:
        prompt = "A群とB群の比較をしたいです"
        _put(store, prompt)
        store.clear_all()
        key = store.make_key(prompt, METADATA_A)
        assert store.get(key, "anthropic", "model-x") is None

    def test_delete_removes_single_entry(self, store: CacheStore) -> None:
        _put(store, "A群とB群の比較をしたいです")
        _put(store, "生存解析をしたいです")
        stats = store.get_stats()
        assert stats["entry_count"] == 2
        store.delete(stats["top_cached_prompts"][0]["key_hash"])  # CA-004
        assert store.get_stats()["entry_count"] == 1

    def test_original_prompts_accumulate(self, store: CacheStore) -> None:
        _put(store, "A群とB群を比較したいです")
        _put(store, "A群とB群を比べたい")
        key = store.make_key("A群とB群を比較したい", METADATA_A)
        entry = store.get(key, "anthropic", "model-x")
        assert entry is not None
        assert entry.original_prompts == ["A群とB群を比較したいです", "A群とB群を比べたい"]

    def test_stats_track_hits_and_misses(self, store: CacheStore) -> None:
        prompt = "A群とB群の比較をしたいです"
        key = store.make_key(prompt, METADATA_A)
        store.get(key, "anthropic", "model-x")  # miss
        _put(store, prompt)
        store.get(key, "anthropic", "model-x")  # hit lookup
        store.record_hit(key, "anthropic", "model-x")
        stats = store.get_stats()
        assert stats["cache_hits"] == 1
        assert stats["total_requests"] == 2
        assert stats["saved_api_calls"] == 1
        assert stats["hit_rate"] == 0.5
        assert stats["top_cached_prompts"][0]["use_count"] == 1

    def test_corrupted_cache_file_treated_as_empty(self, tmp_path: Path) -> None:
        (tmp_path / "planner_cache.json").write_text("{not json", encoding="utf-8")
        store = CacheStore(cache_dir=tmp_path)
        key = store.make_key("何かの解析", METADATA_A)
        assert store.get(key, "anthropic", "model-x") is None  # no exception
        _put(store, "何かの解析")
        assert store.get(key, "anthropic", "model-x") is not None
