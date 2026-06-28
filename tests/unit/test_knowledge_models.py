from __future__ import annotations

import pytest
from datetime import datetime, date

from cie.knowledge.models import (
    KnowledgeDomain,
    KnowledgeEntry,
    KnowledgeEntryItem,
    KnowledgeStatus,
    RelatedEntry,
    SourceInfo,
    TrustLevel,
)


def _make_source_info(**kwargs) -> SourceInfo:
    defaults = dict(title="ICH E9 Guideline", year=2019, doi="10.1000/xyz123")
    defaults.update(kwargs)
    return SourceInfo(**defaults)


def _make_entry(**kwargs) -> KnowledgeEntry:
    defaults = dict(
        entry_id="KE-0001",
        domain=KnowledgeDomain.STATISTICS,
        version="1.0.0",
        status=KnowledgeStatus.ACTIVE,
        trust_level=TrustLevel.REGULATORY,
        source_info=_make_source_info(),
        knowledge_entries=[
            KnowledgeEntryItem(
                id="ke-0001-001",
                statement="Estimands must be defined prior to analysis.",
                direct_quote="The estimand should be defined before the statistical analysis.",
            )
        ],
        approved_by_human=True,
        created_by="researcher@example.com",
        approved_by="admin@example.com",
        approved_at=datetime(2026, 6, 28, 12, 0, 0),
    )
    defaults.update(kwargs)
    return KnowledgeEntry(**defaults)


def test_valid_knowledge_entry_creates():
    entry = _make_entry()
    assert entry.entry_id == "KE-0001"
    assert entry.domain == KnowledgeDomain.STATISTICS
    assert entry.approved_by_human is True


def test_approved_by_human_false_raises():
    with pytest.raises(ValueError, match="approved_by_human must be True"):
        _make_entry(approved_by_human=False)


def test_source_info_requires_doi_or_url():
    with pytest.raises(ValueError, match="doi or url"):
        SourceInfo(title="Test", year=2020, doi=None, url=None)


def test_entry_id_pattern_validated():
    with pytest.raises(ValueError, match="KE-XXXX"):
        _make_entry(entry_id="KE-ABCD")


def test_expires_at_none_allowed():
    entry = _make_entry(expires_at=None)
    assert entry.expires_at is None


def test_related_entries_default_empty():
    entry = _make_entry()
    assert entry.related_entries == []
