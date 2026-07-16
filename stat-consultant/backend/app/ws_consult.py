"""WS /ws/consult — minimal streaming chat core (Step 1).

Skeleton translated from ``cie/api/routes/ws_chat.py``: one socket carries
several turns; the server owns the running history via ``ConversationStore`` so
the second turn sees the first in context, and the reply streams back token by
token.

Step 1 scope: plain conversational text only. No code/reason structuring
(Step 2), no environment context / references / images / RStudio wiring (later
steps), and — being a localhost personal app — no auth or rate limiting yet.

Frames the client sends (one JSON object, or bare text, per message):
  {"text": "...", "conversation_id": "..."}   — a user turn
  (a bare non-JSON string is also accepted as the text, for easy websocat use)

Frames the server emits (each a JSON object with ``type``):
  delta — a chunk of the assistant reply as it streams
  done  — end of this turn
  error — anything that could not complete (never silent)
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .llm import stream_reply
from .prompts import SYSTEM_PROMPT

_log = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])


def _parse_frame(raw: str) -> tuple[str, str]:
    """Return ``(text, conversation_id)`` from a client message.

    Accepts a JSON object ``{"text", "conversation_id"}`` or a bare string
    (treated as the text). Unknown shapes yield empty text, which the caller
    surfaces as an error rather than acting on.
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw.strip(), ""
    if isinstance(parsed, str):
        return parsed.strip(), ""
    if isinstance(parsed, dict):
        return str(parsed.get("text") or "").strip(), str(
            parsed.get("conversation_id") or ""
        )
    return "", ""


@router.websocket("/ws/consult")
async def ws_consult(websocket: WebSocket) -> None:
    """Accept a socket, then stream a chat reply per user turn, keeping context."""
    await websocket.accept()
    store = websocket.app.state.conversations
    # One conversation per socket by default; a client may override per frame.
    default_conversation_id = uuid.uuid4().hex

    try:
        while True:
            raw = await websocket.receive_text()
            text, conversation_id = _parse_frame(raw)
            if not text:
                await websocket.send_json(
                    {"type": "error", "reason": "empty message: expected text"}
                )
                continue

            state = store.get_or_create(conversation_id or default_conversation_id)
            state.add_turn("user", text)

            reply_parts: list[str] = []
            try:
                async for chunk in stream_reply(SYSTEM_PROMPT, state.history()):
                    reply_parts.append(chunk)
                    await websocket.send_json({"type": "delta", "text": chunk})
            except Exception as exc:  # noqa: BLE001 — never leak a raw traceback
                _log.warning("ws_consult generation error: %s", exc)
                await websocket.send_json(
                    {"type": "error", "reason": "generation error"}
                )
                continue

            state.add_turn("assistant", "".join(reply_parts))
            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        return
