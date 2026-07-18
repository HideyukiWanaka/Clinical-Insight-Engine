"""REST /api/models — the model picker's data source.

Returns the curated model list with an ``available`` flag per model — true
when that provider's API key is configured on the server *and* (best-effort)
the model id still exists in that provider's own catalog — plus the default
id. The frontend renders the dropdown from this and disables unavailable
models, so a curated entry the provider has since renamed or retired (e.g. a
model id that was never actually shipped) stops appearing as selectable
instead of requiring a manual edit to models_registry.py.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from .models_registry import MODELS, default_model_id, verified_available

router = APIRouter(tags=["models"])


@router.get("/api/models")
async def list_models() -> dict[str, object]:
    availability = await asyncio.gather(*(verified_available(m) for m in MODELS))
    available_ids = {m.id for m, ok in zip(MODELS, availability) if ok}
    default = next(
        (m.id for m in MODELS if m.id in available_ids), default_model_id()
    )
    return {
        "default": default,
        "models": [
            {
                "id": m.id,
                "label": m.label,
                "provider": m.provider,
                "available": m.id in available_ids,
            }
            for m in MODELS
        ],
    }
