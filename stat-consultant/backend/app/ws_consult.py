"""WS /ws/consult — structured chat core (Step 2).

Step 1 streamed plain-text deltas. Step 2 emits SPEC 4.4 message types: each
user turn yields an ordered stream of ``assistant_text`` (一言理由 + 折りたたみ
用の詳細) and ``assistant_code`` (Rコード本体) frames — one response may carry
several ``assistant_code`` blocks, and every code block carries a one-line
reason. The server still owns the running history so later turns keep context.

Out of scope here: frontend rendering (Step 3), environment/references/images/
RStudio wiring (later steps). Localhost personal app, so no auth/rate-limit yet.

Frames the client sends (one JSON object, or bare text, per message):
  {"text": "...", "conversation_id": "..."}   — a user turn

Frames the server emits (each a JSON object with ``type``):
  assistant_text — {reason: 一言, detail: 折りたたみ用の詳細}
  assistant_code — {reason: 一言の理由・前提, language, code}
  done           — end of this turn
  error          — anything that could not complete (never silent)
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .llm import blocks_to_text, generate_blocks
from .prompts import SYSTEM_PROMPT
from .references import build_reference_context, extract_query_terms

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


def _frame_for(block: dict) -> dict | None:
    """Map a model block to a SPEC 4.4 outgoing frame (or None to skip)."""
    if block.get("type") == "text":
        return {
            "type": "assistant_text",
            "reason": str(block.get("reason", "")),
            "detail": str(block.get("detail", "")),
        }
    if block.get("type") == "code":
        return {
            "type": "assistant_code",
            "reason": str(block.get("reason", "")),
            "language": str(block.get("language") or "r"),
            "code": str(block.get("code", "")),
        }
    return None


@router.websocket("/ws/consult")
async def ws_consult(websocket: WebSocket) -> None:
    """Accept a socket, then stream structured reply frames per user turn."""
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

            # Ground on the user's uploaded references: retrieve the top hits for
            # the latest message and fold their excerpts into the system prompt.
            library = websocket.app.state.references
            refs = library.retrieve(extract_query_terms(text), top_k=2)
            system = SYSTEM_PROMPT + build_reference_context(refs)

            try:
                blocks = await generate_blocks(system, state.history())
            except Exception as exc:  # noqa: BLE001 — never leak a raw traceback
                _log.warning("ws_consult generation error: %s", exc)
                await websocket.send_json(
                    {"type": "error", "reason": "generation error"}
                )
                continue

            for block in blocks:
                frame = _frame_for(block)
                if frame is not None:
                    await websocket.send_json(frame)

            state.add_turn("assistant", blocks_to_text(blocks))
            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        return
