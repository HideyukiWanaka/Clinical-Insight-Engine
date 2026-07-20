"""Model registry across providers (Anthropic / OpenAI / Gemini).

No hardcoded model-id list: each configured provider's own ``/models``
catalog is queried directly and filtered down to ordinary text-chat models.
A distributed app can't ship a source patch every time a provider renames a
model or tacks on a date/preview suffix (observed live: Gemini's real id is
``gemini-3-pro-preview``, not a curated ``gemini-3-pro``) — so nothing here
pins an exact model id. Only the *provider* set (Anthropic/OpenAI/Gemini) and
the coarse per-provider "which family names are chat models" heuristics
below are hardcoded; those change far less often than individual model ids.

Keys come from the OS keychain or environment (``secrets_store``) — never
hardcoded, never echoed to the UI beyond ``has_key``.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from . import secrets_store

Provider = str  # "anthropic" | "openai" | "gemini"

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

PROVIDERS: tuple[Provider, ...] = ("anthropic", "openai", "gemini")

# Human labels for the settings screen.
PROVIDER_LABELS: dict[Provider, str] = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI (GPT)",
    "gemini": "Google (Gemini)",
}


@dataclass(frozen=True)
class ModelSpec:
    id: str  # the provider's real model id — used as-is for the API call
    label: str  # display name in the dropdown
    provider: Provider


def configured_providers() -> set[Provider]:
    """Providers with a configured API key (OS keyring or environment)."""
    return {p for p in PROVIDERS if secrets_store.has_api_key(p)}


def is_available(spec: ModelSpec) -> bool:
    return spec.provider in configured_providers()


# --- text-chat filtering ---------------------------------------------------
# Each provider's /models mixes in embeddings/TTS/image/video/etc. A model
# must match one of its provider's family prefixes and none of the shared
# deny substrings to be offered in the chat picker.
_CHAT_ALLOW_PREFIX: dict[Provider, tuple[str, ...]] = {
    "anthropic": ("claude-",),
    "openai": ("gpt-", "chatgpt-", "o1", "o3", "o4", "o5"),
    "gemini": ("gemini-",),
}
_CHAT_DENY_SUBSTRING: tuple[str, ...] = (
    "embed", "whisper", "tts", "dall-e", "audio", "video", "image",
    "moderation", "davinci", "babbage", "instruct", "realtime",
    "transcribe", "search", "computer-use", "codex", "live", "veo",
    "imagen", "aqa",
    # Special-purpose families that share a chat prefix but aren't general
    # chat models. "robotics" (Gemini Robotics-ER, embodied reasoning) used to
    # slip through and become the default for a statistics tool.
    "robotics", "learnlm", "guard",
)


def _is_chat_model(provider: Provider, model_id: str) -> bool:
    allow = _CHAT_ALLOW_PREFIX.get(provider, ())
    if not any(model_id.startswith(p) for p in allow):
        return False
    low = model_id.lower()
    return not any(bad in low for bad in _CHAT_DENY_SUBSTRING)


def _strip_models_prefix(raw_id: str) -> str:
    # Gemini's OpenAI-compat catalog returns ids like "models/gemini-3-pro-preview".
    return raw_id.removeprefix("models/")


def _humanize_id(model_id: str) -> str:
    """Fallback label when the provider doesn't supply a display name (OpenAI)."""
    words = []
    for part in model_id.split("-"):
        if part.lower() == "gpt":
            words.append("GPT")
        elif re.fullmatch(r"o\d+", part.lower()):
            words.append(part.lower())
        else:
            words.append(part.capitalize())
    return " ".join(words)


def _created_sort_key(created: object) -> tuple[int, object]:
    """Normalize Anthropic's ISO ``created_at`` str, OpenAI's unix ``created``
    int, and Gemini's (observed) absent value into one comparable, descending
    sort key. Gemini supplies nothing here, so this alone cannot order its
    catalog — see _tier_score for what actually decides the default."""
    if isinstance(created, (int, float)) or (isinstance(created, str) and created):
        return (1, created)
    return (0, "")


