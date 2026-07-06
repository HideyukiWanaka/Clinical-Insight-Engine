"""/api/knowledge/* — Knowledge Ingestion Pipeline endpoints (§3.8, ADR-0003).

Thin wrappers over ``KnowledgeIngestionAgent`` (ingest → pending/) and
``KnowledgeLifecycleService`` (human-approved register → institutional/).
The approve endpoint IS the human-in-the-loop surface (ADR-0003:
``approved_by_human`` is always True on register).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile

from cie.api.deps import get_services
from cie.api.models import (
    KnowledgeApproveRequest,
    KnowledgeApproveResponse,
    KnowledgeIngestResponse,
    KnowledgeListResponse,
    KnowledgeRejectRequest,
    KnowledgeRejectResponse,
)
from cie.knowledge.ingestion_guard import IngestionError

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _draft_store(request: Request) -> dict:
    store = getattr(request.app.state, "knowledge_drafts", None)
    if store is None:
        store = {}
        request.app.state.knowledge_drafts = store
    return store


@router.post("/ingest", response_model=KnowledgeIngestResponse)
async def ingest(request: Request, file: UploadFile) -> KnowledgeIngestResponse:
    """Run the KIP ingestion pipeline; PII-rejected documents return 422."""
    services = get_services(request)
    file_bytes = await file.read()
    try:
        draft = await services["knowledge_ingestion"].ingest(
            Path(file.filename or "upload.txt"),
            file_bytes,
            uploaded_by="api",
        )
    except IngestionError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": exc.error_code,
                "message": str(exc),
                "failed_checks": [
                    getattr(c, "check_name", str(c)) for c in exc.failed_checks
                ],
            },
        ) from exc

    _draft_store(request)[draft.draft_id] = draft
    return KnowledgeIngestResponse(
        draft_id=draft.draft_id,
        extracted={
            "source_info": draft.extracted_metadata,
            "domain": draft.extracted_domain,
            "trust_level": draft.extracted_trust_level,
            "knowledge_items": draft.extracted_knowledge_items,
        },
        extraction_limitations=draft.extraction_limitations,
    )


@router.post("/approve", response_model=KnowledgeApproveResponse)
async def approve(
    request: Request, body: KnowledgeApproveRequest
) -> KnowledgeApproveResponse:
    """Register a human-approved draft into institutional/ (ADR-0003)."""
    services = get_services(request)
    draft = _draft_store(request).get(body.draft_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "DRAFT_NOT_FOUND",
                "message": f"No pending draft {body.draft_id}",
                "detail": None,
            },
        )

    corrections = body.corrections or {}
    source_info = {**draft.extracted_metadata, **corrections.get("source_info", {})}
    knowledge_items = corrections.get("knowledge_items") or draft.extracted_knowledge_items

    entry = await services["knowledge_lifecycle"].register_knowledge(
        draft=draft,
        approved_by="api",
        created_by="api",
        domain=body.domain,
        trust_level=body.trust_level,
        source_info=source_info,
        knowledge_items=knowledge_items,
    )
    _draft_store(request).pop(body.draft_id, None)
    # Embedding reindex is Phase 5 (ADR-0005) — not performed here.
    return KnowledgeApproveResponse(entry_id=entry.entry_id)


@router.post("/reject", response_model=KnowledgeRejectResponse)
async def reject(
    request: Request, body: KnowledgeRejectRequest
) -> KnowledgeRejectResponse:
    """Reject a pending draft (transient — drop from the pending store)."""
    removed = _draft_store(request).pop(body.draft_id, None)
    if removed is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "DRAFT_NOT_FOUND",
                "message": f"No pending draft {body.draft_id}",
                "detail": None,
            },
        )
    return KnowledgeRejectResponse(draft_id=body.draft_id, status="rejected")


@router.get("", response_model=KnowledgeListResponse)
async def list_entries(request: Request) -> KnowledgeListResponse:
    """List registered institutional/ knowledge entries (REGISTRY.yaml)."""
    services = get_services(request)
    frozen = services["knowledge_loader"].load_for_execution("api-list")
    entries = [
        {
            "entry_id": getattr(e, "entry_id", None),
            "domain": getattr(getattr(e, "domain", None), "value", None),
            "status": getattr(getattr(e, "status", None), "value", None),
            "trust_level": getattr(getattr(e, "trust_level", None), "value", None),
            "title": getattr(getattr(e, "source_info", None), "title", None),
        }
        for e in frozen.entries
    ]
    return KnowledgeListResponse(entries=entries)


@router.post("/reindex")
async def reindex(request: Request) -> dict:
    """Rebuild the local embedding index (§3.9).

    Deferred to Phase 5 (ADR-0005 local embedding RAG). Returns 501 so callers
    get an explicit, non-silent signal rather than a fabricated count.
    """
    raise HTTPException(
        status_code=501,
        detail={
            "error_code": "NOT_IMPLEMENTED",
            "message": "Embedding reindex arrives in Phase 5 (ADR-0005).",
            "detail": "The Phase 1 API keeps the existing MarkdownReferenceLibrary.",
        },
    )
