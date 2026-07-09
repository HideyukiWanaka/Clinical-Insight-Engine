"""/api/settings/llm — AI provider selection + API key management.

Distinct from the ``X-CIE-Token`` session auth (main.py): this is the
end-user-facing screen for "which LLM provider, and what's its API key" —
the thing people instinctively look for under something called "settings".
Keys are written to the OS keyring only (``cie.core.secrets_store``), never
returned or logged; only a per-provider ``has_key`` boolean is exposed.

Both the provider switch and the key save mutate the single shared
``LLMClient`` instance in place (``services["llm_client"].set_credentials``),
so changes take effect on the very next LLM call — no API restart needed.
The active provider is additionally persisted to ``.env`` so it survives one.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from cie.api.deps import get_services
from cie.api.models import (
    LlmApiKeyClearRequest,
    LlmApiKeyRequest,
    LlmProviderRequest,
    LlmProviderStatus,
    LlmSettingsResponse,
)
from cie.core.env_file import set_env_var
from cie.core.secrets_store import delete_api_key, has_api_key, load_api_key, save_api_key

router = APIRouter(prefix="/api/settings", tags=["settings"])

_PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI (GPT)",
    "google_gemini": "Google Gemini",
}


def _status(active_provider: str) -> LlmSettingsResponse:
    return LlmSettingsResponse(
        active_provider=active_provider,
        providers=[
            LlmProviderStatus(provider=p, label=label, has_key=has_api_key(p))
            for p, label in _PROVIDER_LABELS.items()
        ],
    )


# Invisible characters copy/paste sometimes carries along silently (zero-width
# space/joiners, BOM). None of these are ever legitimately part of an API key,
# so they're stripped outright rather than causing a cryptic ASCII-codec
# UnicodeEncodeError deep inside httpx's header encoding the next time the
# key is used in an Authorization header (httpx headers must be ASCII/latin-1).
_INVISIBLE_CHARS = "​‌‍﻿"


def _clean_api_key(raw: str) -> str:
    """Strip whitespace and invisible characters; reject remaining non-ASCII.

    Raises:
        ValueError: If non-ASCII characters remain after cleaning — almost
            always a sign of a full-width character or stray symbol picked up
            during copy/paste, which the user should re-check.
    """
    cleaned = raw.strip()
    for ch in _INVISIBLE_CHARS:
        cleaned = cleaned.replace(ch, "")
    cleaned = cleaned.strip()
    if not cleaned.isascii():
        raise ValueError(
            "APIキーに全角文字や特殊な記号が含まれているようです。"
            "コピー元を確認し、キーだけを貼り付け直してください。"
        )
    return cleaned


def _require_known_provider(provider: str) -> None:
    if provider not in _PROVIDER_LABELS:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "UNKNOWN_PROVIDER",
                "message": f"未知のプロバイダーです: {provider}",
                "detail": f"対応プロバイダー: {sorted(_PROVIDER_LABELS)}",
            },
        )


@router.get("/llm", response_model=LlmSettingsResponse)
async def get_llm_settings(request: Request) -> LlmSettingsResponse:
    """Current active provider + which providers already have a stored key."""
    llm_client = get_services(request)["llm_client"]
    return _status(llm_client.provider)


@router.post("/llm/provider", response_model=LlmSettingsResponse)
async def set_llm_provider(
    request: Request, body: LlmProviderRequest
) -> LlmSettingsResponse:
    """Switch the active provider. Persists to .env; takes effect immediately."""
    _require_known_provider(body.provider)
    llm_client = get_services(request)["llm_client"]
    llm_client.set_credentials(body.provider, load_api_key(body.provider) or "")
    set_env_var("CIE_ACTIVE_AI_PROVIDER", body.provider)
    return _status(body.provider)


@router.post("/llm/key", response_model=LlmSettingsResponse)
async def save_llm_key(request: Request, body: LlmApiKeyRequest) -> LlmSettingsResponse:
    """Save a provider's API key to the OS keyring.

    If this is the active provider, the running client picks up the new key
    immediately; otherwise it's just stored for a future provider switch.
    """
    _require_known_provider(body.provider)
    if not body.api_key.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "EMPTY_API_KEY",
                "message": "APIキーが空です。",
                "detail": None,
            },
        )
    try:
        clean_key = _clean_api_key(body.api_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_API_KEY_CHARACTERS",
                "message": str(exc),
                "detail": None,
            },
        ) from exc
    save_api_key(body.provider, clean_key)

    llm_client = get_services(request)["llm_client"]
    if llm_client.provider == body.provider:
        llm_client.set_credentials(body.provider, clean_key)
    return _status(llm_client.provider)


@router.post("/llm/key/clear", response_model=LlmSettingsResponse)
async def clear_llm_key(
    request: Request, body: LlmApiKeyClearRequest
) -> LlmSettingsResponse:
    """Remove a provider's stored API key."""
    _require_known_provider(body.provider)
    delete_api_key(body.provider)

    llm_client = get_services(request)["llm_client"]
    if llm_client.provider == body.provider:
        llm_client.set_credentials(body.provider, "")
    return _status(llm_client.provider)