# --- default-selection ranking ---------------------------------------------
# The dropdown still lists whatever the provider's catalog returns — nothing is
# hardcoded — but the *default* must not be whichever id happens to sort first.
# Gemini's catalog carries no `created`, so ordering by it alone degenerates to
# reverse-alphabetical, which is how a robotics model became the default.
#
# Score capability *tier* words rather than version numbers, so a future
# claude-opus-5 or gemini-4-pro ranks correctly with no edit here — that's the
# property the live-catalog design exists to preserve.
_TIER_BONUS: tuple[tuple[str, int], ...] = (
    ("opus", 3),
    ("pro", 3),
    ("sonnet", 2),
)
_TIER_PENALTY: tuple[tuple[str, int], ...] = (
    # Cheaper/faster tiers: fine to offer, wrong to auto-pick for statistical
    # reasoning where answer quality matters more than latency.
    ("mini", 2), ("nano", 2), ("lite", 2), ("flash", 2), ("haiku", 2),
    # Unstable channels shouldn't be the default a clinician silently gets.
    ("preview", 3), ("experimental", 3), ("-exp", 3), ("alpha", 3), ("beta", 3),
)


def _tier_score(model_id: str) -> int:
    """Rough capability ranking used to order the picker and pick the default."""
    low = model_id.lower()
    score = 0
    for token, bonus in _TIER_BONUS:
        if token in low:
            score += bonus
    for token, penalty in _TIER_PENALTY:
        if token in low:
            score -= penalty
    return score


async def _fetch_provider_models(provider: Provider) -> list[ModelSpec] | None:
    key = secrets_store.load_api_key(provider)
    if not key:
        return None
    try:
        if provider == "anthropic":
            async with AsyncAnthropic(api_key=key) as client:
                page = await client.models.list()
            raw = [(m.id, getattr(m, "display_name", None), getattr(m, "created_at", None))
                   for m in page.data]
        else:
            base_url = GEMINI_BASE_URL if provider == "gemini" else None
            async with AsyncOpenAI(api_key=key, base_url=base_url) as client:
                page = await client.models.list()
            raw = [(_strip_models_prefix(m.id), getattr(m, "display_name", None),
                    getattr(m, "created", None)) for m in page.data]
    except Exception:  # noqa: BLE001 — any SDK/network failure just fails open to the cache
        return None

    chat_only = [(mid, label, created) for mid, label, created in raw
                 if _is_chat_model(provider, mid)]
    # Tier first (capability), then recency where the provider reports it, then
    # id for a stable tiebreak. Without the tier term this is alphabetical noise
    # for any provider that omits `created`.
    chat_only.sort(
        key=lambda t: (_tier_score(t[0]), _created_sort_key(t[2]), t[0]),
        reverse=True,
    )
    return [ModelSpec(id=mid, label=label or _humanize_id(mid), provider=provider)
            for mid, label, _created in chat_only]


_LIVE_CACHE_TTL_SECONDS = 300
_live_cache: dict[Provider, tuple[float, list[ModelSpec]]] = {}


async def list_models(provider: Provider) -> list[ModelSpec]:
    """This provider's currently available chat models, newest-first.

    Cached per provider (network calls are relatively slow); a fetch failure
    (offline, key just rotated, provider outage) reuses the last-known-good
    cache instead of blanking the dropdown, but there's no static fallback
    list any more — if this provider has never been fetched successfully, it
    contributes nothing until connectivity is restored.
    """
    now = time.monotonic()
    cached = _live_cache.get(provider)
    if cached and now - cached[0] < _LIVE_CACHE_TTL_SECONDS:
        return cached[1]
    fetched = await _fetch_provider_models(provider)
    if fetched is not None:
        _live_cache[provider] = (now, fetched)
        return fetched
    return cached[1] if cached else []


async def _first_live_model() -> ModelSpec | None:
    for provider in PROVIDERS:
        models = await list_models(provider)
        if models:
            return models[0]
    return None


def _infer_provider(model_id: str) -> Provider | None:
    for provider, prefixes in _CHAT_ALLOW_PREFIX.items():
        if any(model_id.startswith(p) for p in prefixes):
            return provider
    return None


async def resolve_model(model_id: str | None) -> ModelSpec:
    """Return the spec for ``model_id``, falling back to the first available
    live model when omitted (bare-text WS turns, per the README)."""
    if model_id:
        provider = _infer_provider(model_id)
        # Unrecognized prefix: provider="" makes is_available() False below,
        # so the caller's existing "not configured" error path handles it.
        return ModelSpec(id=model_id, label=model_id, provider=provider or "")
    return await _first_live_model() or ModelSpec(id="", label="(no model)", provider="")
