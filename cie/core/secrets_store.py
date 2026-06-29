"""CIE Platform — OS keyring-based API key storage.

API keys are stored in the OS-level secure credential store
(macOS Keychain, Windows Credential Manager, Linux Secret Service).
Environment variables are used as a fallback for headless/CI environments.

Security invariants:
- API key values are never logged or stored in plaintext outside the keyring.
- ``has_api_key()`` returns only a boolean — no key value is exposed.
- ``load_api_key()`` is the single retrieval path; callers must not cache
  the returned string beyond immediate use.
"""

from __future__ import annotations

import os

import keyring
import keyring.errors

from cie.core.exceptions import CIEError

SERVICE_NAME = "cie-platform"

_KEYRING_KEY_NAMES: dict[str, str] = {
    "anthropic":     "anthropic_api_key",
    "openai":        "openai_api_key",
    "google_gemini": "google_gemini_api_key",
}

_ENV_FALLBACK: dict[str, str] = {
    "anthropic":     "ANTHROPIC_API_KEY",
    "openai":        "OPENAI_API_KEY",
    "google_gemini": "GOOGLE_GEMINI_API_KEY",
}


def _validate_provider(provider: str) -> str:
    """Return the keyring key name for a provider, or raise ValueError."""
    key_name = _KEYRING_KEY_NAMES.get(provider)
    if key_name is None:
        raise ValueError(
            f"Unknown provider: {provider!r}. "
            f"Supported: {sorted(_KEYRING_KEY_NAMES)}"
        )
    return key_name


def save_api_key(provider: str, key: str) -> None:
    """Store an API key in the OS keyring.

    Args:
        provider: LLM provider identifier (``"anthropic"``, ``"openai"``,
                  ``"google_gemini"``).
        key: The API key value to store.

    Raises:
        ValueError: If ``provider`` is not a known provider.
        CIEError: If the keyring is locked (cannot write).
        keyring.errors.NoKeyringError: If no keyring backend is available
            (propagated so the UI can show an appropriate error).
    """
    key_name = _validate_provider(provider)
    try:
        keyring.set_password(SERVICE_NAME, key_name, key)
    except keyring.errors.KeyringLocked as exc:
        raise CIEError(
            "キーチェーンがロックされています。デバイスのロックを解除してから再試行してください。",
        ) from exc


def load_api_key(provider: str) -> str | None:
    """Load an API key from the OS keyring, falling back to environment variables.

    Resolution order:
      1. OS keyring (macOS Keychain / Windows Credential Manager / Linux SS)
      2. Environment variable (``ANTHROPIC_API_KEY``, etc.) — for CI/headless

    Args:
        provider: LLM provider identifier.

    Returns:
        The API key string, or ``None`` if not configured in either location.

    Raises:
        ValueError: If ``provider`` is not a known provider.
        CIEError: If the keyring is locked (cannot read).
    """
    key_name = _validate_provider(provider)
    try:
        value = keyring.get_password(SERVICE_NAME, key_name)
        if value is not None:
            return value
    except keyring.errors.KeyringLocked as exc:
        raise CIEError(
            "キーチェーンがロックされています。デバイスのロックを解除してから再試行してください。",
        ) from exc
    except keyring.errors.NoKeyringError:
        pass

    return os.environ.get(_ENV_FALLBACK.get(provider, "")) or None


def delete_api_key(provider: str) -> None:
    """Remove an API key from the OS keyring.

    Idempotent: does nothing if the key is not present.

    Args:
        provider: LLM provider identifier.

    Raises:
        ValueError: If ``provider`` is not a known provider.
    """
    key_name = _validate_provider(provider)
    try:
        keyring.delete_password(SERVICE_NAME, key_name)
    except keyring.errors.PasswordDeleteError:
        pass
    except keyring.errors.NoKeyringError:
        pass


def has_api_key(provider: str) -> bool:
    """Return ``True`` if an API key is configured for the given provider.

    This is the only value the settings UI should display — never the key itself.

    Args:
        provider: LLM provider identifier.

    Returns:
        ``True`` if a key is stored in keyring or environment variable.

    Raises:
        ValueError: If ``provider`` is not a known provider.
    """
    return load_api_key(provider) is not None


__all__ = [
    "SERVICE_NAME",
    "save_api_key",
    "load_api_key",
    "delete_api_key",
    "has_api_key",
]
