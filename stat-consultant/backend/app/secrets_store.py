"""OS keyring-based API key storage (BYOK).

Translated from ``cie/core/secrets_store.py``. Keys are stored in the OS-level
secure credential store (macOS Keychain / Windows Credential Manager / Linux
Secret Service); environment variables are a read fallback for headless/CI.

Security invariants:
- Key values are never logged or persisted in plaintext outside the keyring.
- ``has_api_key()`` returns only a boolean — the key value is never exposed.
- ``load_api_key()`` is the single retrieval path; callers must not cache the
  returned string beyond immediate use.
"""

from __future__ import annotations

import os

import keyring
import keyring.errors

SERVICE_NAME = "stat-consultant"

_KEYRING_KEY_NAMES: dict[str, str] = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "gemini_api_key",
}

# Env var(s) checked as a fallback when no keyring value is stored. Gemini has
# two accepted names (matches models_registry).
_ENV_FALLBACK: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


class KeyringUnavailableError(RuntimeError):
    """Raised when a key cannot be written (locked or no keychain backend)."""


def _validate_provider(provider: str) -> str:
    key_name = _KEYRING_KEY_NAMES.get(provider)
    if key_name is None:
        raise ValueError(
            f"Unknown provider: {provider!r}. Supported: {sorted(_KEYRING_KEY_NAMES)}"
        )
    return key_name


def _env_key(provider: str) -> str | None:
    for name in _ENV_FALLBACK.get(provider, ()):
        value = os.environ.get(name)
        if value:
            return value
    return None


def save_api_key(provider: str, key: str) -> None:
    """Store an API key in the OS keyring.

    Raises:
        ValueError: unknown provider.
        KeyringUnavailableError: the keyring is locked or unavailable (so the
            endpoint can tell the user to use the keychain / env var instead).
    """
    key_name = _validate_provider(provider)
    try:
        keyring.set_password(SERVICE_NAME, key_name, key)
    except keyring.errors.KeyringLocked as exc:
        raise KeyringUnavailableError(
            "キーチェーンがロックされています。デバイスのロックを解除して再試行してください。"
        ) from exc
    except keyring.errors.NoKeyringError as exc:
        raise KeyringUnavailableError(
            "この環境ではOSキーチェーンが使えません。環境変数でキーを設定してください。"
        ) from exc


def load_api_key(provider: str) -> str | None:
    """Load an API key: OS keyring first, then environment variable fallback."""
    key_name = _validate_provider(provider)
    try:
        value = keyring.get_password(SERVICE_NAME, key_name)
        if value is not None:
            return value
    except keyring.errors.NoKeyringError:
        pass
    except keyring.errors.KeyringError:
        pass
    return _env_key(provider)


def delete_api_key(provider: str) -> None:
    """Remove a provider's stored key. Idempotent; env fallback is untouched."""
    key_name = _validate_provider(provider)
    try:
        keyring.delete_password(SERVICE_NAME, key_name)
    except (keyring.errors.PasswordDeleteError, keyring.errors.NoKeyringError):
        pass
    except keyring.errors.KeyringError:
        pass


def has_api_key(provider: str) -> bool:
    """Whether a key is configured for ``provider`` (keyring or env)."""
    return load_api_key(provider) is not None


__all__ = [
    "SERVICE_NAME",
    "KeyringUnavailableError",
    "save_api_key",
    "load_api_key",
    "delete_api_key",
    "has_api_key",
]
