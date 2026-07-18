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

from .environment import build_environment_context
from .llm import blocks_to_text, generate_blocks
from .models_registry import is_available, resolve_model
from .prompts import IMAGE_INSTRUCTION, SYSTEM_PROMPT
from .references import build_reference_context, extract_query_terms

_log = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])


# A reference figure is small (papers' figures downscale well); cap the decoded
# data URL so a pathological upload can't blow up the prompt / provider request.
_MAX_IMAGE_B64_CHARS = 8_000_000  # ~6 MB decoded — ample for a figure screenshot
_ALLOWED_IMAGE_MEDIA = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp"}
)


def _parse_image(parsed: dict) -> dict | None:
    """Extract a this-turn reference figure ``{media_type, data}`` if present.

    The figure is ephemeral (SPEC §9 / Step 9: 「その場限りの参考図」) — sent only
    for this turn, never persisted. Malformed or oversized images are dropped
    (returned as ``None``) rather than raised, so a bad attachment degrades to a
    text-only turn instead of failing the whole message.
    """
    img = parsed.get("image")
    if not isinstance(img, dict):
        return None
    media_type = str(img.get("media_type") or "")
    data = str(img.get("data") or "")
    if media_type not in _ALLOWED_IMAGE_MEDIA or not data:
        return None
    if len(data) > _MAX_IMAGE_B64_CHARS:
        return None
    return {"media_type": media_type, "data": data}


def _parse_frame(raw: str) -> tuple[str, str, str, dict | None]:
    """Return ``(text, conversation_id, model, image)`` from a client message.

    Accepts a JSON object ``{"text", "conversation_id", "model", "image"}`` or a
    bare string (treated as the text). Unknown shapes yield empty text, which the
    caller surfaces as an error rather than acting on.
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw.strip(), "", "", None
    if isinstance(parsed, str):
        return parsed.strip(), "", "", None
    if isinstance(parsed, dict):
        return (
            str(parsed.get("text") or "").strip(),
            str(parsed.get("conversation_id") or ""),
            str(parsed.get("model") or ""),
            _parse_image(parsed),
        )
    return "", "", "", None


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
            text, conversation_id, model, image = _parse_frame(raw)
            # A reference figure may arrive with no typed text — synthesise a
            # default ask so the turn is meaningful and the history stays useful.
            if not text and image is not None:
                text = "添付した図を参考に、私のデータで同様の図を描くRコードを提案してください。"
            if not text:
                await websocket.send_json(
                    {"type": "error", "reason": "empty message: expected text"}
                )
                continue

            # Resolve the chosen model; require its provider key to be configured.
            spec = resolve_model(model)
            if not is_available(spec):
                await websocket.send_json(
                    {
                        "type": "error",
                        "reason": f"モデル {spec.label} は未設定です"
                        f"（サーバーに {spec.provider} のAPIキーがありません）",
                    }
                )
                continue

            resolved_conversation_id = conversation_id or default_conversation_id
            state = store.get_or_create(resolved_conversation_id)
            state.add_turn("user", text)
            store.persist(resolved_conversation_id)

            # Ground the reply on (1) the user's uploaded references and (2) the
            # latest RStudio environment snapshot (Step 8), folded into the
            # system prompt. When a reference figure is attached (Step 9), add
            # the vision-to-ggplot2 instruction too.
            library = websocket.app.state.references
            refs = library.retrieve(extract_query_terms(text), top_k=2)
            system = (
                SYSTEM_PROMPT
                + build_reference_context(refs)
                + build_environment_context(websocket.app.state.environment.latest)
            )
            if image is not None:
                system += IMAGE_INSTRUCTION

            try:
                blocks = await generate_blocks(spec, system, state.history(), image)
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
            store.persist(resolved_conversation_id)
            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        return
