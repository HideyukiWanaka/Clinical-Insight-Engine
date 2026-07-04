"""CIE Platform — CacheStore: JSON-backed semantic cache (ADR-0004).

Storage layout (both files live next to this module by default):
    planner_cache.json — {"version": "1.0", "entries": {<hash>: <entry>}}
    cache_stats.json   — {"cache_hits": int, "cache_misses": int}

Governance rules enforced here:
    CA-002 / CA-003 — should_cache() rejects low-confidence and
                      clarification-required results.
    CA-004          — delete() / clear_all() physically remove entries.
    CA-005          — the storage hash includes llm_provider + llm_model,
                      so entries are never shared across models.
    CA-006          — dataset_fingerprint is part of CacheKey.

All file access is serialized with a threading.Lock to survive
Streamlit's concurrent re-renders. A corrupted cache file is treated as
empty (warning logged), never raised.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from cie.cache.models import CacheEntry, CacheKey
from cie.cache.normalization import make_dataset_fingerprint, normalize_prompt

_log = logging.getLogger(__name__)

_CACHE_VERSION = "1.0"
_MIN_CONFIDENCE = 0.7  # CA-002


class CacheStore:
    """Read/write access to the Planner semantic cache and its statistics.

    Args:
        cache_dir: Directory holding ``planner_cache.json`` and
            ``cache_stats.json``. Defaults to this module's directory
            (``cie/cache/``).
    """

    def __init__(self, cache_dir: Path | str | None = None) -> None:
        base = Path(cache_dir) if cache_dir is not None else Path(__file__).parent
        base.mkdir(parents=True, exist_ok=True)
        self._cache_path = base / "planner_cache.json"
        self._stats_path = base / "cache_stats.json"
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Key construction
    # ------------------------------------------------------------------

    def make_key(self, prompt: str, dataset_metadata: dict) -> CacheKey:
        return CacheKey(
            normalized_prompt=normalize_prompt(prompt),
            dataset_fingerprint=make_dataset_fingerprint(dataset_metadata or {}),
        )

    @staticmethod
    def _entry_hash(key: CacheKey, llm_provider: str, llm_model: str) -> str:
        # CA-005: provider/model are part of the storage identity.
        raw = "\n".join(
            [key.normalized_prompt, key.dataset_fingerprint, llm_provider, llm_model]
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    def get(
        self,
        key: CacheKey,
        llm_provider: str = "",
        llm_model: str = "",
    ) -> CacheEntry | None:
        """Look up an entry; a miss is counted in the statistics."""
        with self._lock:
            entries = self._load_cache()["entries"]
            raw = entries.get(self._entry_hash(key, llm_provider, llm_model))
            if raw is None:
                self._bump_stat("cache_misses")
                return None
            return self._entry_from_dict(raw)

    def put(
        self,
        key: CacheKey,
        original_prompt: str,
        intent_object: dict,
        confidence_score: float,
        llm_provider: str,
        llm_model: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            data = self._load_cache()
            entry_hash = self._entry_hash(key, llm_provider, llm_model)
            existing = data["entries"].get(entry_hash)
            if existing is not None:
                prompts = existing.get("original_prompts", [])
                if original_prompt not in prompts:
                    prompts.append(original_prompt)
                existing["original_prompts"] = prompts
                existing["intent_object"] = intent_object
                existing["confidence_score"] = confidence_score
            else:
                entry = CacheEntry(
                    cache_key=key,
                    original_prompts=[original_prompt],
                    intent_object=intent_object,
                    confidence_score=confidence_score,
                    created_at=now,
                    last_used_at=now,
                    use_count=0,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                )
                data["entries"][entry_hash] = self._entry_to_dict(entry)
            self._save_cache(data)

    def record_hit(
        self,
        key: CacheKey,
        llm_provider: str = "",
        llm_model: str = "",
    ) -> None:
        with self._lock:
            data = self._load_cache()
            raw = data["entries"].get(self._entry_hash(key, llm_provider, llm_model))
            if raw is not None:
                raw["use_count"] = int(raw.get("use_count", 0)) + 1
                raw["last_used_at"] = datetime.now(timezone.utc).isoformat()
                self._save_cache(data)
            self._bump_stat("cache_hits")

    # ------------------------------------------------------------------
    # Governance (CA-002 / CA-003)
    # ------------------------------------------------------------------

    def should_cache(
        self, confidence_score: float, requires_clarification: bool
    ) -> bool:
        if confidence_score < _MIN_CONFIDENCE:
            return False
        if requires_clarification:
            return False
        return True

    # ------------------------------------------------------------------
    # Statistics & management (SC-3 / CA-004)
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Statistics payload for the settings UI."""
        with self._lock:
            stats = self._load_stats()
            entries = self._load_cache()["entries"]
        hits = stats.get("cache_hits", 0)
        misses = stats.get("cache_misses", 0)
        total = hits + misses
        top = sorted(
            (
                {
                    "key_hash": entry_hash,
                    "normalized_prompt": raw["cache_key"]["normalized_prompt"],
                    "use_count": int(raw.get("use_count", 0)),
                    "llm_model": raw.get("llm_model", ""),
                }
                for entry_hash, raw in entries.items()
            ),
            key=lambda item: item["use_count"],
            reverse=True,
        )
        return {
            "total_requests": total,
            "cache_hits": hits,
            "hit_rate": round(hits / total, 3) if total else 0.0,
            "saved_api_calls": hits,
            "entry_count": len(entries),
            "top_cached_prompts": top[:10],
        }

    def delete(self, key_hash: str) -> None:
        """Physically remove one entry by its storage hash (CA-004)."""
        with self._lock:
            data = self._load_cache()
            if data["entries"].pop(key_hash, None) is not None:
                self._save_cache(data)

    def delete_by_key(self, key: CacheKey, llm_provider: str, llm_model: str) -> None:
        """Physically remove one entry addressed by its logical cache key."""
        self.delete(self._entry_hash(key, llm_provider, llm_model))

    def clear_all(self) -> None:
        with self._lock:
            self._save_cache({"version": _CACHE_VERSION, "entries": {}})
            self._save_stats({"cache_hits": 0, "cache_misses": 0})

    # ------------------------------------------------------------------
    # Internal persistence helpers (caller must hold self._lock)
    # ------------------------------------------------------------------

    def _load_cache(self) -> dict:
        data = self._load_json(self._cache_path)
        if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
            return {"version": _CACHE_VERSION, "entries": {}}
        return data

    def _load_stats(self) -> dict:
        data = self._load_json(self._stats_path)
        if not isinstance(data, dict):
            return {"cache_hits": 0, "cache_misses": 0}
        return data

    def _load_json(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning(
                "Cache file %s is corrupted or unreadable (%s) — "
                "reinitialising as empty.",
                path, exc,
            )
            return None

    def _save_cache(self, data: dict) -> None:
        self._cache_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _save_stats(self, stats: dict) -> None:
        self._stats_path.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _bump_stat(self, field: str) -> None:
        stats = self._load_stats()
        stats[field] = int(stats.get(field, 0)) + 1
        self._save_stats(stats)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    @staticmethod
    def _entry_to_dict(entry: CacheEntry) -> dict:
        raw = asdict(entry)
        raw["created_at"] = entry.created_at.isoformat()
        raw["last_used_at"] = entry.last_used_at.isoformat()
        return raw

    @staticmethod
    def _entry_from_dict(raw: dict) -> CacheEntry:
        return CacheEntry(
            cache_key=CacheKey(**raw["cache_key"]),
            original_prompts=list(raw.get("original_prompts", [])),
            intent_object=dict(raw.get("intent_object", {})),
            confidence_score=float(raw.get("confidence_score", 0.0)),
            created_at=datetime.fromisoformat(raw["created_at"]),
            last_used_at=datetime.fromisoformat(raw["last_used_at"]),
            use_count=int(raw.get("use_count", 0)),
            llm_provider=raw.get("llm_provider", ""),
            llm_model=raw.get("llm_model", ""),
        )
