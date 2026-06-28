from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from cie.core.exceptions import KnowledgeError
from cie.knowledge.loader import FrozenKnowledgeSet, KnowledgeLoader
from cie.knowledge.models import KnowledgeDomain


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _base_metadata(entry_id: str = "KE-0001", **overrides) -> dict:
    meta = {
        "entry_id": entry_id,
        "domain": "statistics",
        "version": "1.0.0",
        "status": "active",
        "trust_level": "peer_reviewed",
        "source_info": {
            "title": "Test Study",
            "year": 2024,
            "doi": "10.1000/test",
        },
        "knowledge_entries": [
            {
                "id": "item-001",
                "statement": "Randomisation is essential.",
                "direct_quote": "RCT is the gold standard.",
                "confidence": 0.9,
            }
        ],
        "approved_by_human": True,
        "created_by": "researcher@example.com",
        "approved_by": "admin@example.com",
        "approved_at": "2024-01-01T00:00:00+00:00",
        "expires_at": None,
        "related_entries": [],
    }
    meta.update(overrides)
    return meta


def _write_entry(institutional_dir: Path, metadata: dict) -> None:
    entry_dir = institutional_dir / metadata["entry_id"]
    entry_dir.mkdir(parents=True, exist_ok=True)
    (entry_dir / "METADATA.yaml").write_text(
        yaml.dump(metadata, allow_unicode=True), encoding="utf-8"
    )


def _write_registry(institutional_dir: Path, entries: list[dict]) -> None:
    registry = {
        "schema_version": "1.0",
        "entries": [
            {
                "entry_id": e["entry_id"],
                "status": e.get("status", "active"),
            }
            for e in entries
        ],
    }
    (institutional_dir / "REGISTRY.yaml").write_text(
        yaml.dump(registry, allow_unicode=True), encoding="utf-8"
    )


def _make_loader(tmp_path: Path) -> KnowledgeLoader:
    official = tmp_path / "official"
    official.mkdir()
    institutional = tmp_path / "institutional"
    institutional.mkdir()
    return KnowledgeLoader(official_dir=official, institutional_dir=institutional)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_load_returns_frozen_set(tmp_path):
    loader = _make_loader(tmp_path)
    meta = _base_metadata()
    _write_entry(tmp_path / "institutional", meta)
    _write_registry(tmp_path / "institutional", [meta])
    result = loader.load_for_execution("exec-001")
    assert isinstance(result, FrozenKnowledgeSet)
    assert result.execution_id == "exec-001"
    assert len(result.entries) == 1


def test_frozen_set_is_immutable(tmp_path):
    loader = _make_loader(tmp_path)
    _write_registry(tmp_path / "institutional", [])
    frozen = loader.load_for_execution("exec-002")
    with pytest.raises((TypeError, AttributeError)):
        frozen.entries = ()  # type: ignore[misc]


def test_reload_raises_error(tmp_path):
    loader = _make_loader(tmp_path)
    _write_registry(tmp_path / "institutional", [])
    frozen = loader.load_for_execution("exec-003")
    with pytest.raises(KnowledgeError) as exc_info:
        frozen.reload()
    assert "FORBIDDEN" in exc_info.value.error_code


def test_archived_entries_excluded(tmp_path):
    loader = _make_loader(tmp_path)
    active_meta = _base_metadata("KE-0001", status="active")
    archived_meta = _base_metadata("KE-0002", status="archived")
    _write_entry(tmp_path / "institutional", active_meta)
    _write_entry(tmp_path / "institutional", archived_meta)
    _write_registry(tmp_path / "institutional", [active_meta, archived_meta])
    frozen = loader.load_for_execution("exec-004")
    ids = {e.entry_id for e in frozen.entries}
    assert "KE-0001" in ids
    assert "KE-0002" not in ids


def test_superseded_entry_warning(tmp_path):
    loader = _make_loader(tmp_path)
    meta = _base_metadata(
        "KE-0001",
        related_entries=[{"entry_id": "KE-0002", "relationship": "superseded_by"}],
    )
    _write_entry(tmp_path / "institutional", meta)
    _write_registry(tmp_path / "institutional", [meta])
    frozen = loader.load_for_execution("exec-005")
    superseded = [w for w in frozen.expiry_warnings if w.level == "superseded"]
    assert len(superseded) == 1
    assert superseded[0].entry_id == "KE-0001"


def test_expired_entry_generates_warning(tmp_path):
    loader = _make_loader(tmp_path)
    past_date = (date.today() - timedelta(days=10)).isoformat()
    meta = _base_metadata("KE-0001", expires_at=past_date)
    _write_entry(tmp_path / "institutional", meta)
    _write_registry(tmp_path / "institutional", [meta])
    frozen = loader.load_for_execution("exec-006")
    expired = [w for w in frozen.expiry_warnings if w.level == "expired"]
    assert len(expired) == 1
    assert expired[0].entry_id == "KE-0001"


def test_expiring_soon_entry_warning(tmp_path):
    loader = _make_loader(tmp_path)
    soon_date = (date.today() + timedelta(days=30)).isoformat()
    meta = _base_metadata("KE-0001", expires_at=soon_date)
    _write_entry(tmp_path / "institutional", meta)
    _write_registry(tmp_path / "institutional", [meta])
    frozen = loader.load_for_execution("exec-007")
    soon = [w for w in frozen.expiry_warnings if w.level == "expiring_soon"]
    assert len(soon) == 1
    assert soon[0].entry_id == "KE-0001"


def test_no_expiry_no_warning(tmp_path):
    loader = _make_loader(tmp_path)
    meta = _base_metadata("KE-0001", expires_at=None)
    _write_entry(tmp_path / "institutional", meta)
    _write_registry(tmp_path / "institutional", [meta])
    frozen = loader.load_for_execution("exec-008")
    expiry_warnings = [
        w for w in frozen.expiry_warnings if w.level in ("expired", "expiring_soon")
    ]
    assert expiry_warnings == []


def test_get_by_domain_filters_correctly(tmp_path):
    loader = _make_loader(tmp_path)
    stats_meta = _base_metadata("KE-0001", domain="statistics")
    clinical_meta = _base_metadata("KE-0002", domain="clinical")
    _write_entry(tmp_path / "institutional", stats_meta)
    _write_entry(tmp_path / "institutional", clinical_meta)
    _write_registry(tmp_path / "institutional", [stats_meta, clinical_meta])
    frozen = loader.load_for_execution("exec-009")
    stats_entries = frozen.get_by_domain(KnowledgeDomain.STATISTICS)
    clinical_entries = frozen.get_by_domain(KnowledgeDomain.CLINICAL)
    assert len(stats_entries) == 1
    assert stats_entries[0].entry_id == "KE-0001"
    assert len(clinical_entries) == 1
    assert clinical_entries[0].entry_id == "KE-0002"
