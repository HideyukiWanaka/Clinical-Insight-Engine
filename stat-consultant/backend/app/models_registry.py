"""Model registry across providers (Anthropic / OpenAI / Gemini).

The user picks a model in the UI; the WS turn carries its ``id``. A model is
marked available when its provider API key is configured on the server *and*
(best-effort, via ``verified_available``) the provider's own catalog still
lists that model id — see the "live catalog check" section below. Keys come
from the environment — never the UI (no secrets screen).

NOTE: the model IDs below are still a curated starting set (display label,
ordering, and which ids are worth offering at all are a human call) — edit
this one list to match each provider's current lineup. The live catalog check
only *hides* entries the provider has dropped; it never adds new ones.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from . import secrets_store

Provider = str  # "anthropic" | "openai" | "gemini"

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


@dataclass(frozen=True)
class ModelSpec:
    id: str  # stable id used by the frontend + WS frame
    label: str  # display name in the dropdown
    provider: Provider
    model: str  # the provider's actual model id


# --- curated model list (edit here to match current provider lineups) ---
MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("claude-opus-4-8", "Claude Opus 4.8", "anthropic", "claude-opus-4-8"),
    ModelSpec("claude-sonnet-5", "Claude Sonnet 5", "anthropic", "claude-sonnet-5"),
    ModelSpec("claude-haiku-4-5", "Claude Haiku 4.5", "anthropic", "claude-haiku-4-5"),
    ModelSpec("gpt-5.1", "GPT-5.1", "openai", "gpt-5.1"),
    ModelSpec("gpt-5-mini", "GPT-5 mini", "openai", "gpt-5-mini"),
    ModelSpec("gemini-3-pro", "Gemini 3 Pro", "gemini", "gemini-3-pro"),
    ModelSpec("gemini-2.5-flash", "Gemini 2.5 Flash", "gemini", "gemini-2.5-flash"),
)

_BY_ID: dict[str, ModelSpec] = {m.id: m for m in MODELS}

# Distinct providers appearing in MODELS (order-stable).
_PROVIDERS: tuple[Provider, ...] = tuple(dict.fromkeys(m.provider for m in MODELS))

# Human labels for the settings screen.
PROVIDER_LABELS: dict[Provider, str] = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI (GPT)",
    "gemini": "Google (Gemini)",
}


def configured_providers() -> set[Provider]:
    """Providers with a configured API key (OS keyring or environment)."""
    return {p for p in _PROVIDERS if secrets_store.has_api_key(p)}


def is_available(spec: ModelSpec) -> bool:
    return spec.provider in configured_providers()


# --- live catalog check (SPEC: hide curated entries the provider dropped) ---
# The curated list above can drift from a provider's actual lineup (renamed or
# retired model ids). Rather than requiring a code edit every time that
# happens, cross-check each provider's own /models endpoint and hide entries
# that no longer exist there. Cached per provider so the settings screen
# doesn't hit the network on every render; a fetch failure (offline, key just
# rotated, provider outage) fails open — i.e. trusts the curated list — so a
# transient lookup error never blanks out every model.
_LIVE_CACHE_TTL_SECONDS = 300
_live_cache: dict[Provider, tuple[float, set[str]]] = {}


async def _fetch_live_ids(provider: Provider) -> set[str] | None:
    key = secrets_store.load_api_key(provider)
    if not key:
        return None
    try:
        if provider == "anthropic":
            async with AsyncAnthropic(api_key=key) as client:
                page = await client.models.list()
        else:
            base_url = GEMINI_BASE_URL if provider == "gemini" else None
            async with AsyncOpenAI(api_key=key, base_url=base_url) as client:
                page = await client.models.list()
        return {m.id for m in page.data}
    except Exception:  # noqa: BLE001 — any SDK/network failure just fails open
        return None


async def _live_ids(provider: Provider) -> set[str] | None:
    """Cached live catalog for ``provider``, or None if never fetched."""
    now = time.monotonic()
    cached = _live_cache.get(provider)
    if cached and now - cached[0] < _LIVE_CACHE_TTL_SECONDS:
        return cached[1]
    fetched = await _fetch_live_ids(provider)
    if fetched is not None:
        _live_cache[provider] = (now, fetched)
        return fetched
    return cached[1] if cached else None  # stale cache beats no cache


async def verified_available(spec: ModelSpec) -> bool:
    """``is_available`` plus a best-effort check that the model id still
    exists in the provider's own catalog, so a renamed/retired curated entry
    (e.g. a model id that never shipped) stops showing up as selectable."""
    if not is_available(spec):
        return False
    live_ids = await _live_ids(spec.provider)
    if live_ids is None:  # couldn't verify — trust the curated list
        return True
    return spec.model in live_ids


def default_model_id() -> str:
    """First available model, else the first listed (so the UI is never empty)."""
    configured = configured_providers()
    for m in MODELS:
        if m.provider in configured:
            return m.id
    return MODELS[0].id


def resolve_model(model_id: str | None) -> ModelSpec:
    """Return the spec for ``model_id``, falling back to the default."""
    if model_id and model_id in _BY_ID:
        return _BY_ID[model_id]
    return _BY_ID[default_model_id()]
