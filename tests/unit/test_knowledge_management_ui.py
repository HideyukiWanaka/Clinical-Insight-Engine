"""Unit tests for the Knowledge Management screen.

streamlit is mocked at sys.modules level so no Streamlit runtime is needed.
Tests verify which event dict render_knowledge_management() returns in each
interaction scenario.

Convention follows test_knowledge_review_ui.py in this directory.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# streamlit stub — must be installed before any component import
# ---------------------------------------------------------------------------

def _make_st_mock() -> MagicMock:
    mock = MagicMock(name="streamlit")

    col = MagicMock()
    col.__enter__ = MagicMock(return_value=col)
    col.__exit__ = MagicMock(return_value=False)
    mock.columns.return_value = [col, col]
    mock.button.return_value = False
    mock.checkbox.return_value = False

    # tabs() returns context-manager-compatible mocks
    tab = MagicMock()
    tab.__enter__ = MagicMock(return_value=tab)
    tab.__exit__ = MagicMock(return_value=False)
    mock.tabs.return_value = [tab, tab]

    mock.session_state = {}
    return mock


_st_stub = _make_st_mock()
sys.modules.setdefault("streamlit", _st_stub)

# Now safe to import domain models and the screen under test
from cie.knowledge.ingestion_agent import KnowledgeEntryDraft  # noqa: E402
from cie.knowledge.loader import ExpiryWarning  # noqa: E402
from cie.knowledge.models import (  # noqa: E402
    KnowledgeDomain,
    KnowledgeEntry,
    KnowledgeEntryItem,
    KnowledgeStatus,
    SourceInfo,
    TrustLevel,
)

import cie.ui.screens.knowledge_management as km  # noqa: E402
import cie.ui.components.knowledge_review as kr   # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _fresh_st() -> MagicMock:
    """Return a fresh st mock and patch it into both modules under test."""
    mock = _make_st_mock()
    km.st = mock
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
            {
                "id": "i-001",
                "statement": "A statement.",
                "direct_quote": "A quote.",
                "confidence": 0.9,
            }
        ],
        extracted_trust_level="peer_reviewed",
        extracted_domain="statistics",
        extraction_limitations=["AI extraction only — review required."],
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return KnowledgeEntryDraft(**defaults)


def _make_entry(entry_id: str = "KE-0001") -> KnowledgeEntry:
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
        created_by="researcher@example.com",
        approved_by="admin@example.com",
        approved_at=datetime.now(timezone.utc),
    )


def _make_expiry_warning(level: str = "expiring_soon") -> ExpiryWarning:
    return ExpiryWarning(
        entry_id="KE-0001",
        level=level,  # type: ignore[arg-type]
        message="Expiring soon message",
    )


# ---------------------------------------------------------------------------
# Tests: screen returns None when nothing is clicked
# ---------------------------------------------------------------------------

class TestNoEvent:
    def test_returns_none_when_nothing_clicked(self):
        """No button clicks → render_knowledge_management returns None."""
        _fresh_st()
        # render_knowledge_upload_panel is called when draft is None; mock it to do nothing
        with patch.object(km, "render_knowledge_upload_panel"):
            with patch.object(km, "render_knowledge_registry_panel"):
                result = km.render_knowledge_management(
                    entries=[],
                    draft=None,
                    expiry_warnings=[],
                    current_user_id="user@example.com",
                    current_user_role="researcher",
                )
        assert result is None

    def test_returns_none_with_entries_and_no_interaction(self):
        _fresh_st()
        with patch.object(km, "render_knowledge_upload_panel"):
            with patch.object(km, "render_knowledge_registry_panel"):
                result = km.render_knowledge_management(
                    entries=[_make_entry()],
                    draft=None,
                    expiry_warnings=[],
                    current_user_id="user@example.com",
                    current_user_role="researcher",
                )
        assert result is None


# ---------------------------------------------------------------------------
# Tests: draft present → draft review UI
# ---------------------------------------------------------------------------

class TestDraftReview:
    def test_draft_approved_returns_event(self):
        """When render_knowledge_draft_review returns 'approve', action=draft_approved."""
        st = _fresh_st()
        st.session_state = {
            "trust_draft-001": "peer_reviewed",
            "domain_draft-001": "statistics",
        }
        draft = _make_draft()

        with patch.object(km, "render_knowledge_draft_review", return_value="approve"):
            with patch.object(km, "render_knowledge_registry_panel"):
                result = km.render_knowledge_management(
                    entries=[],
                    draft=draft,
                    expiry_warnings=[],
                    current_user_id="user@example.com",
                    current_user_role="researcher",
                )

        assert result is not None
        assert result["action"] == "draft_approved"
        assert result["draft_id"] == "draft-001"
        assert result["trust_level"] == "peer_reviewed"
        assert result["domain"] == "statistics"

    def test_draft_rejected_returns_event(self):
        """When render_knowledge_draft_review returns 'reject', action=draft_rejected."""
        st = _fresh_st()
        st.session_state = {}
        draft = _make_draft()

        with patch.object(km, "render_knowledge_draft_review", return_value="reject"):
            with patch.object(km, "render_knowledge_registry_panel"):
                result = km.render_knowledge_management(
                    entries=[],
                    draft=draft,
                    expiry_warnings=[],
                    current_user_id="user@example.com",
                    current_user_role="researcher",
                )

        assert result is not None
        assert result["action"] == "draft_rejected"
        assert result["draft_id"] == "draft-001"

    def test_draft_present_shows_info_banner(self):
        """When a draft exists, st.info() is called with the draft_id."""
        st = _fresh_st()
        st.session_state = {}
        draft = _make_draft()

        with patch.object(km, "render_knowledge_draft_review", return_value=None):
            with patch.object(km, "render_knowledge_registry_panel"):
                km.render_knowledge_management(
                    entries=[],
                    draft=draft,
                    expiry_warnings=[],
                    current_user_id="user@example.com",
                    current_user_role="researcher",
                )

        info_calls = [str(c) for c in st.info.call_args_list]
        assert any("draft-001" in t for t in info_calls), (
            f"Expected draft_id in st.info(); got: {info_calls}"
        )

    def test_draft_approved_falls_back_to_extracted_values(self):
        """When session_state has no trust/domain keys, extracted values are used."""
        st = _fresh_st()
        st.session_state = {}  # no widget state
        draft = _make_draft(
            extracted_trust_level="regulatory",
            extracted_domain="clinical",
        )

        with patch.object(km, "render_knowledge_draft_review", return_value="approve"):
            with patch.object(km, "render_knowledge_registry_panel"):
                result = km.render_knowledge_management(
                    entries=[],
                    draft=draft,
                    expiry_warnings=[],
                    current_user_id="user@example.com",
                    current_user_role="researcher",
                )

        assert result["trust_level"] == "regulatory"
        assert result["domain"] == "clinical"


# ---------------------------------------------------------------------------
# Tests: upload event
# ---------------------------------------------------------------------------

class TestUploadEvent:
    def test_upload_callback_produces_event(self):
        """When on_upload is called by render_knowledge_upload_panel, action=upload."""
        _fresh_st()

        def fake_upload_panel(on_upload):
            on_upload(b"file content", "study.pdf")

        with patch.object(km, "render_knowledge_upload_panel", side_effect=fake_upload_panel):
            with patch.object(km, "render_knowledge_registry_panel"):
                result = km.render_knowledge_management(
                    entries=[],
                    draft=None,
                    expiry_warnings=[],
                    current_user_id="user@example.com",
                    current_user_role="researcher",
                )

        assert result is not None
        assert result["action"] == "upload"
        assert result["filename"] == "study.pdf"
        assert result["file_bytes"] == b"file content"

    def test_no_draft_shows_upload_panel(self):
        """When draft is None, render_knowledge_upload_panel is called."""
        _fresh_st()

        with patch.object(km, "render_knowledge_upload_panel") as mock_panel:
            with patch.object(km, "render_knowledge_registry_panel"):
                km.render_knowledge_management(
                    entries=[],
                    draft=None,
                    expiry_warnings=[],
                    current_user_id="user@example.com",
                    current_user_role="researcher",
                )

        mock_panel.assert_called_once()

    def test_draft_present_hides_upload_panel(self):
        """When a draft is pending, render_knowledge_upload_panel is NOT called."""
        st = _fresh_st()
        st.session_state = {}
        draft = _make_draft()

        with patch.object(km, "render_knowledge_upload_panel") as mock_panel, \
             patch.object(km, "render_knowledge_draft_review", return_value=None), \
             patch.object(km, "render_knowledge_registry_panel"):
            km.render_knowledge_management(
                entries=[],
                draft=draft,
                expiry_warnings=[],
                current_user_id="user@example.com",
                current_user_role="researcher",
            )

        mock_panel.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: archive event
# ---------------------------------------------------------------------------

class TestArchiveEvent:
    def test_archive_callback_produces_event(self):
        """When on_archive is called, action=archive with correct entry_id."""
        _fresh_st()

        def fake_registry(entries, current_user_id, current_user_role, on_archive):
            on_archive("KE-0001")

        with patch.object(km, "render_knowledge_registry_panel", side_effect=fake_registry):
            with patch.object(km, "render_knowledge_upload_panel"):
                result = km.render_knowledge_management(
                    entries=[_make_entry()],
                    draft=None,
                    expiry_warnings=[],
                    current_user_id="user@example.com",
                    current_user_role="researcher",
                )

        assert result is not None
        assert result["action"] == "archive"
        assert result["entry_id"] == "KE-0001"


# ---------------------------------------------------------------------------
# Tests: expiry warnings
# ---------------------------------------------------------------------------

class TestExpiryWarnings:
    def test_expiry_warnings_rendered_at_top(self):
        """Expiry warnings are passed to render_expiry_warnings."""
        _fresh_st()
        warnings = [_make_expiry_warning("expiring_soon"), _make_expiry_warning("expired")]

        with patch.object(km, "render_expiry_warnings") as mock_warn, \
             patch.object(km, "render_knowledge_upload_panel"), \
             patch.object(km, "render_knowledge_registry_panel"):
            km.render_knowledge_management(
                entries=[],
                draft=None,
                expiry_warnings=warnings,
                current_user_id="user@example.com",
                current_user_role="researcher",
            )

        mock_warn.assert_called_once_with(warnings)

    def test_no_expiry_warnings_skips_render(self):
        """When warnings list is empty, render_expiry_warnings is NOT called."""
        _fresh_st()

        with patch.object(km, "render_expiry_warnings") as mock_warn, \
             patch.object(km, "render_knowledge_upload_panel"), \
             patch.object(km, "render_knowledge_registry_panel"):
            km.render_knowledge_management(
                entries=[],
                draft=None,
                expiry_warnings=[],
                current_user_id="user@example.com",
                current_user_role="researcher",
            )

        mock_warn.assert_not_called()

    def test_expired_warning_shows_st_error(self):
        """An 'expired' ExpiryWarning results in st.error() being called."""
        st = _fresh_st()
        warnings = [_make_expiry_warning("expired")]

        with patch.object(km, "render_knowledge_upload_panel"), \
             patch.object(km, "render_knowledge_registry_panel"):
            km.render_knowledge_management(
                entries=[],
                draft=None,
                expiry_warnings=warnings,
                current_user_id="user@example.com",
                current_user_role="researcher",
            )

        st.error.assert_called()
