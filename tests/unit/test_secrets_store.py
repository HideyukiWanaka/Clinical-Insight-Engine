"""Unit tests for cie.core.secrets_store.

The keyring module is mocked at the sys.modules level before any import of
secrets_store, so no real OS keyring is ever accessed.
"""

from __future__ import annotations

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Build and inject a fake keyring module BEFORE importing secrets_store
# ---------------------------------------------------------------------------

def _make_keyring_mock() -> MagicMock:
    """Return a MagicMock that mimics the keyring package."""
    errors_mod = ModuleType("keyring.errors")

    class NoKeyringError(Exception):
        pass

    class PasswordDeleteError(Exception):
        pass

    class PasswordSetError(Exception):
        pass

    class KeyringLocked(Exception):
        pass

    errors_mod.NoKeyringError = NoKeyringError          # type: ignore[attr-defined]
    errors_mod.PasswordDeleteError = PasswordDeleteError  # type: ignore[attr-defined]
    errors_mod.PasswordSetError = PasswordSetError      # type: ignore[attr-defined]
    errors_mod.KeyringLocked = KeyringLocked            # type: ignore[attr-defined]

    kr = MagicMock(name="keyring")
    kr.errors = errors_mod
    kr.get_password = MagicMock(return_value=None)
    kr.set_password = MagicMock(return_value=None)
    kr.delete_password = MagicMock(return_value=None)
    return kr


_keyring_mock = _make_keyring_mock()
sys.modules["keyring"] = _keyring_mock           # type: ignore[assignment]
sys.modules["keyring.errors"] = _keyring_mock.errors  # type: ignore[assignment]

# Now it is safe to import secrets_store
from cie.core.secrets_store import (  # noqa: E402
    SERVICE_NAME,
    delete_api_key,
    has_api_key,
    load_api_key,
    save_api_key,
)
from cie.core.exceptions import CIEError  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_mock() -> None:
    """Reset all mock call records between tests."""
    _keyring_mock.get_password.reset_mock(return_value=True)
    _keyring_mock.set_password.reset_mock()
    _keyring_mock.delete_password.reset_mock()
    _keyring_mock.get_password.return_value = None
    _keyring_mock.set_password.return_value = None
    _keyring_mock.delete_password.return_value = None
    _keyring_mock.get_password.side_effect = None
    _keyring_mock.set_password.side_effect = None
    _keyring_mock.delete_password.side_effect = None


# ---------------------------------------------------------------------------
# save_api_key
# ---------------------------------------------------------------------------

class TestSaveApiKey:
    def setup_method(self):
        _reset_mock()

    def test_calls_keyring_set_password(self):
        save_api_key("anthropic", "sk-ant-test")
        _keyring_mock.set_password.assert_called_once_with(
            SERVICE_NAME, "anthropic_api_key", "sk-ant-test"
        )

    def test_openai_uses_correct_key_name(self):
        save_api_key("openai", "sk-openai-key")
        _keyring_mock.set_password.assert_called_once_with(
            SERVICE_NAME, "openai_api_key", "sk-openai-key"
        )

    def test_google_gemini_uses_correct_key_name(self):
        save_api_key("google_gemini", "AIza-key")
        _keyring_mock.set_password.assert_called_once_with(
            SERVICE_NAME, "google_gemini_api_key", "AIza-key"
        )

    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            save_api_key("unknown_llm", "some-key")

    def test_keyring_locked_raises_cie_error(self):
        _keyring_mock.set_password.side_effect = _keyring_mock.errors.KeyringLocked("locked")
        with pytest.raises(CIEError):
            save_api_key("anthropic", "sk-ant-test")

    def test_no_keyring_error_propagates(self):
        _keyring_mock.set_password.side_effect = _keyring_mock.errors.NoKeyringError("no backend")
        with pytest.raises(_keyring_mock.errors.NoKeyringError):
            save_api_key("anthropic", "sk-ant-test")


# ---------------------------------------------------------------------------
# load_api_key
# ---------------------------------------------------------------------------

class TestLoadApiKey:
    def setup_method(self):
        _reset_mock()

    def test_returns_value_from_keyring(self):
        _keyring_mock.get_password.return_value = "sk-ant-stored"
        result = load_api_key("anthropic")
        assert result == "sk-ant-stored"

    def test_returns_none_when_keyring_has_no_value(self):
        _keyring_mock.get_password.return_value = None
        result = load_api_key("anthropic")
        assert result is None

    def test_falls_back_to_env_on_no_keyring_error(self, monkeypatch):
        _keyring_mock.get_password.side_effect = _keyring_mock.errors.NoKeyringError("no backend")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-fallback-key")
        result = load_api_key("anthropic")
        assert result == "env-fallback-key"

    def test_falls_back_to_env_for_openai(self, monkeypatch):
        _keyring_mock.get_password.side_effect = _keyring_mock.errors.NoKeyringError("no backend")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-env-key")
        result = load_api_key("openai")
        assert result == "openai-env-key"

    def test_falls_back_to_env_for_gemini(self, monkeypatch):
        _keyring_mock.get_password.side_effect = _keyring_mock.errors.NoKeyringError("no backend")
        monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "gemini-env-key")
        result = load_api_key("google_gemini")
        assert result == "gemini-env-key"

    def test_returns_none_when_neither_keyring_nor_env(self, monkeypatch):
        _keyring_mock.get_password.side_effect = _keyring_mock.errors.NoKeyringError("no backend")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = load_api_key("anthropic")
        assert result is None

    def test_keyring_locked_raises_cie_error(self):
        _keyring_mock.get_password.side_effect = _keyring_mock.errors.KeyringLocked("locked")
        with pytest.raises(CIEError):
            load_api_key("anthropic")

    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            load_api_key("bad_provider")

    def test_keyring_called_with_correct_args(self):
        _keyring_mock.get_password.return_value = "key"
        load_api_key("google_gemini")
        _keyring_mock.get_password.assert_called_once_with(SERVICE_NAME, "google_gemini_api_key")


# ---------------------------------------------------------------------------
# delete_api_key
# ---------------------------------------------------------------------------

class TestDeleteApiKey:
    def setup_method(self):
        _reset_mock()

    def test_calls_keyring_delete_password(self):
        delete_api_key("anthropic")
        _keyring_mock.delete_password.assert_called_once_with(
            SERVICE_NAME, "anthropic_api_key"
        )

    def test_ignores_password_delete_error(self):
        _keyring_mock.delete_password.side_effect = _keyring_mock.errors.PasswordDeleteError("not found")
        delete_api_key("openai")  # should not raise

    def test_ignores_no_keyring_error(self):
        _keyring_mock.delete_password.side_effect = _keyring_mock.errors.NoKeyringError("no backend")
        delete_api_key("anthropic")  # should not raise

    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            delete_api_key("bad_provider")


# ---------------------------------------------------------------------------
# has_api_key
# ---------------------------------------------------------------------------

class TestHasApiKey:
    def setup_method(self):
        _reset_mock()

    def test_returns_true_when_key_exists(self):
        _keyring_mock.get_password.return_value = "some-key"
        assert has_api_key("anthropic") is True

    def test_returns_false_when_key_absent(self, monkeypatch):
        _keyring_mock.get_password.return_value = None
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert has_api_key("anthropic") is False

    def test_returns_true_via_env_fallback(self, monkeypatch):
        _keyring_mock.get_password.side_effect = _keyring_mock.errors.NoKeyringError("no backend")
        monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "env-key")
        assert has_api_key("google_gemini") is True

    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            has_api_key("bad_provider")
