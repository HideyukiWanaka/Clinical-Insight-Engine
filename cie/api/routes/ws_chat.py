"""WS /ws/chat — streaming conversational proposal (Phase 2).

The REST ``/api/propose`` returns the whole ``analysis_proposal`` in one shot;
this socket instead streams the natural-language explanation token by token
(``delta`` frames) and then delivers the structured code candidates in a final
``proposal`` frame — the chat-AI "typing" experience the workbench chat wants.

Deterministic routing (safety): this endpoint does NOT let an LLM decide what to
do. It runs the SAME governed StatisticsAgent path ``/api/propose`` uses (issue
token → schema-validated AgentInput → agent enforces scope/schema/audit →
revoke), only over a streaming entry point. The Planner still runs over REST
``/api/intent`` first, so the intent hand-off is unchanged; the client passes the
resolved ``intent_object`` here. R execution stays human-gated (POST /api/run).

Auth mirrors ``/ws/console`` (§2): the first message carries the session token,
not the HTTP ``X-CIE-Token`` middleware (which never sees websocket-scope
connections). The server owns the conversation history via ``ConversationStore``
so the streamed explanation reflects the whole dialogue.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from cie.agents.base import AgentInput
from cie.api.deps import new_execution_id
from cie.security.capability_token import CapabilityScope

_log = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])

# Same permissive dispatch schema /api/propose validates the conversational
# Statistics payload against (the strict analysis-request schema is the Planner
# *output* shape, not this *input* shape — see cie/api/routes/propose.py).
_INPUT_SCHEMA_REF = "cie://schemas/task-context.schema.json"


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    """Authenticate, then stream a conversational proposal for an intent."""
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
    if not isinstance(intent_object, dict) or not intent_object:
        # This increment streams the *propose* step; the caller resolves intent
        # over REST /api/intent first (Planner) and passes it here. Never silent.
        await websocket.send_json(
            {"type": "error", "reason": "intent_object_required"}
        )
        await websocket.close()
        return

    conversation_id = str(first.get("conversation_id") or "")
    prompt = str(first.get("prompt") or "")

    store = websocket.app.state.conversations
    state = store.get_or_create(conversation_id)
    if prompt:
        state.add_turn("user", prompt)

    dataset_context = getattr(websocket.app.state, "dataset_context", None) or {}
    payload: dict = {
        "data_quality_report": {"quality_gate_passed": True},
        "intent_object": intent_object,
        "dataset_structural_metadata": dataset_context.get(
            "dataset_structural_metadata", {}
        ),
        "var_n_alias_map": dataset_context.get("var_n_alias_map", {}),
        "conversation_history": state.history(),
        "conversational_mode": True,
        "inject_raw_data_rows": False,
    }

    execution_id = new_execution_id()
    token_manager = services["token_manager"]
    agent = services["statistics"]
    token = token_manager.issue(
        execution_id=execution_id,
        agent_id="statistics",
        step_id="ws_chat",
        requested_scopes={
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.R_CODE_GENERATE_TEMPLATE,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
    )
    agent_input = AgentInput(
        execution_id=execution_id,
        node_id="ws_chat",
        capability_token=token,
        payload=payload,
        input_schema_ref=_INPUT_SCHEMA_REF,
    )

    try:
        async for event in agent.stream_conversational_proposal(agent_input):
            if event.get("type") == "proposal":
                proposal = event.get("analysis_proposal") or {}
                # Record the assistant reply so the next turn's streamed
                # explanation reflects it (server owns the history).
                state.add_turn("assistant", proposal.get("explanation_markdown", ""))
                await websocket.send_json(
                    {
                        "type": "proposal",
                        "execution_id": execution_id,
                        "analysis_proposal": proposal,
                        "r_script_provenance": event.get("r_script_provenance") or {},
                    }
                )
            else:
                await websocket.send_json(event)
    except Exception as exc:  # noqa: BLE001 — never leak a raw traceback to the socket
        _log.warning("ws_chat streaming error: %s", exc)
        await websocket.send_json(
            {"type": "error", "reason": "generation error"}
        )
        await websocket.close(code=1011)
        return
    finally:
        # ADR: the capability token is always revoked (try/finally), exactly as
        # cie/api/deps.invoke_agent does for the REST handlers.
        token_manager.revoke(token)

    await websocket.send_json({"type": "done"})
    await websocket.close()
