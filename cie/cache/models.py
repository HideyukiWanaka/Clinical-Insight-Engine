"""CIE Platform — Semantic cache data models (ADR-0004 Phase 1).

CacheKey pairs the normalized user prompt with a fingerprint of the
dataset's column structure: the same sentence over a different dataset
must never hit the cache (CA-006).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CacheKey:
    """Composite lookup key for a cached IntentObject.

    Attributes:
        normalized_prompt: User prompt after normalization
            (see :func:`cie.cache.normalization.normalize_prompt`).
        dataset_fingerprint: SHA-256 (truncated) of sorted var_N:type pairs.
    """

    normalized_prompt: str
    dataset_fingerprint: str


@dataclass
class CacheEntry:
    """A single cached Planner result.

    Attributes:
        cache_key: The composite key this entry is stored under.
        original_prompts: Raw user inputs that mapped to this key —
            accumulated for later SYNONYM_MAP curation (ADR-0004 Phase 2).
        intent_object: The cached IntentObject dict.
        confidence_score: LLM confidence at cache time (always >= 0.7, CA-002).
        created_at: First insertion time (UTC).
        last_used_at: Most recent hit time (UTC).
        use_count: Number of cache hits served by this entry.
        llm_provider: Provider that produced the entry.
        llm_model: Model that produced the entry — entries are never shared
            across models (CA-005).
    """

    cache_key: CacheKey
    original_prompts: list[str]
    intent_object: dict
    confidence_score: float
    created_at: datetime
    last_used_at: datetime
    use_count: int
    llm_provider: str
    llm_model: str
