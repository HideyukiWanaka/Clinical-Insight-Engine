"""Unit tests for CIE UI components: StatusBar and RightPane.

Streamlit is mocked at the sys.modules level so no Streamlit runtime is needed.
Tests verify which st.* calls are made (what is rendered) rather than visual output.

The prompt specification asks for streamlit.testing.v1.AppTest; however, since
Streamlit is not installed in the test environment, we follow the established
project convention of module-level mocking (see test_knowledge_review_ui.py).
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# streamlit stub — must be installed before importing the components
# ---------------------------------------------------------------------------

def _make_st_mock() -> MagicMock:
    mock = MagicMock(name="streamlit")

    col = MagicMock()
    col.__enter__ = MagicMock(return_value=col)
    col.__exit__ = MagicMock(return_value=False)
    mock.columns.return_value = [col, col, col, col]

    mock.button.return_value = False
    mock.checkbox.return_value = False
    return mock


_st_stub = _make_st_mock()
sys.modules.setdefault("streamlit", _st_stub)

import cie.ui.components.status_bar as sb  # noqa: E402
import cie.ui.components.right_pane as rp  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_st_for(module) -> MagicMock:
    mock = _make_st_mock()
    module.st = mock
    return mock


def _make_event(severity: str = "INFO", code: str = "EVT-001") -> dict:
    return {
        "severity": severity,
        "code": code,
        "timestamp": "2026-06-28T12:00:00Z",
    }


def _make_log_entry(
    agent_id: str = "planner",
    action: str = "intent_extracted",
    summary: str = "confidence=0.91",
    severity: str = "INFO",
    timestamp: str = "2026-06-28T14:32:07+00:00",
) -> dict:
    return {
        "agent_id": agent_id,
        "action": action,
        "summary": summary,
        "severity": severity,
        "timestamp": timestamp,
    }


# ---------------------------------------------------------------------------
# StatusBar tests
# ---------------------------------------------------------------------------

class TestStatusBar:
    def test_online_indicator(self):
        """connection_status='online' のとき 🟢 オンライン を含む markdown を呼ぶ。"""
        st = _fresh_st_for(sb)
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        st.columns.return_value = [col, col, col, col]

        sb.render_status_bar(
            project_name="TestProject",
            execution_id=None,
            connection_status="online",
            security_events=[],
            workflow_state=None,
        )

        # In the mock env, st.markdown() is called (not col.markdown), because
        # Streamlit's column context re-routing is not replicated by the mock.
        all_markdown = [str(c) for c in st.markdown.call_args_list]
        assert any("🟢" in t for t in all_markdown), (
            f"Expected 🟢 in markdown calls; got: {all_markdown}"
        )

    def test_offline_indicator(self):
        """connection_status='offline' のとき ⚫ を含む markdown を呼ぶ。"""
        st = _fresh_st_for(sb)
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        st.columns.return_value = [col, col, col, col]

        sb.render_status_bar(
            project_name=None,
            execution_id=None,
            connection_status="offline",
            security_events=[],
            workflow_state=None,
        )

        all_markdown = [str(c) for c in st.markdown.call_args_list]
        assert any("⚫" in t for t in all_markdown), (
            f"Expected ⚫ in markdown calls; got: {all_markdown}"
        )

    def test_breach_overlay_shown(self):
        """BREACH イベントがある場合、st.error() を呼んでオーバーレイを表示する。"""
        st = _fresh_st_for(sb)
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        st.columns.return_value = [col, col, col, col]

        breach_event = _make_event(severity="BREACH", code="SEC-BREACH-001")
        sb.render_status_bar(
            project_name="SecureProject",
            execution_id="ex-abc123",
            connection_status="online",
            security_events=[breach_event],
            workflow_state=None,
        )

        st.error.assert_called_once()
        error_text = str(st.error.call_args)
        assert "🚨" in error_text, f"Expected 🚨 in error overlay; got: {error_text}"
        assert "SEC-BREACH-001" in error_text, f"Expected error code; got: {error_text}"

    def test_no_breach_overlay_without_breach_event(self):
        """BREACH イベントがない場合、st.error() は呼ばれない。"""
        st = _fresh_st_for(sb)
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        st.columns.return_value = [col, col, col, col]

        sb.render_status_bar(
            project_name=None,
            execution_id=None,
            connection_status="online",
            security_events=[_make_event(severity="WARNING")],
            workflow_state=None,
        )

        st.error.assert_not_called()

    def test_execution_id_truncated(self):
        """execution_id がある場合、最初の8文字 + '...' でマークダウン表示される。"""
        st = _fresh_st_for(sb)
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        st.columns.return_value = [col, col, col, col]

        sb.render_status_bar(
            project_name=None,
            execution_id="abcdef1234567890",
            connection_status="online",
            security_events=[],
            workflow_state=None,
        )

        all_markdown = [str(c) for c in st.markdown.call_args_list]
        assert any("abcdef12" in t for t in all_markdown), (
            f"Expected truncated execution_id; got: {all_markdown}"
        )


# ---------------------------------------------------------------------------
# ApprovalPanel tests
# ---------------------------------------------------------------------------

class TestApprovalPanel:
    def test_approval_button_disabled_when_unchecked(self):
        """checkbox 未チェック時、承認ボタンは disabled=True で描画される。"""
        st = _fresh_st_for(rp)
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        st.columns.return_value = [col, col]
        st.checkbox.return_value = False  # unchecked

        context = {"title": "Rスクリプトの実行を承認します。", "is_irreversible": True}
        rp.render_right_pane(
            workflow_state=None,
            agent_activity_log=[],
            approval_pending=True,
            approval_context=context,
        )

        # Find the "承認して実行" button call and verify disabled=True
        button_calls = col.button.call_args_list
        approve_calls = [c for c in button_calls if "承認して実行" in str(c)]
        assert len(approve_calls) >= 1, f"Expected approve button; got: {button_calls}"
        _, kwargs = approve_calls[0]
        assert kwargs.get("disabled") is True, (
            f"Approve button should be disabled when unchecked; kwargs: {kwargs}"
        )

    def test_approval_button_enabled_when_checked(self):
        """checkbox チェック済みのとき、承認ボタンは disabled=False で描画される。"""
        st = _fresh_st_for(rp)
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        st.columns.return_value = [col, col]
        st.checkbox.return_value = True  # checked

        context = {"title": "承認テスト", "is_irreversible": False}
        rp.render_right_pane(
            workflow_state=None,
            agent_activity_log=[],
            approval_pending=True,
            approval_context=context,
        )

        button_calls = col.button.call_args_list
        approve_calls = [c for c in button_calls if "承認して実行" in str(c)]
        assert len(approve_calls) >= 1, f"Expected approve button; got: {button_calls}"
        _, kwargs = approve_calls[0]
        assert kwargs.get("disabled") is False, (
            f"Approve button should be enabled when checked; kwargs: {kwargs}"
        )

    def test_irreversible_shows_error(self):
        """is_irreversible=True のとき、st.error() で警告が表示される。"""
        st = _fresh_st_for(rp)
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        st.columns.return_value = [col, col]
        st.checkbox.return_value = False

        context = {"title": "不可逆操作テスト", "is_irreversible": True}
        rp.render_right_pane(
            workflow_state=None,
            agent_activity_log=[],
            approval_pending=True,
            approval_context=context,
        )

        st.error.assert_called_once()
        assert "取り消せません" in str(st.error.call_args)

    def test_approval_panel_hidden_when_not_pending(self):
        """approval_pending=False のとき、承認パネルの要素を描画しない。"""
        st = _fresh_st_for(rp)
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        st.columns.return_value = [col, col]

        rp.render_right_pane(
            workflow_state=None,
            agent_activity_log=[],
            approval_pending=False,
            approval_context=None,
        )

        st.checkbox.assert_not_called()


# ---------------------------------------------------------------------------
# AgentActivityFeed tests
# ---------------------------------------------------------------------------

class TestActivityFeed:
    def test_activity_feed_max_50(self):
        """51件のログを渡すと最新50件のみ表示される。"""
        st = _fresh_st_for(rp)
        st.columns.return_value = []

        logs = [
            _make_log_entry(summary=f"entry-{i}") for i in range(51)
        ]
        rp.render_right_pane(
            workflow_state=None,
            agent_activity_log=logs,
            approval_pending=False,
            approval_context=None,
        )

        # st.code is used for normal INFO entries
        code_calls = st.code.call_args_list
        # Each visible entry renders exactly once via st.code / st.warning / st.error
        total_render_calls = (
            len(st.code.call_args_list)
            + len(st.warning.call_args_list)
            + len(st.error.call_args_list)
        )
        assert total_render_calls == 50, (
            f"Expected exactly 50 rendered entries; got {total_render_calls}"
        )

        # "entry-0" (oldest) should NOT appear; "entry-50" (newest) should appear
        all_rendered = (
            [str(c) for c in st.code.call_args_list]
            + [str(c) for c in st.warning.call_args_list]
            + [str(c) for c in st.error.call_args_list]
        )
        assert not any("entry-0" in t for t in all_rendered), (
            "Oldest entry (entry-0) should have been dropped"
        )
        assert any("entry-50" in t for t in all_rendered), (
            "Newest entry (entry-50) should be visible"
        )

    def test_warning_entries_use_st_warning(self):
        """severity=WARNING のエントリは st.warning() で描画される。"""
        st = _fresh_st_for(rp)
        st.columns.return_value = []

        logs = [_make_log_entry(severity="WARNING", summary="warn-entry")]
        rp.render_right_pane(
            workflow_state=None,
            agent_activity_log=logs,
            approval_pending=False,
            approval_context=None,
        )

        assert st.warning.call_count >= 1
        assert any("warn-entry" in str(c) for c in st.warning.call_args_list)

    def test_critical_entries_use_st_error(self):
        """severity=CRITICAL のエントリは st.error() で描画される。"""
        st = _fresh_st_for(rp)
        st.columns.return_value = []

        logs = [_make_log_entry(severity="CRITICAL", summary="crit-entry")]
        rp.render_right_pane(
            workflow_state=None,
            agent_activity_log=logs,
            approval_pending=False,
            approval_context=None,
        )

        assert st.error.call_count >= 1
        assert any("crit-entry" in str(c) for c in st.error.call_args_list)

    def test_empty_feed_shows_caption(self):
        """ログが空のとき、st.caption() でメッセージを表示する。"""
        st = _fresh_st_for(rp)
        st.columns.return_value = []

        rp.render_right_pane(
            workflow_state=None,
            agent_activity_log=[],
            approval_pending=False,
            approval_context=None,
        )

        st.caption.assert_called_once()
