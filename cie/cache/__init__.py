"""CIE Platform — PlannerAgent semantic cache (ADR-0004).

Public surface:
    CacheKey / CacheEntry   — cie.cache.models
    CacheStore              — cie.cache.store
    normalize_prompt / make_dataset_fingerprint — cie.cache.normalization
"""

from cie.cache.models import CacheEntry, CacheKey
from cie.cache.normalization import make_dataset_fingerprint, normalize_prompt
from cie.cache.store import CacheStore

__all__ = [
    "CacheEntry",
    "CacheKey",
    "CacheStore",
    "make_dataset_fingerprint",
    "normalize_prompt",
]
