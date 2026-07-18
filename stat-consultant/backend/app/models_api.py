"""REST /api/models — the model picker's data source.

Returns the curated model list with an ``available`` flag per model (true when
that provider's API key is configured on the server) and the default id. The
frontend renders the dropdown from this and disables unavailable models.
"""

from __future__ import annotations

from fastapi import APIRouter

from .models_registry import MODELS, configured_providers, default_model_id

router = APIRouter(tags=["models"])


@router.get("/api/models")
def list_models() -> dict[str, object]:
    configured = configured_providers()
    return {
        "default": default_model_id(),
        "models": [
            {
                "id": m.id,
                "label": m.label,
                "provider": m.provider,
                "available": m.provider in configured,
            }
            for m in MODELS
        ],
    }
