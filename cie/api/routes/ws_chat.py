"""WS /ws/chat — streaming conversational core (Phase 2).

One socket per turn drives the whole first-turn flow server-side: the client
sends a natural-language ``prompt`` and the server deterministically routes it —
run the Planner, then either ask for clarification, ask for confirmation, or (on
a high-confidence unambiguous intent) stream the code proposal. When the client
instead sends a resolved ``intent_object`` (after clicking a confirm/clarify
option), the Planner is skipped and the proposal streams directly. A follow-up
turn adds a ``continuation_query`` (plus the prior results/script) alongside the
lineage ``intent_object``: the Planner is skipped and the streamed proposal
extends the prior analysis.

Deterministic routing (safety): an LLM never decides *what to do* here. The
Planner and Statistics agents run over their existing governed paths (issue
token → schema-validated AgentInput → agent enforces scope/schema/audit →
revoke); this route only chooses between them by the Planner's own
confidence/clarification signals. R execution stays human-gated (POST /api/run).

Frames the server emits (each a JSON object with ``type``):
  intent   — echo of the understood intent right before streaming (transparency)
  clarify  — Planner needs a choice; carries clarification_options + intent_object
  confirm  — low-confidence intent awaiting the user's OK; carries intent_object
  delta    — a chunk of the proposal explanation as it streams
  proposal — the terminal structured result (candidates + provenance)
  error    — anything that could not complete (never silent, §5)
  done     — end of this turn

Auth mirrors ``/ws/console`` (§2): the first message carries the session token.
The server owns the running history via ``ConversationStore`` so the Planner
reads a correction in context and the streamed reply reflects the dialogue.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from cie.agents.base import AgentInput
from cie.api.conversation import ConversationState
from cie.api.deps import invoke_agent, new_execution_id
from cie.api.intent_display import resolve_intent_display
from cie.security.capability_token import CapabilityScope

_log = logging.getLogger(__name__)

router = APIRouter(tags=["ws"])

# Confidence at/above which an unambiguous intent skips the confirm gate and
# streams the proposal directly (matches ChatPane's HIGH_CONFIDENCE / CA-002).
_HIGH_CONFIDENCE = 0.7

# Same permissive dispatch schema /api/propose validates the conversational
# Statistics payload against (the strict analysis-request schema is the Planner
# *output* shape, not this *input* shape — see cie/api/routes/propose.py).
_STATS_INPUT_SCHEMA_REF = "cie://schemas/task-context.schema.json"


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    """Authenticate, then route a chat turn (Planner → proposal) with streaming."""
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

    # Follow-up (continuation) turn: a natural-language request that extends the
    # PRIOR analysis. It rides alongside intent_object (the lineage intent) and
    # carries the prior results/script as context — the Planner is skipped and
    # the proposal streams as a follow-up (see _stream_proposal).
    continuation_query = str(first.get("continuation_query") or "")
    continuation: dict | None = None
    if continuation_query:
        continuation = {
            "continuation_query": continuation_query,
            "prior_statistical_results": first.get("prior_statistical_results"),
            "prior_r_script": first.get("prior_r_script"),
        }

    if not has_intent and not prompt:
        # Need a prompt to plan from, or a resolved intent to propose for. Never
        # silent — surface the reason (§5).
        await websocket.send_json({"type": "error", "reason": "prompt_or_intent_required"})
        await websocket.close()
        return

    conversation_id = str(first.get("conversation_id") or "")
    state = websocket.app.state.conversations.get_or_create(conversation_id)
    dataset_context = getattr(websocket.app.state, "dataset_context", None) or {}

    try:
        if has_intent:
            # Confirm/clarify follow-through OR a continuation turn: the client
            # already has the intent, so skip the Planner and stream directly.
            # For a continuation the user-visible text is the follow-up query.
            user_text = continuation_query or prompt
            if user_text:
                state.add_turn("user", user_text)
            await _stream_proposal(
                websocket, services, state, intent_object, dataset_context,
                continuation=continuation,
            )
        else:
            # Fresh natural-language turn: run the Planner first, then route.
            proceed = await _route_via_planner(
                websocket, services, state, prompt, dataset_context
            )
            if proceed is not None:
                await _stream_proposal(
                    websocket, services, state, proceed, dataset_context
                )
    except Exception as exc:  # noqa: BLE001 — never leak a raw traceback to the socket
        _log.warning("ws_chat routing error: %s", exc)
        await websocket.send_json({"type": "error", "reason": "generation error"})
        await websocket.close(code=1011)
        return

    await websocket.send_json({"type": "done"})
    await websocket.close()


async def _route_via_planner(
    websocket: WebSocket,
    services: dict,
    state: ConversationState,
    prompt: str,
    dataset_context: dict,
) -> dict | None:
    """Run the Planner and emit the routing frame.

    Returns the resolved ``intent_object`` when the turn should proceed to
    streaming a proposal (high confidence, unambiguous); returns ``None`` when
    the turn is terminal here (clarify / confirm / planner failure).
    """
    # History EXCLUDES the current prompt (it rides separately, matching
    # /api/intent), so read it before recording this turn.
    history = state.history()
    col_meta = dataset_context.get("dataset_structural_metadata", {})
    alias_map = dataset_context.get("var_n_alias_map", {})
    masked_vars = set(dataset_context.get("pii_masked_vars", []))

    output = await invoke_agent(
        services,
        agent_key="planner",
        agent_id="planner",
        step_id="ws_chat_intent",
        scopes=[
            CapabilityScope.DATASET_PROXY_METADATA,
            CapabilityScope.WORKFLOW_STATE_READ,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ],
        payload={
            "user_natural_language_prompt": prompt,
            "dataset_structural_metadata": col_meta,
            "conversation_history": history,
            "inject_raw_data_rows": False,
        },
        input_schema_ref="cie://schemas/planner-input.schema.json",
        execution_id=new_execution_id(),
    )

    # Record the turn now that the Planner has read the prior history.
    state.add_turn("user", prompt)

    if output.status not in ("success", "clarification_required"):
        await websocket.send_json(
            {"type": "error",
             "reason": output.error_message or "planner_failed"}
        )
        return None

    op = output.output_payload
    intent_object = op.get("intent_object", {}) or {}
    clarification_options = op.get("clarification_options") or []
    confidence = float(op.get("confidence_score") or 0.0)
    requires_clarification = bool(op.get("requires_human_clarification", False))

    # Un-mask var_n aliases in user-facing prose so the chat never shows raw
    # internal identifiers like "var_4" (Fix C) — same helper as /api/intent.
    resolve_intent_display(
        intent_object, clarification_options, alias_map, masked_vars
    )
    summary = intent_object.get("natural_language_summary") or ""

    if requires_clarification:
        state.add_turn("assistant", summary or "確認のため選択肢を提示しました。")
        await websocket.send_json(
            {"type": "clarify",
             "intent_object": intent_object,
             "clarification_options": clarification_options}
        )
        return None

    if confidence < _HIGH_CONFIDENCE:
        state.add_turn("assistant", summary or "意図を確認しました。")
        await websocket.send_json(
            {"type": "confirm", "intent_object": intent_object}
        )
        return None

    # High confidence & unambiguous — echo the understood intent (transparency,
    # never a silent hand-off) and proceed to stream the proposal.
    await websocket.send_json(
        {"type": "intent",
         "intent_object": intent_object,
         "confidence_score": confidence}
    )
    return intent_object


async def _stream_proposal(
    websocket: WebSocket,
    services: dict,
    state: ConversationState,
    intent_object: dict,
    dataset_context: dict,
    continuation: dict | None = None,
) -> None:
    """Stream a conversational proposal for ``intent_object`` over the socket.

    Runs the governed StatisticsAgent streaming entry point (token issued here,
    always revoked in finally — same lifecycle as cie/api/deps.invoke_agent) and
    forwards its delta/proposal/error events, recording the assistant reply so
    the next turn's streamed explanation reflects it.

    When ``continuation`` is given (a follow-up turn), its query + prior
    results/script ride in the payload so the streamed proposal extends the
    prior analysis rather than starting fresh (StatisticsAgent detects it via
    ``continuation_query`` — same fields as REST /api/propose).
    """
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
    if continuation:
        payload["continuation_query"] = continuation["continuation_query"]
        payload["prior_statistical_results"] = continuation.get(
            "prior_statistical_results"
        )
        payload["prior_r_script"] = continuation.get("prior_r_script")

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
        input_schema_ref=_STATS_INPUT_SCHEMA_REF,
    )

    try:
        async for event in agent.stream_conversational_proposal(agent_input):
            if event.get("type") == "proposal":
                proposal = event.get("analysis_proposal") or {}
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
    finally:
        # ADR: the capability token is always revoked (try/finally).
        token_manager.revoke(token)
