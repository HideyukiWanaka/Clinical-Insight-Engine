"""Unit tests for the Settings screen.

streamlit is mocked at sys.modules level so no Streamlit runtime is needed.
Tests verify which event dict render_settings() returns in each scenario,
and that no API key values leak into session_state.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# streamlit stub — must be installed before any screen import
# ---------------------------------------------------------------------------

def _make_st_mock() -> MagicMock:
    mock = MagicMock(name="streamlit")
    mock.session_state = {}
    mock.button.return_value = False
    mock.radio.return_value = "Anthropic (Claude)"
    mock.text_input.return_value = ""
    mock.columns.return_value = _make_cols(3)
    return mock


def _make_cols(n: int) -> list[MagicMock]:
    cols = []
    for _ in range(n):
        col = MagicMock()
        col.__enter__ = MagicMock(return_value=col)
        col.__exit__ = MagicMock(return_value=False)
        cols.append(col)
    return cols


_st_stub = _make_st_mock()
sys.modules.setdefault("streamlit", _st_stub)

import cie.ui.screens.settings as settings_mod  # noqa: E402
from cie.ui.screens.settings import render_settings  # noqa: E402

_PROVIDERS = settings_mod._PROVIDERS
_PROVIDER_KEYS = settings_mod._PROVIDER_KEYS
_PROVIDER_LABELS = settings_mod._PROVIDER_LABELS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_st(radio_value: str = "Anthropic (Claude)", key_input: str = "") -> MagicMock:
    """Return a fresh st mock and wire it into the settings module."""
    mock = _make_st_mock()
    mock.radio.return_value = radio_value
    mock.text_input.return_value = key_input
    mock.columns.return_value = _make_cols(3)
    settings_mod.st = mock
    return mock


def _all_status_false() -> dict[str, bool]:
    return {"anthropic": False, "openai": False, "google_gemini": False}


def _all_status_true() -> dict[str, bool]:
    return {"anthropic": True, "openai": True, "google_gemini": True}


# ---------------------------------------------------------------------------
# No interaction — returns None
# ---------------------------------------------------------------------------

class TestNoInteraction:
    def test_returns_none_when_nothing_clicked(self):
        st = _fresh_st()
        st.button.return_value = False
        result = render_settings("anthropic", _all_status_false())
        assert result is None

    def test_returns_none_when_provider_unchanged(self):
        st = _fresh_st(radio_value="Anthropic (Claude)")
        st.button.return_value = False
        result = render_settings("anthropic", _all_status_false())
        assert result is None


# ---------------------------------------------------------------------------
# Provider change
# ---------------------------------------------------------------------------

class TestProviderChange:
    def test_returns_change_provider_event_for_openai(self):
        _fresh_st(radio_value="OpenAI (GPT)")
        result = render_settings("anthropic", _all_status_false())
        assert result == {"action": "change_provider", "provider": "openai"}

    def test_returns_change_provider_event_for_gemini(self):
        _fresh_st(radio_value="Google Gemini")
        result = render_settings("anthropic", _all_status_false())
        assert result == {"action": "change_provider", "provider": "google_gemini"}

    def test_no_event_when_provider_matches(self):
        st = _fresh_st(radio_value="OpenAI (GPT)")
        st.button.return_value = False
        result = render_settings("openai", _all_status_false())
        assert result is None


# ---------------------------------------------------------------------------
# Save key
# ---------------------------------------------------------------------------

class TestSaveKey:
    def test_returns_save_key_event_with_api_key_value(self):
        st = _fresh_st(key_input="sk-ant-real-key")
        # Save button returns True, clear button False
        st.button.side_effect = [True, False]
        result = render_settings("anthropic", _all_status_false())
        assert result == {
            "action": "save_key",
            "provider": "anthropic",
            "api_key": "sk-ant-real-key",
        }

    def test_save_button_disabled_when_key_input_empty(self):
        st = _fresh_st(key_input="")
        st.button.return_value = False
        render_settings("anthropic", _all_status_false())
        # Verify save button was called with disabled=True
        save_calls = [
            call for call in st.button.call_args_list
            if call.args and call.args[0] == "保存"
        ]
        assert save_calls, "保存 button was never rendered"
        save_call = save_calls[0]
        assert save_call.kwargs.get("disabled") is True

    def test_save_button_enabled_when_key_present(self):
        st = _fresh_st(radio_value="Google Gemini", key_input="AIza-some-key")
        st.button.return_value = False
        render_settings("google_gemini", _all_status_false())
        save_calls = [
            call for call in st.button.call_args_list
            if call.args and call.args[0] == "保存"
        ]
        assert save_calls
        save_call = save_calls[0]
        assert save_call.kwargs.get("disabled") is False

    def test_api_key_not_written_to_session_state(self):
        st = _fresh_st(key_input="sk-secret-key")
        st.button.side_effect = [True, False]
        render_settings("anthropic", _all_status_false())
        # Session state must not contain the key value
        secret = "sk-secret-key"
        for v in st.session_state.values():
            assert v != secret, "API key value leaked into session_state"


# ---------------------------------------------------------------------------
# Clear key
# ---------------------------------------------------------------------------

class TestClearKey:
    def test_returns_clear_key_event(self):
        st = _fresh_st()
        # Save button False, clear button True
        st.button.side_effect = [False, True]
        result = render_settings("anthropic", {"anthropic": True, "openai": False, "google_gemini": False})
        assert result == {"action": "clear_key", "provider": "anthropic"}

    def test_clear_button_not_rendered_when_no_key(self):
        st = _fresh_st()
        st.button.return_value = False
        render_settings("openai", {"anthropic": False, "openai": False, "google_gemini": False})
        # The "削除" button should never have been rendered
        delete_calls = [
            call for call in st.button.call_args_list
            if call.args and call.args[0] == "削除"
        ]
        assert not delete_calls, "削除 button was rendered even though no key is stored"

    def test_clear_button_rendered_when_key_exists(self):
        st = _fresh_st()
        st.button.return_value = False
        render_settings("anthropic", {"anthropic": True, "openai": False, "google_gemini": False})
        delete_calls = [
            call for call in st.button.call_args_list
            if call.args and call.args[0] == "削除"
        ]
        assert delete_calls, "削除 button was NOT rendered even though key is stored"


# ---------------------------------------------------------------------------
# Key status display
# ---------------------------------------------------------------------------

class TestKeyStatusDisplay:
    def test_success_shown_when_key_configured(self):
        st = _fresh_st()
        st.button.return_value = False
        render_settings("anthropic", {"anthropic": True, "openai": False, "google_gemini": False})
        st.success.assert_called()

    def test_warning_shown_when_key_missing(self):
        st = _fresh_st(radio_value="OpenAI (GPT)")
        st.button.return_value = False
        render_settings("openai", {"anthropic": True, "openai": False, "google_gemini": False})
        st.warning.assert_called()
