"""Unit tests for cie.core.llm_client.LLMClient.

All HTTP calls are mocked via httpx.AsyncClient injection — no real API keys
or network connections are required.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from cie.core.llm_client import LLMClient, LLMError, llm_client_from_env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_http(status: int = 200, body: dict | None = None) -> MagicMock:
    """Return a fake httpx.AsyncClient whose post() returns a mock response."""
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body or {}
    if status >= 400:
        import httpx
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status}",
            request=MagicMock(),
            response=response,
        )
        response.text = f"Error {status}"
    else:
        response.raise_for_status.return_value = None

    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    return client


def _anthropic_body(text: str) -> dict:
    return {"content": [{"text": text}]}


def _openai_body(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_invalid_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            LLMClient(provider="unknown_provider", api_key="key")

    def test_default_model_anthropic(self):
        c = LLMClient("anthropic", "key", http_client=MagicMock())
        assert "claude" in c.model

    def test_default_model_openai(self):
        c = LLMClient("openai", "key", http_client=MagicMock())
        assert "gpt" in c.model

    def test_default_model_google_gemini(self):
        c = LLMClient("google_gemini", "key", http_client=MagicMock())
        assert "gemini" in c.model

    def test_custom_model_respected(self):
        c = LLMClient("anthropic", "key", model="claude-opus-4-8", http_client=MagicMock())
        assert c.model == "claude-opus-4-8"

    def test_provider_property(self):
        c = LLMClient("openai", "key", http_client=MagicMock())
        assert c.provider == "openai"

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-123")
        c = LLMClient("anthropic", http_client=MagicMock())
        assert c._api_key == "env-key-123"


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------

class TestAnthropicProvider:
    @pytest.mark.asyncio
    async def test_complete_returns_text(self):
        http = _mock_http(200, _anthropic_body('{"objective": "between_group_comparison"}'))
        c = LLMClient("anthropic", "sk-ant-test", http_client=http)
        result = await c.complete("system prompt", "user message")
        assert result == '{"objective": "between_group_comparison"}'

    @pytest.mark.asyncio
    async def test_uses_correct_endpoint(self):
        http = _mock_http(200, _anthropic_body("ok"))
        c = LLMClient("anthropic", "sk-ant-test", http_client=http)
        await c.complete("s", "u")
        url = http.post.call_args[0][0]
        assert "api.anthropic.com" in url

    @pytest.mark.asyncio
    async def test_sends_api_key_header(self):
        http = _mock_http(200, _anthropic_body("ok"))
        c = LLMClient("anthropic", "my-secret-key", http_client=http)
        await c.complete("s", "u")
        headers = http.post.call_args[1]["headers"]
        assert headers["x-api-key"] == "my-secret-key"

    @pytest.mark.asyncio
    async def test_sends_anthropic_version_header(self):
        http = _mock_http(200, _anthropic_body("ok"))
        c = LLMClient("anthropic", "key", http_client=http)
        await c.complete("s", "u")
        headers = http.post.call_args[1]["headers"]
        assert "anthropic-version" in headers

    @pytest.mark.asyncio
    async def test_system_in_body_not_messages(self):
        """Anthropic API takes system as a top-level field, not in messages."""
        http = _mock_http(200, _anthropic_body("ok"))
        c = LLMClient("anthropic", "key", http_client=http)
        await c.complete("my system", "my user")
        body = http.post.call_args[1]["json"]
        assert body["system"] == "my system"
        assert body["messages"][0]["role"] == "user"
        assert body["messages"][0]["content"] == "my user"

    @pytest.mark.asyncio
    async def test_http_error_raises_llm_error(self):
        http = _mock_http(401, {})
        http.post.return_value.text = "Unauthorized"
        c = LLMClient("anthropic", "bad-key", http_client=http)
        with pytest.raises(LLMError) as exc_info:
            await c.complete("s", "u")
        assert exc_info.value.provider == "anthropic"
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------

class TestOpenAIProvider:
    @pytest.mark.asyncio
    async def test_complete_returns_text(self):
        http = _mock_http(200, _openai_body("response text"))
        c = LLMClient("openai", "sk-test", http_client=http)
        result = await c.complete("system", "user")
        assert result == "response text"

    @pytest.mark.asyncio
    async def test_uses_correct_endpoint(self):
        http = _mock_http(200, _openai_body("ok"))
        c = LLMClient("openai", "key", http_client=http)
        await c.complete("s", "u")
        url = http.post.call_args[0][0]
        assert "openai.com" in url

    @pytest.mark.asyncio
    async def test_sends_bearer_auth(self):
        http = _mock_http(200, _openai_body("ok"))
        c = LLMClient("openai", "my-openai-key", http_client=http)
        await c.complete("s", "u")
        headers = http.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer my-openai-key"

    @pytest.mark.asyncio
    async def test_system_in_messages(self):
        """OpenAI-compat API takes system as a message with role='system'."""
        http = _mock_http(200, _openai_body("ok"))
        c = LLMClient("openai", "key", http_client=http)
        await c.complete("my system", "my user")
        messages = http.post.call_args[1]["json"]["messages"]
        assert messages[0] == {"role": "system", "content": "my system"}
        assert messages[1] == {"role": "user", "content": "my user"}

    @pytest.mark.asyncio
    async def test_http_error_raises_llm_error(self):
        http = _mock_http(429, {})
        http.post.return_value.text = "Rate limit"
        c = LLMClient("openai", "key", http_client=http)
        with pytest.raises(LLMError) as exc_info:
            await c.complete("s", "u")
        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# Google Gemini provider
# ---------------------------------------------------------------------------

class TestGeminiProvider:
    @pytest.mark.asyncio
    async def test_complete_returns_text(self):
        http = _mock_http(200, _openai_body("gemini response"))
        c = LLMClient("google_gemini", "AIza-test", http_client=http)
        result = await c.complete("system", "user")
        assert result == "gemini response"

    @pytest.mark.asyncio
    async def test_uses_gemini_endpoint(self):
        http = _mock_http(200, _openai_body("ok"))
        c = LLMClient("google_gemini", "key", http_client=http)
        await c.complete("s", "u")
        url = http.post.call_args[0][0]
        assert "generativelanguage.googleapis.com" in url

    @pytest.mark.asyncio
    async def test_sends_bearer_auth(self):
        http = _mock_http(200, _openai_body("ok"))
        c = LLMClient("google_gemini", "my-gemini-key", http_client=http)
        await c.complete("s", "u")
        headers = http.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer my-gemini-key"

    @pytest.mark.asyncio
    async def test_uses_openai_compat_message_format(self):
        """Gemini uses the same OpenAI-compatible format as OpenAI."""
        http = _mock_http(200, _openai_body("ok"))
        c = LLMClient("google_gemini", "key", http_client=http)
        await c.complete("sys", "usr")
        messages = http.post.call_args[1]["json"]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_GEMINI_API_KEY", "gemini-env-key")
        http = _mock_http(200, _openai_body("ok"))
        c = LLMClient("google_gemini", http_client=http)
        await c.complete("s", "u")
        headers = http.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer gemini-env-key"


# ---------------------------------------------------------------------------
# llm_client_from_env factory
# ---------------------------------------------------------------------------

class TestFactory:
    def test_defaults_to_anthropic(self, monkeypatch):
        monkeypatch.delenv("CIE_ACTIVE_AI_PROVIDER", raising=False)
        c = llm_client_from_env()
        assert c.provider == "anthropic"

    def test_reads_provider_from_env(self, monkeypatch):
        monkeypatch.setenv("CIE_ACTIVE_AI_PROVIDER", "openai")
        c = llm_client_from_env()
        assert c.provider == "openai"

    def test_provider_arg_overrides_env(self, monkeypatch):
        monkeypatch.setenv("CIE_ACTIVE_AI_PROVIDER", "openai")
        c = llm_client_from_env(provider="google_gemini")
        assert c.provider == "google_gemini"

    def test_model_arg_passed_through(self, monkeypatch):
        monkeypatch.delenv("CIE_ACTIVE_AI_PROVIDER", raising=False)
        c = llm_client_from_env(model="claude-opus-4-8")
        assert c.model == "claude-opus-4-8"


# ---------------------------------------------------------------------------
# Multi-turn + streaming (Phase 1 additions)
# ---------------------------------------------------------------------------


class _FakeStreamResponse:
    def __init__(self, status_code: int, lines: list[str]) -> None:
        self.status_code = status_code
        self._lines = lines

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln

    async def aread(self) -> bytes:
        return b"stream error body"


class _FakeStreamCM:
    def __init__(self, resp: _FakeStreamResponse) -> None:
        self._resp = resp

    async def __aenter__(self) -> _FakeStreamResponse:
        return self._resp

    async def __aexit__(self, *_: object) -> bool:
        return False


def _mock_stream_http(lines: list[str], status: int = 200) -> MagicMock:
    http = MagicMock()
    http.stream = MagicMock(return_value=_FakeStreamCM(_FakeStreamResponse(status, lines)))
    return http


async def _collect(agen) -> str:
    return "".join([chunk async for chunk in agen])


class TestMultiTurn:
    @pytest.mark.asyncio
    async def test_complete_messages_sends_all_turns_anthropic(self):
        http = _mock_http(200, _anthropic_body("ok"))
        c = LLMClient("anthropic", "key", http_client=http)
        turns = [
            {"role": "user", "content": "男女の血圧を比較したい"},
            {"role": "assistant", "content": "収縮期血圧で比較しますか？"},
            {"role": "user", "content": "はい"},
        ]
        await c.complete_messages("sys", turns)
        body = http.post.call_args[1]["json"]
        assert body["system"] == "sys"
        assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
        assert body["messages"][-1]["content"] == "はい"

    @pytest.mark.asyncio
    async def test_complete_still_single_user_turn(self):
        # Backward-compat: complete() must still produce one user message.
        http = _mock_http(200, _anthropic_body("ok"))
        c = LLMClient("anthropic", "key", http_client=http)
        await c.complete("my system", "my user")
        body = http.post.call_args[1]["json"]
        assert body["messages"] == [{"role": "user", "content": "my user"}]


class TestStreaming:
    @pytest.mark.asyncio
    async def test_stream_anthropic_yields_text_deltas(self):
        lines = [
            "event: content_block_delta",
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}',
            "",
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":" 世界"}}',
            "data: [DONE]",
        ]
        c = LLMClient("anthropic", "key", http_client=_mock_stream_http(lines))
        out = await _collect(c.stream_messages("sys", [{"role": "user", "content": "hi"}]))
        assert out == "Hello 世界"

    @pytest.mark.asyncio
    async def test_stream_openai_yields_delta_content(self):
        lines = [
            'data: {"choices":[{"delta":{"content":"Foo"}}]}',
            'data: {"choices":[{"delta":{"content":"bar"}}]}',
            "data: [DONE]",
        ]
        c = LLMClient("openai", "key", http_client=_mock_stream_http(lines))
        out = await _collect(c.stream_messages("sys", [{"role": "user", "content": "hi"}]))
        assert out == "Foobar"

    @pytest.mark.asyncio
    async def test_stream_prefill_is_yielded_first(self):
        lines = ['data: {"choices":[{"delta":{"content":"code"}}]}', "data: [DONE]"]
        c = LLMClient("openai", "key", http_client=_mock_stream_http(lines))
        out = await _collect(
            c.stream_messages("sys", [{"role": "user", "content": "x"}], assistant_prefill="```r\n")
        )
        assert out == "```r\ncode"

    @pytest.mark.asyncio
    async def test_stream_http_error_raises_llm_error(self):
        c = LLMClient("anthropic", "key", http_client=_mock_stream_http([], status=429))
        with pytest.raises(LLMError) as exc_info:
            await _collect(c.stream_messages("sys", [{"role": "user", "content": "x"}]))
        assert exc_info.value.status_code == 429
