"""REST /api/settings/keys — BYOK API key management.

The end-user-facing "settings" screen: which provider, and what's its key.
Translated from the LLM-key parts of ``cie/api/routes/settings.py`` (the
provider-switch and storage parts are dropped — the provider is implied by the
model chosen in the header).

Keys are written to the OS keyring only (``app.secrets_store``), never returned
or logged; only a per-provider ``has_key`` boolean is exposed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import secrets_store
from .models_registry import PROVIDER_LABELS
from .origins import require_local_origin

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Zero-width space / joiners / BOM that copy-paste silently carries along. None
# are ever part of an API key, and left in they'd blow up later as a non-ASCII
# Authorization header. Strip outright.
_INVISIBLE_CHARS = "​‌‍﻿"


class ApiKeyBody(BaseModel):
    provider: str
    api_key: str


def _clean_api_key(raw: str) -> str:
    """Strip whitespace + invisible chars; reject remaining non-ASCII."""
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
    if provider not in PROVIDER_LABELS:
        raise HTTPException(status_code=400, detail=f"未知のプロバイダーです: {provider}")


def _status() -> dict[str, object]:
    return {
        "providers": [
            {"provider": p, "label": label, "has_key": secrets_store.has_api_key(p)}
            for p, label in PROVIDER_LABELS.items()
        ]
    }


@router.get("/keys")
def get_keys() -> dict[str, object]:
    """Which providers already have a stored key (never the key itself)."""
    return _status()


@router.post("/keys", dependencies=[Depends(require_local_origin)])
def save_key(body: ApiKeyBody) -> dict[str, object]:
    """Save a provider's API key to the OS keyring. Returns has_key-only status."""
    _require_known_provider(body.provider)
    if not body.api_key.strip():
        raise HTTPException(status_code=400, detail="APIキーが空です。")
    try:
        clean_key = _clean_api_key(body.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        secrets_store.save_api_key(body.provider, clean_key)
    except secrets_store.KeyringUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _status()


@router.delete("/keys/{provider}", dependencies=[Depends(require_local_origin)])
def clear_key(provider: str) -> dict[str, object]:
    """Remove a provider's stored key."""
    _require_known_provider(provider)
    secrets_store.delete_api_key(provider)
    return _status()
