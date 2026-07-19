"""REST /api/models — the model picker's data source.

Returns each configured provider's live chat-model catalog (no curated
id list — see models_registry.py). Every entry returned here is, by
construction, currently invocable, so there's no ``available`` flag to
carry any more; a provider with no key (or no reachable catalog yet)
simply contributes no entries.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from .models_registry import PROVIDERS, list_models

router = APIRouter(tags=["models"])


@router.get("/api/models")
async def list_models_endpoint() -> dict[str, object]:
    per_provider = await asyncio.gather(*(list_models(p) for p in PROVIDERS))
    models = [m for group in per_provider for m in group]
    return {
        "default": models[0].id if models else "",
        "models": [
            {"id": m.id, "label": m.label, "provider": m.provider} for m in models
        ],
    }
