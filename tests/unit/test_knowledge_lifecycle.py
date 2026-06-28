from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from cie.core.exceptions import PermissionDeniedError
from cie.knowledge.ingestion_agent import KnowledgeEntryDraft
from cie.knowledge.lifecycle import KnowledgeLifecycleService
from cie.knowledge.models import KnowledgeEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(tmp_path: Path) -> KnowledgeLifecycleService:
    institutional = tmp_path / "institutional"
    institutional.mkdir()
    (institutional / "REGISTRY.yaml").write_text(
        "schema_version: '1.0'\nentries: []\n", encoding="utf-8"
    )
    pending = tmp_path / "pending"
    pending.mkdir()
    mock_audit = MagicMock()
    mock_audit.write = AsyncMock()
    return KnowledgeLifecycleService(
        institutional_dir=institutional,
        pending_dir=pending,
        audit_service=mock_audit,
    )


def _make_draft(tmp_path: Path) -> KnowledgeEntryDraft:
    draft_id = "test-draft-001"
    draft_dir = tmp_path / "pending" / draft_id
    draft_dir.mkdir(parents=True, exist_ok=True)
    (draft_dir / "REVIEW_REQUEST.yaml").write_text("draft_id: test-draft-001\n", encoding="utf-8")
    return KnowledgeEntryDraft(
        draft_id=draft_id,
        source_hash="abc123",
        source_filename="study.pdf",
        parsed_text="Study content.",
        extracted_metadata={"title": "Test Study", "year": 2024, "doi": "10.1000/test"},
        extracted_knowledge_items=[],
        extracted_trust_level="peer_reviewed",
        extracted_domain="statistics",
        extraction_limitations=[],
        created_at=datetime.now(timezone.utc),
    )


def _default_register_kwargs() -> dict:
    return dict(
        approved_by="admin@example.com",
        created_by="researcher@example.com",
        domain="statistics",
        trust_level="peer_reviewed",
        source_info={"title": "Test Study", "year": 2024, "doi": "10.1000/test"},
        knowledge_items=[
            {
                "id": "item-001",
                "statement": "Randomisation is essential.",
                "direct_quote": "Randomisation is the gold standard.",
                "confidence": 0.9,
            }
        ],
    )


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_creates_entry_directory(tmp_path):
    svc = _make_service(tmp_path)
    draft = _make_draft(tmp_path)
    entry = await svc.register_knowledge(draft, **_default_register_kwargs())
    assert (tmp_path / "institutional" / entry.entry_id).is_dir()


@pytest.mark.asyncio
async def test_register_writes_metadata_yaml(tmp_path):
    svc = _make_service(tmp_path)
    draft = _make_draft(tmp_path)
    entry = await svc.register_knowledge(draft, **_default_register_kwargs())
    meta_path = tmp_path / "institutional" / entry.entry_id / "METADATA.yaml"
    assert meta_path.exists()
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    assert meta["entry_id"] == entry.entry_id
    assert meta["approved_by_human"] is True
    assert meta["status"] == "active"
    assert meta["domain"] == "statistics"


@pytest.mark.asyncio
async def test_register_updates_registry(tmp_path):
    svc = _make_service(tmp_path)
    draft = _make_draft(tmp_path)
    entry = await svc.register_knowledge(draft, **_default_register_kwargs())
    registry = yaml.safe_load(
        (tmp_path / "institutional" / "REGISTRY.yaml").read_text(encoding="utf-8")
    )
    ids = [e["entry_id"] for e in registry["entries"]]
    assert entry.entry_id in ids


@pytest.mark.asyncio
async def test_register_entry_id_increments(tmp_path):
    svc = _make_service(tmp_path)

    draft1 = _make_draft(tmp_path)
    entry1 = await svc.register_knowledge(draft1, **_default_register_kwargs())

    # Second draft needs its own pending dir
    draft2_id = "test-draft-002"
    draft2_dir = tmp_path / "pending" / draft2_id
    draft2_dir.mkdir(parents=True, exist_ok=True)
    draft2 = KnowledgeEntryDraft(
        draft_id=draft2_id,
        source_hash="def456",
        source_filename="study2.pdf",
        parsed_text="More content.",
        extracted_metadata={"title": "Study 2", "year": 2024, "doi": "10.1000/test2"},
        extracted_knowledge_items=[],
        extracted_trust_level="peer_reviewed",
        extracted_domain="clinical",
        extraction_limitations=[],
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    entry2 = await svc.register_knowledge(
        draft2,
        **{**_default_register_kwargs(), "domain": "clinical"},
    )

    assert entry1.entry_id == "KE-0001"
    assert entry2.entry_id == "KE-0002"


# ---------------------------------------------------------------------------
# Archive (Soft Delete) tests
# ---------------------------------------------------------------------------

async def _register_and_get_entry(tmp_path: Path) -> tuple[KnowledgeLifecycleService, KnowledgeEntry]:
    svc = _make_service(tmp_path)
    draft = _make_draft(tmp_path)
    entry = await svc.register_knowledge(draft, **_default_register_kwargs())
    return svc, entry


@pytest.mark.asyncio
async def test_archive_changes_status(tmp_path):
    svc, entry = await _register_and_get_entry(tmp_path)
    await svc.archive_entry(
        entry_id=entry.entry_id,
        archived_by="admin@example.com",
        current_user_id="researcher@example.com",
        current_user_role="researcher",
        reason="Superseded by newer guideline.",
    )
    meta = yaml.safe_load(
        (tmp_path / "institutional" / entry.entry_id / "METADATA.yaml").read_text(encoding="utf-8")
    )
    assert meta["status"] == "archived"
    assert meta["archived_by"] == "admin@example.com"
    assert meta["archived_at"] is not None


@pytest.mark.asyncio
async def test_archive_unauthorized_user_raises(tmp_path):
    svc, entry = await _register_and_get_entry(tmp_path)
    with pytest.raises(PermissionDeniedError):
        await svc.archive_entry(
            entry_id=entry.entry_id,
            archived_by="intruder@example.com",
            current_user_id="intruder@example.com",
            current_user_role="researcher",
        )


@pytest.mark.asyncio
async def test_archive_admin_can_archive_others(tmp_path):
    svc, entry = await _register_and_get_entry(tmp_path)
    # admin is not the creator but can still archive
    await svc.archive_entry(
        entry_id=entry.entry_id,
        archived_by="admin@example.com",
        current_user_id="admin@example.com",
        current_user_role="admin",
    )
    meta = yaml.safe_load(
        (tmp_path / "institutional" / entry.entry_id / "METADATA.yaml").read_text(encoding="utf-8")
    )
    assert meta["status"] == "archived"


@pytest.mark.asyncio
async def test_archive_does_not_physically_delete(tmp_path):
    svc, entry = await _register_and_get_entry(tmp_path)
    entry_dir = tmp_path / "institutional" / entry.entry_id
    await svc.archive_entry(
        entry_id=entry.entry_id,
        archived_by="admin@example.com",
        current_user_id="researcher@example.com",
        current_user_role="researcher",
    )
    # Directory and files must still exist after soft delete
    assert entry_dir.exists()
    assert (entry_dir / "METADATA.yaml").exists()
    assert (entry_dir / "KNOWLEDGE.md").exists()


def test_no_physical_delete_method_exists():
    members = inspect.getmembers(KnowledgeLifecycleService, predicate=inspect.isfunction)
    delete_methods = [name for name, _ in members if "delete" in name.lower()]
    assert delete_methods == [], (
        f"KnowledgeLifecycleService must not define any 'delete' method; found: {delete_methods}"
    )
