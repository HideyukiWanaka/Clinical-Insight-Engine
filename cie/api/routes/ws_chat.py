"""WS /ws/chat — streaming conversational core (Phase 2).

This route is a thin transport: it authenticates, rate-limits, parses the
client's first message into a :class:`DialogTurn`, and streams whatever frames
the :class:`DialogService` yields. All turn orchestration — running the Planner,
gating clarify/confirm/proceed, streaming the proposal, and dispatching the
visualization/report tools — lives in ``cie/api/dialog.py`` (the Dialog agent),
which chooses *what to do* by explicit + structural gates, never by an LLM.

One socket per turn. The client sends a natural-language ``prompt`` (fresh
turn), a resolved ``intent_object`` (confirm/clarify follow-through), a
``continuation_query`` + prior results/script (a follow-up), or a
``requested_tool`` (an explicit 図/原稿 affordance). See ``dialog.py`` for how
each is routed. R execution stays human-gated (POST /api/run).

Frames the server emits (each a JSON object with ``type``):
  intent     — echo of the understood intent right before streaming (transparency)
  clarify    — Planner needs a choice; carries clarification_options + intent_object
  confirm    — low-confidence intent awaiting the user's OK; carries intent_object
  delta      — a chunk of the proposal explanation as it streams
  proposal   — the terminal structured result (candidates + provenance)
  figures    — generated figure manifest (the visualization tool)
  manuscript — drafted manuscript sections (the reporting tool)
  error      — anything that could not complete (never silent, §5)
  done       — end of this turn

Auth mirrors ``/ws/console`` (§2): the first message carries the session token.
The server owns the running history via ``ConversationStore`` so the Planner
reads a correction in context and the streamed reply reflects the dialogue.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from cie.api.dialog import _VALID_TOOLS, DialogService, DialogTurn

_log = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    """Authenticate, then delegate the chat turn to the Dialog agent, streaming."""
    await websocket.accept()
    services = websocket.app.state.services
    expected = websocket.app.state.session_token

    try:
        first = await websocket.receive_json()
    except (WebSocketDisconnect, ValueError):
        await websocket.close(code=1008)
        return

    provided = str(first.get("token", ""))
    if not provided or not secrets.compare_digest(provided, expected):
        await websocket.send_json(
            {"type": "error", "reason": "unauthorized: invalid session token"}
        )
        await websocket.close(code=1008)  # policy violation
        return

    # Self-limit: this route bypasses RateLimitMiddleware entirely (websocket
    # scope is invisible to BaseHTTPMiddleware), same shape as /ws/console.
    client = websocket.client.host if websocket.client else "unknown"
    retry_after = websocket.app.state.ws_rate_limiter.check(
        client, "/ws/chat", max_requests=40, window_seconds=60
    )
    if retry_after is not None:
        await websocket.send_json(
            {"type": "error",
             "reason": f"rate limited: too many messages, retry in {int(retry_after)}s"}
        )
        await websocket.close(code=1008)
        return

    intent_object = first.get("intent_object")
    has_intent = isinstance(intent_object, dict) and bool(intent_object)
    prompt = str(first.get("prompt") or "")
    # An explicit tool affordance (図/原稿) — the deterministic routing gate. Only
    # a known tool is honoured; anything else is dropped so it can never dispatch
    # somewhere unexpected.
    requested_tool = str(first.get("requested_tool") or "")
    if requested_tool not in _VALID_TOOLS:
        requested_tool = ""

    if not has_intent and not prompt and not requested_tool:
        # Need a prompt to plan from, or a resolved intent / tool to act on. Never
        # silent — surface the reason (§5).
        await websocket.send_json({"type": "error", "reason": "prompt_or_intent_required"})
        await websocket.close()
        return

    conversation_id = str(first.get("conversation_id") or "")
    state = websocket.app.state.conversations.get_or_create(conversation_id)
    dataset_context = getattr(websocket.app.state, "dataset_context", None) or {}

    turn = DialogTurn(
        prompt=prompt,
        intent_object=intent_object if has_intent else None,
        continuation_query=str(first.get("continuation_query") or ""),
        prior_statistical_results=first.get("prior_statistical_results"),
        prior_r_script=first.get("prior_r_script"),
        requested_tool=requested_tool,
    )
    dialog = DialogService(services, dataset_context)

    try:
        async for frame in dialog.run_turn(turn, state):
            await websocket.send_json(frame)
    except Exception as exc:  # noqa: BLE001 — never leak a raw traceback to the socket
        _log.warning("ws_chat routing error: %s", exc)
        await websocket.send_json({"type": "error", "reason": "generation error"})
        await websocket.close(code=1011)
        return

    await websocket.send_json({"type": "done"})
    await websocket.close()
