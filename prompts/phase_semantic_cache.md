# Phase: Semantic Cache — PlannerAgent LLMコスト削減
# File: prompts/phase_semantic_cache.md
# 依存: MVP完了後（Phase 10以降）
# ADR: decisions/ADR-0004.md

---

## 背景と目的

PlannerAgentは毎回LLM APIを呼び出して
自然言語プロンプト → IntentObject へ変換を行っているが、
「A群とB群の比較」のような同一・類似の入力は
毎回同じ結果を返す。

このPhaseでは「使うほどコストが下がる」セマンティックキャッシュを
段階的に実装する。詳細なアーキテクチャ決定はADR-0004を参照すること。

---

## 実装対象ファイル（新規作成）

```
cie/cache/__init__.py
cie/cache/store.py          ← CacheStore（読み書き・統計）
cie/cache/models.py         ← CacheKey・CacheEntry データクラス
cie/cache/normalization.py  ← プロンプト正規化ロジック
```

## 実装対象ファイル（変更）

```
cie/agents/planner.py       ← _execute() にキャッシュ参照・書き込みを追加
agents/planner.yaml         ← CA-001〜006 ルールを behavior_rules に追記
```

---

## SC-1: CacheStore の実装

### `cie/cache/models.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

@dataclass(frozen=True)
class CacheKey:
    normalized_prompt: str
    dataset_fingerprint: str  # SHA-256 of sorted var_N:type pairs

@dataclass
class CacheEntry:
    cache_key: CacheKey
    original_prompts: list[str]   # 同一キーにマッチした元の入力を蓄積
    intent_object: dict
    confidence_score: float
    created_at: datetime
    last_used_at: datetime
    use_count: int
    llm_provider: str
    llm_model: str
```

### `cie/cache/normalization.py`

正規化処理の要件（ADR-0004 Phase 1）:

1. 全角英数字 → 半角
2. 英字 → 小文字
3. 末尾の冗長な助詞・丁寧語を除去
   - 除去対象: `をしたいです` `をしたい` `をしてください` `です` `ます`
4. 連続空白 → 1文字の空白
5. 句読点（。、．，）を除去

実装後にテストすること:
- `「A群とB群の比較をしたいです」` → `「a群とb群の比較」`
- `「A群とB群の比較をしたい」` → `「a群とb群の比較」` (上と同じキー)
- `「治療前後の変化を見たいです」` → `「治療前後の変化を見」`

dataset_fingerprintの生成:
```python
import hashlib, json

