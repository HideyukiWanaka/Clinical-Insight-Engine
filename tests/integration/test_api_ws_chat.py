"""tests/integration/test_api_ws_chat.py — WS /ws/chat streaming (Phase 2).

Verifies the streaming conversational core:
- first-message token auth (§2), same as /ws/console,
- an intent_object streams the proposal directly (Planner skipped),
- a prompt routes deterministically through the Planner: high confidence →
  intent echo + streamed proposal; low confidence → confirm; ambiguous →
  clarify (never silent, §5),
- the server records the turn in its own ConversationState.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from cie.api.main import create_app  # noqa: E402
from tests.integration.test_api_endpoints import (  # noqa: E402
    TOKEN,
    FakeAgent,
    _make_services,
)

_INTENT = {"objective": "between_group_comparison", "outcome_type": "continuous"}


class _FakeStreamingStatistics:
    """Statistics stub exposing the streaming entry point the WS route calls."""

    agent_id = "statistics"

    def __init__(self) -> None:
        self.last_payload: dict | None = None

    async def stream_conversational_proposal(self, agent_input):
        self.last_payload = agent_input.payload
        yield {"type": "delta", "text": "性別間で血圧を"}
        yield {"type": "delta", "text": "比較します。"}
        yield {
            "type": "proposal",
            "analysis_proposal": {
                "explanation_markdown": "性別間で血圧を比較します。",
                "code_candidates": [
                    {"candidate_id": "c1", "label": "t-test", "r_code": "t.test(BP ~ Sex)"}
                ],
                "recommended_candidate_id": "c1",
                "off_catalog": False,
            },
            "r_script_provenance": {"llm_generated": True, "conversational": True},
            "recommended_r_script": "t.test(BP ~ Sex)",
        }


def _make_client(tmp_path, **overrides) -> TestClient:
    overrides.setdefault("statistics", _FakeStreamingStatistics())
    app = create_app(services=_make_services(tmp_path, **overrides), session_token=TOKEN)
    return TestClient(app)


@pytest.fixture
def client(tmp_path) -> TestClient:
    with _make_client(tmp_path) as c:
        yield c


def _drain(ws) -> list[dict]:
    frames: list[dict] = []
    while True:
        msg = ws.receive_json()
        frames.append(msg)
        if msg["type"] in ("done", "error"):
            break
    return frames


# ── intent_object path (Planner skipped) ────────────────────────────────────


def test_ws_chat_intent_object_streams_proposal_directly(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({
            "token": TOKEN,
            "conversation_id": "conv-1",
            "intent_object": _INTENT,
            "prompt": "男女で血圧を比較したい",
        })
        frames = _drain(ws)

    types = [f["type"] for f in frames]
    assert "intent" not in types  # Planner is skipped when intent is supplied
    assert "delta" in types
    assert types[-1] == "done"
    deltas = "".join(f["text"] for f in frames if f["type"] == "delta")
    assert deltas == "性別間で血圧を比較します。"
    proposal = next(f for f in frames if f["type"] == "proposal")
    assert proposal["analysis_proposal"]["recommended_candidate_id"] == "c1"


def test_ws_chat_records_turn_in_server_side_history(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({
            "token": TOKEN,
            "conversation_id": "conv-2",
            "intent_object": _INTENT,
            "prompt": "男女で血圧を比較したい",
        })
        _drain(ws)

    state = client.app.state.conversations.get_or_create("conv-2")
    roles = [t["role"] for t in state.turns]
    assert roles == ["user", "assistant"]
    assert state.turns[0]["text"] == "男女で血圧を比較したい"
    assert state.turns[1]["text"] == "性別間で血圧を比較します。"


# ── prompt path (deterministic Planner routing) ─────────────────────────────


def test_ws_chat_prompt_high_confidence_echoes_intent_then_streams(
    client: TestClient,
) -> None:
    # The default planner stub returns confidence 0.9 (unambiguous).
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({
            "token": TOKEN,
            "conversation_id": "conv-3",
            "prompt": "男女で血圧を比較したい",
        })
        frames = _drain(ws)

    types = [f["type"] for f in frames]
    assert types[0] == "intent"  # transparent hand-off echo (never silent)
    assert "delta" in types
    assert any(f["type"] == "proposal" for f in frames)
    assert types[-1] == "done"


def test_ws_chat_prompt_low_confidence_asks_confirm(tmp_path) -> None:
    planner = FakeAgent("planner", {
        "intent_object": {"objective": "between_group_comparison"},
        "confidence_score": 0.4,
        "requires_human_clarification": False,
        "clarification_options": [],
    })
    with _make_client(tmp_path, planner=planner) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"token": TOKEN, "conversation_id": "c", "prompt": "何か比較して"})
            frames = _drain(ws)

    types = [f["type"] for f in frames]
    assert "confirm" in types
    assert "proposal" not in types  # low confidence never auto-proposes
    confirm = next(f for f in frames if f["type"] == "confirm")
    assert confirm["intent_object"]["objective"] == "between_group_comparison"


def test_ws_chat_prompt_ambiguous_asks_clarify(tmp_path) -> None:
    planner = FakeAgent("planner", {
        "intent_object": {"objective": "between_group_comparison"},
        "confidence_score": 0.5,
        "requires_human_clarification": True,
        "clarification_options": [
            {"option_id": "o1", "label": "収縮期血圧", "intent_override": {"paired": False}},
        ],
    })
    with _make_client(tmp_path, planner=planner) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"token": TOKEN, "conversation_id": "c", "prompt": "血圧を見たい"})
            frames = _drain(ws)

    clarify = next(f for f in frames if f["type"] == "clarify")
    assert clarify["clarification_options"][0]["label"] == "収縮期血圧"
    assert "proposal" not in [f["type"] for f in frames]


# ── continuation (follow-up) path ───────────────────────────────────────────


def test_ws_chat_continuation_streams_and_forwards_prior_context(tmp_path) -> None:
    stats = _FakeStreamingStatistics()
    with _make_client(tmp_path, statistics=stats) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({
                "token": TOKEN,
                "conversation_id": "cont-1",
                # Lineage intent + follow-up query + prior context (Planner skipped).
                "intent_object": _INTENT,
                "continuation_query": "効果量の信頼区間も出したい",
                "prior_statistical_results": {"test_name": "Welch t-test"},
                "prior_r_script": "t.test(BP ~ Sex)",
            })
            frames = _drain(ws)

    types = [f["type"] for f in frames]
    assert "intent" not in types  # Planner skipped on a continuation turn
    assert "delta" in types and "proposal" in types
    assert types[-1] == "done"

    # The follow-up context was forwarded to the streaming StatisticsAgent.
    assert stats.last_payload["continuation_query"] == "効果量の信頼区間も出したい"
    assert stats.last_payload["prior_statistical_results"] == {"test_name": "Welch t-test"}
    assert stats.last_payload["prior_r_script"] == "t.test(BP ~ Sex)"

    # The user turn recorded is the follow-up query (not empty), then the reply.
    state = client.app.state.conversations.get_or_create("cont-1")
    roles = [t["role"] for t in state.turns]
    assert roles == ["user", "assistant"]
    assert state.turns[0]["text"] == "効果量の信頼区間も出したい"


# ── guards ──────────────────────────────────────────────────────────────────


def test_ws_chat_rejects_bad_token(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"token": "wrong", "intent_object": _INTENT})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "unauthorized" in msg["reason"]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_ws_chat_requires_prompt_or_intent(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"token": TOKEN, "conversation_id": "c"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["reason"] == "prompt_or_intent_required"
