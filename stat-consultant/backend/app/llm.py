"""Thin Claude streaming wrapper (Step 1).

Translated from the LLM-call lifecycle in ``cie/api/deps.py`` (``invoke_agent``):
the original wraps every agent run in ``try: ... finally: revoke`` so the
capability token is always released (CLAUDE.md / SPEC §10). Here the minimal
form is the streaming context manager — ``async with client.messages.stream(...)``
guarantees the stream (and its HTTP resources) are torn down on every exit path,
success or error, which is exactly the try/finally invariant the port preserves.

Auth is zero-config: ``AsyncAnthropic()`` resolves ``ANTHROPIC_API_KEY`` (or an
``ant auth login`` profile) from the environment — nothing is hardcoded.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

# Opus 4.8 is the current, most capable, Vision-capable model — the right default
# for statistical advice where correctness matters (SPEC §6, 痛み②手法選択).
_MODEL = "claude-opus-4-8"
# Streaming reply, so a generous ceiling is safe (no HTTP-timeout risk).
_MAX_TOKENS = 8000

# One process-wide async client. Constructed lazily so importing this module
# never requires credentials to be present (e.g. at test-collection time).
_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()
    return _client


async def stream_reply(
    system: str, messages: list[dict]
) -> AsyncIterator[str]:
    """Stream Claude's reply as incremental text chunks.

    Yields text deltas as the model produces them. ``thinking`` is adaptive so
    the model decides how much to reason per turn (deep for a real methods
    question, none for chitchat); thinking deltas are not part of
    ``text_stream``, so only the user-facing answer is yielded.

    Args:
        system:   The persona/system prompt.
        messages: Ordered turns ``[{"role", "content"}, ...]`` (oldest→newest).

    The ``async with`` context manager is the minimal try/finally port: the
    stream is always closed, on success or on error.
    """
    client = _get_client()
    async with client.messages.stream(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=system,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text
