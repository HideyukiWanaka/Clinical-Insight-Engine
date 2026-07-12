"""tests/integration/test_api_ws_chat.py — WS /ws/chat streaming (Phase 2).

Verifies the streaming conversational-proposal socket:
- first-message token auth (§2), same as /ws/console,
- delta frames stream the explanation, then one proposal frame, then done,
- a missing intent_object is rejected explicitly (never silent, §5),
- the server records the turn in its own ConversationState (server owns history).
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
    _make_services,
)

_INTENT = {"objective": "between_group_comparison", "outcome_type": "continuous"}


class _FakeStreamingStatistics:
    """Statistics stub exposing the streaming entry point the WS route calls."""

    agent_id = "statistics"

    async def stream_conversational_proposal(self, agent_input):
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


@pytest.fixture
def client(tmp_path) -> TestClient:
    services = _make_services(tmp_path, statistics=_FakeStreamingStatistics())
    app = create_app(services=services, session_token=TOKEN)
    with TestClient(app) as c:
        yield c


def _drain(ws) -> list[dict]:
    frames: list[dict] = []
    while True:
        msg = ws.receive_json()
        frames.append(msg)
        if msg["type"] in ("done", "error"):
            break
    return frames


def test_ws_chat_streams_deltas_then_proposal_then_done(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({
            "token": TOKEN,
            "conversation_id": "conv-1",
            "intent_object": _INTENT,
            "prompt": "男女で血圧を比較したい",
        })
        frames = _drain(ws)

    types = [f["type"] for f in frames]
    assert "delta" in types
    assert types[-1] == "done"
    deltas = "".join(f["text"] for f in frames if f["type"] == "delta")
    assert deltas == "性別間で血圧を比較します。"
    proposal = next(f for f in frames if f["type"] == "proposal")
    assert proposal["analysis_proposal"]["recommended_candidate_id"] == "c1"
    assert proposal["r_script_provenance"]["llm_generated"] is True


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


def test_ws_chat_rejects_bad_token(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"token": "wrong", "intent_object": _INTENT})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "unauthorized" in msg["reason"]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_ws_chat_requires_intent_object(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"token": TOKEN, "prompt": "何かして"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["reason"] == "intent_object_required"
