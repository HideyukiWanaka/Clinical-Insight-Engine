"""Claude call that returns SPEC 4.4 structured blocks (Step 2).

Step 1 streamed plain text. Step 2 constrains the reply to a small JSON schema —
an ordered list of ``text`` / ``code`` blocks — so the WebSocket can emit
``assistant_text`` / ``assistant_code`` frames with a reason always attached to
every code block (BUILD_PROMPTS Step 2 / SPEC 4.4).

Structure is enforced by ``output_config.format`` (json_schema), not by parsing
prose, so the frames are reliable. We still call through ``messages.stream(...)``
for HTTP-timeout safety on large replies, then take the final message. The
``async with`` remains the minimal try/finally lifecycle port (SPEC §10): the
stream is always torn down on every exit path.

Auth is zero-config: ``AsyncAnthropic()`` resolves ``ANTHROPIC_API_KEY`` (or an
``ant auth login`` profile) from the environment — nothing is hardcoded.
"""

from __future__ import annotations

import json

from anthropic import AsyncAnthropic

# Opus 4.8 — current, most capable, Vision-capable; the right default for
# statistical advice where correctness matters (SPEC §6, 痛み②手法選択).
_MODEL = "claude-opus-4-8"
# Structured reply may carry several code blocks + reasons (+ adaptive thinking);
# streaming makes a generous ceiling safe (no HTTP-timeout risk).
_MAX_TOKENS = 16000

# SPEC 4.4 message types as an ordered list of blocks. ``reason`` is required on
# every block, which is what guarantees 「理由が常に付与されている」 for code.
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "const": "text"},
                            "reason": {"type": "string"},
                            "detail": {"type": "string"},
                        },
                        "required": ["type", "reason", "detail"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "const": "code"},
                            "reason": {"type": "string"},
                            "language": {"type": "string"},
                            "code": {"type": "string"},
                        },
                        "required": ["type", "reason", "language", "code"],
                        "additionalProperties": False,
                    },
                ]
            },
        }
    },
    "required": ["blocks"],
    "additionalProperties": False,
}

# One process-wide async client, constructed lazily so importing this module
# never requires credentials to be present (e.g. at test-collection time).
_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic()
    return _client


async def generate_blocks(system: str, messages: list[dict]) -> list[dict]:
    """Return the reply as an ordered list of SPEC 4.4 blocks.

    Each element is either ``{"type": "text", "reason", "detail"}`` or
    ``{"type": "code", "reason", "language", "code"}``. ``thinking`` is adaptive
    so the model reasons deeply on a real methods question and not at all on
    chitchat.

    Args:
        system:   The persona/system prompt.
        messages: Ordered turns ``[{"role", "content"}, ...]`` (oldest→newest).

    Raises:
        Anything the SDK raises; the caller turns it into an error frame.
    """
    client = _get_client()
    async with client.messages.stream(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=system,
        messages=messages,
        output_config={
            "format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA}
        },
    ) as stream:
        message = await stream.get_final_message()

    # With output_config.format the first text block is guaranteed valid JSON
    # matching the schema; thinking blocks (if any) precede it and are skipped.
    text = next((b.text for b in message.content if b.type == "text"), "")
    data = json.loads(text)
    blocks = data.get("blocks", [])
    return [b for b in blocks if isinstance(b, dict) and b.get("type") in ("text", "code")]


def blocks_to_text(blocks: list[dict]) -> str:
    """Render blocks to a plain-text assistant turn for the running history.

    History is stored as text so the next turn threads context; the exact
    structured shape is a rendering concern for the client, not the model.
    """
    parts: list[str] = []
    for b in blocks:
        if b.get("type") == "text":
            parts.append(b.get("reason", ""))
            detail = b.get("detail", "")
            if detail:
                parts.append(detail)
        elif b.get("type") == "code":
            lang = b.get("language", "r")
            parts.append(
                f"{b.get('reason', '')}\n```{lang}\n{b.get('code', '')}\n```"
            )
    return "\n\n".join(p for p in parts if p)
