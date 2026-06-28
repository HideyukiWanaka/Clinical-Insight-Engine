"""Unit tests for knowledge_review UI components.

streamlit is mocked at the sys.modules level so no Streamlit runtime is needed.
All tests verify *what* is rendered (which st.* calls are made) rather than
the visual output, which cannot be asserted without a browser.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import ModuleType
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# streamlit stub — must be installed before importing the component
# ---------------------------------------------------------------------------

def _make_st_mock() -> MagicMock:
    """Return a MagicMock that behaves like the streamlit module."""
    mock = MagicMock(name="streamlit")
    # columns() must return a list of context-manager-compatible mocks
    col = MagicMock()
    col.__enter__ = MagicMock(return_value=col)
    col.__exit__ = MagicMock(return_value=False)
    mock.columns.return_value = [col, col]
    # button() returns False by default (not clicked)
    mock.button.return_value = False
    return mock


# Inject the stub before importing the module under test
_st_stub = _make_st_mock()
sys.modules.setdefault("streamlit", _st_stub)

# Now safe to import the component
from cie.knowledge.ingestion_agent import KnowledgeEntryDraft  # noqa: E402
from cie.knowledge.loader import ExpiryWarning  # noqa: E402
from cie.knowledge.models import (  # noqa: E402
    KnowledgeDomain,
    KnowledgeEntry,
    KnowledgeEntryItem,
    KnowledgeStatus,
    RelatedEntry,
    SourceInfo,
    TrustLevel,
)

import cie.ui.components.knowledge_review as kr  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_st() -> MagicMock:
    """Return a fresh st mock and patch it into the component module."""
    mock = _make_st_mock()
    kr.st = mock
    return mock


def _make_draft(**overrides) -> KnowledgeEntryDraft:
    defaults = dict(
        draft_id="draft-001",
        source_hash="abc123",
        source_filename="study.pdf",
        parsed_text="Some content.",
        extracted_metadata={"title": "Test Study", "year": 2024, "doi": "10.1000/xyz"},
        extracted_knowledge_items=[
            {"id": "i-001", "statement": "A statement.", "direct_quote": "A quote.", "confidence": 0.9},
        ],
        extracted_trust_level="peer_reviewed",
        extracted_domain="statistics",
        extraction_limitations=["AI extraction only — review required."],
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return KnowledgeEntryDraft(**defaults)


def _make_entry(
    entry_id: str = "KE-0001",
    created_by: str = "researcher@example.com",
    related: list[RelatedEntry] | None = None,
) -> KnowledgeEntry:
    return KnowledgeEntry(
        entry_id=entry_id,
        domain=KnowledgeDomain.STATISTICS,
        version="1.0.0",
        status=KnowledgeStatus.ACTIVE,
        trust_level=TrustLevel.PEER_REVIEWED,
        source_info=SourceInfo(title="Test Study", year=2024, doi="10.1000/test"),
        knowledge_entries=[
            KnowledgeEntryItem(
                id="item-001",
                statement="Randomisation is essential.",
                direct_quote="RCT is the gold standard.",
            )
        ],
        approved_by_human=True,
        created_by=created_by,
        approved_by="admin@example.com",
        approved_at=datetime.now(timezone.utc),
        related_entries=related or [],
    )


# ---------------------------------------------------------------------------
# render_expiry_warnings tests
# ---------------------------------------------------------------------------

def test_render_expiry_warnings_expired():
    st = _fresh_st()
    warnings = [ExpiryWarning(entry_id="KE-0001", level="expired", message="Expired message")]
    kr.render_expiry_warnings(warnings)
    st.error.assert_called_once()
    assert "Expired message" in st.error.call_args[0][0]
    st.warning.assert_not_called()


def test_render_expiry_warnings_expiring_soon():
    st = _fresh_st()
    warnings = [ExpiryWarning(entry_id="KE-0001", level="expiring_soon", message="Expiring soon msg")]
    kr.render_expiry_warnings(warnings)
    st.warning.assert_called_once()
    assert "Expiring soon msg" in st.warning.call_args[0][0]
    st.error.assert_not_called()


def test_render_expiry_warnings_no_warnings():
    st = _fresh_st()
    kr.render_expiry_warnings([])
    st.error.assert_not_called()
    st.warning.assert_not_called()


# ---------------------------------------------------------------------------
# render_knowledge_registry_panel tests
# ---------------------------------------------------------------------------

def test_archive_button_hidden_for_unauthorized():
    st = _fresh_st()
    entry = _make_entry(created_by="owner@example.com")
    on_archive = MagicMock()
    kr.render_knowledge_registry_panel(
        entries=[entry],
        current_user_id="intruder@example.com",
        current_user_role="researcher",
        on_archive=on_archive,
    )
    # st.button must not have been called with the archive label
    archive_calls = [
        c for c in st.button.call_args_list
        if "アーカイブ" in str(c)
    ]
    assert archive_calls == [], f"Archive button should not render for unauthorized user, got: {archive_calls}"
    on_archive.assert_not_called()


def test_superseded_warning_shown():
    st = _fresh_st()
    related = [RelatedEntry(entry_id="KE-0002", relationship="superseded_by")]
    entry = _make_entry(related=related)
    kr.render_knowledge_registry_panel(
        entries=[entry],
        current_user_id="researcher@example.com",
        current_user_role="researcher",
        on_archive=MagicMock(),
    )
    # st.warning should be called with the "新しいバージョン" message
    warning_texts = [str(c) for c in st.warning.call_args_list]
    assert any("新しいバージョン" in t for t in warning_texts), (
        f"Expected superseded warning; got warning calls: {warning_texts}"
    )


# ---------------------------------------------------------------------------
# render_knowledge_draft_review tests
# ---------------------------------------------------------------------------

def test_low_confidence_items_highlighted():
    st = _fresh_st()
    draft = _make_draft(
        extracted_knowledge_items=[
            {"id": "i-low", "statement": "Low confidence stmt.", "direct_quote": "Quote.", "confidence": 0.5},
            {"id": "i-high", "statement": "High confidence stmt.", "direct_quote": "Quote.", "confidence": 0.9},
        ]
    )
    kr.render_knowledge_draft_review(draft)

    # Collect all markdown/write calls to find the 🟡 prefix
    all_text_calls = (
        [str(c) for c in st.markdown.call_args_list]
        + [str(c) for c in st.write.call_args_list]
    )
    highlighted = [t for t in all_text_calls if "🟡" in t]
    assert len(highlighted) >= 1, f"Expected at least one 🟡 highlight; got: {highlighted}"

    not_highlighted = [t for t in all_text_calls if "High confidence" in t and "🟡" in t]
    assert not_highlighted == [], "High confidence items should NOT be highlighted"
