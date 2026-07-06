"""tests/integration/test_api_ws_console.py — Phase 1 WebSocket console tests.

Verifies ``/ws/console`` (rest-api-contract §4.1, RT-004):
- first-message token auth (§2),
- sanitized stdout streaming (raw output is never emitted),
- the stream ends with an ``exit`` frame carrying the exit code.
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


@pytest.fixture
def client(tmp_path) -> TestClient:
    app = create_app(services=_make_services(tmp_path), session_token=TOKEN)
    with TestClient(app) as c:
        yield c


def test_ws_streams_sanitized_stdout_then_exit(client: TestClient) -> None:
    with client.websocket_connect("/ws/console") as ws:
        ws.send_json({"token": TOKEN, "r_script": "print(1+1)"})
        frames = []
        while True:
            msg = ws.receive_json()
            frames.append(msg)
            if msg["type"] == "exit":
                break

    stdout_text = "\n".join(f["text"] for f in frames if f["type"] == "stdout")
    # RT-004: the marker in the fake stdout must have been sanitized.
    assert "SECRET" not in stdout_text
    assert "[REDACTED]" in stdout_text
    assert frames[-1]["type"] == "exit"
    assert frames[-1]["exit_code"] == 0


def test_ws_rejects_bad_token(client: TestClient) -> None:
    with client.websocket_connect("/ws/console") as ws:
        ws.send_json({"token": "wrong", "r_script": "print(1+1)"})
        msg = ws.receive_json()
        assert msg["type"] == "stderr"
        assert "unauthorized" in msg["text"]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_ws_subscribe_without_script_closes_cleanly(client: TestClient) -> None:
    with client.websocket_connect("/ws/console") as ws:
        ws.send_json({"token": TOKEN})
        msg = ws.receive_json()
        assert msg["type"] == "exit"