def make_dataset_fingerprint(metadata: dict) -> str:
    columns = metadata.get("columns", [])
    # var_nエイリアスと推定型のペアをソートして一意な文字列にする
    pairs = sorted(
        (col.get("var_n", ""), col.get("inferred_type", ""))
        for col in columns
    )
    raw = json.dumps(pairs, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

### `cie/cache/store.py`

**ストレージ:**
- `cie/cache/planner_cache.json` — キャッシュ本体
- `cie/cache/cache_stats.json` — 統計（ヒット数・ミス数）

**必須メソッド:**

```python
class CacheStore:
    def make_key(self, prompt: str, dataset_metadata: dict) -> CacheKey: ...
    def get(self, key: CacheKey) -> CacheEntry | None: ...
    def put(self, key: CacheKey, original_prompt: str, intent_object: dict,
            confidence_score: float, llm_provider: str, llm_model: str) -> None: ...
    def record_hit(self, key: CacheKey) -> None: ...
    def get_stats(self) -> dict: ...  # UIに渡す統計データ
    def delete(self, key_hash: str) -> None: ...  # UIから手動削除
    def clear_all(self) -> None: ...
```

**キャッシュしない条件（CA-002, CA-003）:**
```python
def should_cache(self, confidence_score: float, requires_clarification: bool) -> bool:
    if confidence_score < 0.7:
        return False
    if requires_clarification:
        return False
    return True
```

---

## SC-2: PlannerAgent への組み込み

`cie/agents/planner.py` の `__init__` にCacheStoreを依存注入として追加する。

```python
def __init__(
    self,
    policy_engine: PolicyEngine,
    schema_registry: SchemaRegistry,
    audit_service: AuditService,
    context_guard: ContextGuard,
    llm_client: LLMClient,
    cache_store: CacheStore | None = None,  # Noneの場合はキャッシュ無効
) -> None:
```

`_execute()` の変更箇所（ADR-0004の組み込み方針を参照）:

```python
# PII チェックの直後、LLM呼び出しの直前に挿入
if self._cache_store is not None:
    cache_key = self._cache_store.make_key(user_prompt, dataset_metadata)
    cached = self._cache_store.get(cache_key)
    if cached is not None:
        self._cache_store.record_hit(cache_key)
        await self._write_cache_hit_audit(agent_input, cache_key)
        return self._build_output_from_cache(agent_input, cached)

# ... LLM呼び出し（既存コード）...

# LLM呼び出し成功後、return の直前に挿入
if self._cache_store is not None:
    if self._cache_store.should_cache(confidence_score, requires_clarification):
        self._cache_store.put(
            key=cache_key,
            original_prompt=user_prompt,
            intent_object=intent_obj,
            confidence_score=confidence_score,
            llm_provider=self._llm_client.provider,
            llm_model=self._llm_client.model,
        )
```

**CA-001 準拠のAudit記録:**
```python
async def _write_cache_hit_audit(self, agent_input: AgentInput, cache_key: CacheKey) -> None:
    await self._audit_service.write(AuditEvent(
        execution_id=agent_input.execution_id,
        agent_id=self.agent_id,
        action="CACHE_HIT",
        status="success",
        severity=AuditEventSeverity.INFO,
        payload={
            "normalized_prompt": cache_key.normalized_prompt,
            "dataset_fingerprint": cache_key.dataset_fingerprint,
        },
    ))
```

---

## SC-3: UI統計表示

設定画面（`cie/ui/screens/settings.py`）にキャッシュ統計を追加する。

`CacheStore.get_stats()` が返すデータ:
```python
{
    "total_requests": 42,
    "cache_hits": 28,
    "hit_rate": 0.667,
    "saved_api_calls": 28,
    "top_cached_prompts": [
        {"normalized_prompt": "a群とb群の比較", "use_count": 15},
        {"normalized_prompt": "治療前後の変化を見", "use_count": 8},
    ]
}
```

---

## SC-4: SYNONYM_MAP の構築（Phase 2）

`cie/cache/normalization.py` に追加する辞書。

初期値（実績から随時追加）:
```python
SYNONYM_MAP: dict[str, str] = {
    "比べたい": "比較したい",
    "差を見たい": "比較したい",
    "違いを調べたい": "比較したい",
    "差異": "差",
    "ビフォーアフター": "前後",
    "before after": "前後",
    "介入前後": "前後",
    "治療前後": "前後",
    "関係を見たい": "相関を調べたい",
    "関連を見たい": "相関を調べたい",
    "relate": "相関",
    "correlation": "相関",
    "compare": "比較",
}
```

SYNONYM_MAPの適用は正規化の最後のステップとして行う。

---

## テスト要件

### 単体テスト（tests/unit/test_cache_store.py）

- [ ] 同一プロンプト・同一データで2回目はキャッシュヒット
- [ ] 異なる表記（「比較したい」「比べたい」）が同じキーになる（Phase 2以降）
- [ ] dataset_fingerprintが異なればキャッシュミス
- [ ] confidence < 0.7 はキャッシュされない（CA-002）
- [ ] requires_clarification=True はキャッシュされない（CA-003）
- [ ] LLMモデルが異なるエントリは別管理（CA-005）
- [ ] `clear_all()` 後はヒットしない

### 統合テスト

- [ ] PlannerAgentにCacheStoreを注入してキャッシュヒット時にLLMが呼ばれないことを確認
- [ ] cache_store=None の場合は従来と同じ動作（キャッシュ無効化オプション）

---

## 実装上の注意

- `planner_cache.json` は git の追跡対象から外す（`.gitignore` に追加）
  → キャッシュは施設固有の運用データであり、リポジトリに含めない
- ファイルの読み書きは `filelock` または `threading.Lock` で排他制御する
  （Streamlitの非同期再レンダリングによる競合を防ぐ）
- キャッシュファイルが壊れている場合は例外を出さずに
  空のキャッシュとして初期化し、ログに警告を出す
