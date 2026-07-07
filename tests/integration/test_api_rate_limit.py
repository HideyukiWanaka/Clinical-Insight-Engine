"""Integration test for RateLimitMiddleware on POST /api/intent (OWASP A04:2025).

/api/intent is configured for 10 requests / 60s (cie/api/rate_limit.py). The
11th request from the same client within the window must get 429, and a
different client must be unaffected.
"""

from __future__ import annotations

import os

os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from fastapi.testclient import TestClient

from cie.agents.base import AgentInput, AgentOutput
from cie.api.main import create_app
from cie.security.capability_token import CapabilityTokenManager

TOKEN = "test-session-token"
AUTH = {"X-CIE-Token": TOKEN}


class FakePlanner:
    async def run(self, agent_input: AgentInput) -> AgentOutput:
        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id="planner",
            status="success",
            output_payload={
                "intent_object": {"objective": "between_group_comparison"},
                "confidence_score": 0.9,
                "requires_human_clarification": False,
                "clarification_options": [],
            },
            output_schema_ref="cie://schemas/task-context.schema.json",
        )


@pytest.fixture
def client() -> TestClient:
    services = {
        "token_manager": CapabilityTokenManager(),
        "planner": FakePlanner(),
    }
    app = create_app(services=services, session_token=TOKEN)
    with TestClient(app) as c:
        yield c


def test_11th_request_in_window_is_rate_limited(client: TestClient) -> None:
    for _ in range(10):
        resp = client.post("/api/intent", headers=AUTH, json={"prompt": "x"})
        assert resp.status_code == 200

    resp = client.post("/api/intent", headers=AUTH, json={"prompt": "x"})
    assert resp.status_code == 429
    assert resp.json()["error_code"] == "RATE_LIMITED"
    assert "Retry-After" in resp.headers


def test_unrelated_endpoint_is_not_rate_limited_by_intent_quota(
    client: TestClient,
) -> None:
    for _ in range(10):
        client.post("/api/intent", headers=AUTH, json={"prompt": "x"})

    resp = client.post("/api/knowledge/reindex", headers=AUTH)
    assert resp.status_code == 501  # not 429 — different quota bucket
