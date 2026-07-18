"""Multi-provider LLM call that returns SPEC 4.4 structured blocks.

Supports Anthropic, OpenAI, and Gemini (the last via OpenAI's compatible
endpoint, reusing the ``openai`` SDK). The reply is constrained to a small
JSON schema — an ordered list of ``text`` / ``code`` blocks — so the WebSocket
can emit ``assistant_text`` / ``assistant_code`` frames with a reason always
attached to every code block (BUILD_PROMPTS Step 2 / SPEC 4.4).

Structure comes from each provider's native JSON output (Anthropic
``output_config.format``; OpenAI ``response_format`` json_schema; Gemini
``response_format`` json_object) plus a robust JSON parse that tolerates fences
or stray prose as a fallback.

Auth is zero-config per provider: keys are read from the environment by each
SDK (``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` / ``GEMINI_API_KEY``) — nothing
is hardcoded. The ``async with`` on the Anthropic stream remains the minimal
try/finally lifecycle port (SPEC §10).
"""

from __future__ import annotations

import json
import re

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from . import secrets_store
from .models_registry import GEMINI_BASE_URL, ModelSpec

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

def _new_openai_client(spec: ModelSpec) -> AsyncOpenAI:
    """A fresh OpenAI-SDK client for OpenAI (default) or Gemini (compat base_url).

    Built per request from the current stored key so a key change in the
    settings screen takes effect on the very next turn (no cache to bust).
    """
    key = secrets_store.load_api_key(spec.provider) or ""
    if spec.provider == "gemini":
        return AsyncOpenAI(api_key=key, base_url=GEMINI_BASE_URL)
    return AsyncOpenAI(api_key=key)


def openai_messages(system: str, messages: list[dict]) -> list[dict]:
    """Prepend the system prompt as a system message (OpenAI/Gemini shape)."""
    return [{"role": "system", "content": system}, *messages]


def _attach_image_last_user(
    messages: list[dict], image: dict | None, *, provider: str
) -> list[dict]:
    """Return ``messages`` with *image* attached to the last user turn (Step 9).

    The reference figure is ephemeral — it belongs to this one call only, so it
    is injected into the request messages here rather than stored in history.
    Anthropic and the OpenAI-compatible providers expect different multimodal
    content shapes, selected by ``provider``.
    """
    if not image or not messages or messages[-1].get("role") != "user":
        return messages
    out = [dict(m) for m in messages]
    text = str(out[-1].get("content", ""))
    if provider == "anthropic":
        out[-1]["content"] = [
            {"type": "text", "text": text},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image["media_type"],
                    "data": image["data"],
                },
            },
        ]
    else:  # openai / gemini (OpenAI-compatible content parts)
        data_url = f"data:{image['media_type']};base64,{image['data']}"
        out[-1]["content"] = [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
    return out


def openai_response_format(spec: ModelSpec) -> dict:
    """Native structured-output config for the OpenAI-compatible providers.

    OpenAI supports strict ``json_schema``; Gemini's compat endpoint is more
    reliable with plain ``json_object`` (the schema is described in the prompt,
    and the parser is tolerant), so use that there.
    """
    if spec.provider == "gemini":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {"name": "stat_reply", "strict": True, "schema": _RESPONSE_SCHEMA},
    }


def parse_blocks(text: str) -> list[dict]:
    """Parse the model's JSON reply into blocks, tolerating fences/stray prose."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[A-Za-z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped).strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    blocks = data.get("blocks", []) if isinstance(data, dict) else []
    return [b for b in blocks if isinstance(b, dict) and b.get("type") in ("text", "code")]


async def _anthropic_json(
    model: str, system: str, messages: list[dict], image: dict | None
) -> str:
    # Fresh client from the current stored key (settings-screen changes apply
    # on the next turn); the async-with pair is the try/finally lifecycle port.
    async with AsyncAnthropic(
        api_key=secrets_store.load_api_key("anthropic") or ""
    ) as client:
        async with client.messages.stream(
            model=model,
            max_tokens=_MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=system,
            messages=_attach_image_last_user(messages, image, provider="anthropic"),
            output_config={"format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA}},
        ) as stream:
            message = await stream.get_final_message()
    return next((b.text for b in message.content if b.type == "text"), "")


async def _openai_compat_json(
    spec: ModelSpec, system: str, messages: list[dict], image: dict | None
) -> str:
    with_image = _attach_image_last_user(messages, image, provider=spec.provider)
    async with _new_openai_client(spec) as client:
        resp = await client.chat.completions.create(
            model=spec.model,
            messages=openai_messages(system, with_image),
            response_format=openai_response_format(spec),
        )
    return resp.choices[0].message.content or ""


async def generate_blocks(
    spec: ModelSpec, system: str, messages: list[dict], image: dict | None = None
) -> list[dict]:
    """Return the reply as an ordered list of SPEC 4.4 blocks, via ``spec``'s provider.

    Args:
        spec:     The chosen model (provider + provider model id).
        system:   The persona/system prompt (+ any retrieved reference/环境 context).
        messages: Ordered turns ``[{"role", "content"}, ...]`` (oldest→newest).
        image:    Optional ``{media_type, data}`` reference figure for this turn
                  only (Step 9); attached to the last user message, not stored.

    Raises:
        Anything the SDK raises; the caller turns it into an error frame.
    """
    if spec.provider == "anthropic":
        text = await _anthropic_json(spec.model, system, messages, image)
    else:
        text = await _openai_compat_json(spec, system, messages, image)
    return parse_blocks(text)


def blocks_to_text(blocks: list[dict]) -> str:
    """Render blocks to a plain-text assistant turn for the running history."""
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
