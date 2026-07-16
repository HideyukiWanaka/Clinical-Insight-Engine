"""Model registry across providers (Anthropic / OpenAI / Gemini).

The user picks a model in the UI; the WS turn carries its ``id``. Only models
whose provider API key is configured on the server are marked available. Keys
come from the environment — never the UI (no secrets screen).

NOTE: the model IDs below are a curated starting set. They change often — edit
this one list to match each provider's current lineup; nothing else depends on
the exact strings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

Provider = str  # "anthropic" | "openai" | "gemini"


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

# Env var(s) that supply each provider's key.
_KEY_ENV: dict[Provider, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


def configured_providers() -> set[Provider]:
    """Providers whose API key is present in the environment."""
    return {
        prov
        for prov, names in _KEY_ENV.items()
        if any(os.environ.get(n) for n in names)
    }


def is_available(spec: ModelSpec) -> bool:
    return spec.provider in configured_providers()


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
