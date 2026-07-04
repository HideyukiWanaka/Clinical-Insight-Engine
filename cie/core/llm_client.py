"""CIE Platform — Provider-agnostic LLM client.

Supports three providers out of the box:
  - ``anthropic``    — Anthropic Messages API (Claude)
  - ``openai``       — OpenAI Chat Completions API (GPT)
  - ``google_gemini`` — Google Gemini via OpenAI-compatible endpoint

Provider is selected at construction time.  API keys are injected as plain
strings (callers read them from environment variables or keyring).

Usage:
    client = LLMClient(provider="google_gemini", api_key="AIza...")
    text = await client.complete(system="...", user="...")
"""

from __future__ import annotations

import os
from typing import Literal

import httpx

Provider = Literal["anthropic", "openai", "google_gemini"]

_ENDPOINTS: dict[str, str] = {
    "anthropic":    "https://api.anthropic.com/v1/messages",
    "openai":       "https://api.openai.com/v1/chat/completions",
    "google_gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
}

_DEFAULT_MODELS: dict[str, str] = {
    "anthropic":    "claude-haiku-4-5-20251001",
    "openai":       "gpt-4o-mini",
    "google_gemini": "gemini-3.5-flash",
}

_ENV_KEY_NAMES: dict[str, str] = {
    "anthropic":    "ANTHROPIC_API_KEY",
    "openai":       "OPENAI_API_KEY",
    "google_gemini": "GOOGLE_GEMINI_API_KEY",
}

_DEFAULT_MAX_TOKENS = 1024
_DEFAULT_TIMEOUT = 30.0


class LLMError(Exception):
    """Raised when an LLM API call fails."""

    def __init__(self, message: str, provider: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class LLMClient:
    """Unified async LLM client for Anthropic, OpenAI, and Google Gemini.

    Args:
        provider:    One of ``"anthropic"``, ``"openai"``, ``"google_gemini"``.
        api_key:     Provider API key.  If omitted, read from the environment
                     variable named in ``_ENV_KEY_NAMES[provider]``.
        model:       Model identifier.  Defaults to the provider's recommended
                     fast model if not supplied.
        http_client: Optional pre-configured ``httpx.AsyncClient`` (useful for
                     testing or connection pooling).  A new client is created
                     if not supplied.
        timeout:     Request timeout in seconds (default 30).
        max_tokens:  Maximum tokens for the completion (default 1024).
    """

    def __init__(
        self,
        provider: str,
        api_key: str = "",
        model: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        if provider not in _ENDPOINTS:
            raise ValueError(
                f"Unsupported LLM provider: '{provider}'. "
                f"Supported: {sorted(_ENDPOINTS)}"
            )
        self._provider = provider
        self._api_key = api_key or os.environ.get(_ENV_KEY_NAMES[provider], "")
        self._model = model or _DEFAULT_MODELS[provider]
        self._endpoint = _ENDPOINTS[provider]
        self._timeout = timeout
        self._max_tokens = max_tokens
        # None means create a fresh client per request (avoids "event loop is closed"
        # when asyncio.run() is called multiple times across Streamlit rerenders).
        self._http: httpx.AsyncClient | None = http_client

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, system: str, user: str) -> str:
        """Send a system + user prompt and return the text completion.

        Args:
            system: System prompt (instructions / persona).
            user:   User message content.

        Returns:
            The model's text response as a plain string.

        Raises:
            LLMError: On HTTP errors or unexpected response shape.
        """
        if self._http is not None:
            return await self._dispatch(self._http, system, user)
        async with httpx.AsyncClient() as http:
            return await self._dispatch(http, system, user)

    async def _dispatch(self, http: httpx.AsyncClient, system: str, user: str) -> str:
        if self._provider == "anthropic":
            return await self._complete_anthropic(http, system, user)
        else:
            return await self._complete_openai_compat(http, system, user)

    # ------------------------------------------------------------------
    # Provider-specific implementations
    # ------------------------------------------------------------------

    async def _complete_anthropic(self, http: httpx.AsyncClient, system: str, user: str) -> str:
        """Call the Anthropic Messages API."""
        try:
            response = await http.post(
                self._endpoint,
                json={
                    "model": self._model,
                    "max_tokens": self._max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            return response.json()["content"][0]["text"]
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"Anthropic API error {exc.response.status_code}: {exc.response.text[:200]}",
                provider="anthropic",
                status_code=exc.response.status_code,
            ) from exc
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(str(exc), provider="anthropic") from exc

    async def _complete_openai_compat(self, http: httpx.AsyncClient, system: str, user: str) -> str:
        """Call an OpenAI-compatible Chat Completions endpoint.

        Works for both OpenAI and Google Gemini (which exposes an
        OpenAI-compatible REST endpoint at the configured URL).
        """
        try:
            response = await http.post(
                self._endpoint,
                json={
                    "model": self._model,
                    "max_tokens": self._max_tokens,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"{self._provider} API error {exc.response.status_code}: {exc.response.text[:200]}",
                provider=self._provider,
                status_code=exc.response.status_code,
            ) from exc
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(str(exc), provider=self._provider) from exc

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying HTTP client (only relevant when http_client was injected)."""
        if self._http is not None:
            await self._http.aclose()

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


def llm_client_from_env(
    provider: str | None = None,
    model: str | None = None,
) -> LLMClient:
    """Convenience factory that reads provider and API key from keyring or environment.

    Provider is resolved in this order:
      1. ``provider`` argument (if supplied)
      2. ``CIE_ACTIVE_AI_PROVIDER`` environment variable
      3. Falls back to ``"anthropic"``

    API key is resolved in this order:
      1. OS keyring (via ``cie.core.secrets_store``)
      2. Matching ``*_API_KEY`` environment variable

    Args:
        provider: Optional provider override.
        model:    Optional model override.

    Returns:
        A configured :class:`LLMClient` instance.
    """
    resolved_provider = provider or os.environ.get("CIE_ACTIVE_AI_PROVIDER", "anthropic")

    api_key: str = ""
    try:
        from cie.core.secrets_store import load_api_key
        loaded = load_api_key(resolved_provider)
        if loaded:
            api_key = loaded
    except Exception:
        pass

    if not api_key:
        api_key = os.environ.get(_ENV_KEY_NAMES.get(resolved_provider, ""), "")

    return LLMClient(provider=resolved_provider, api_key=api_key, model=model)


__all__ = ["LLMClient", "LLMError", "Provider", "llm_client_from_env"]
