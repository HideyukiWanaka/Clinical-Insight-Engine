"""Integration tests for CORS configuration (OWASP A05:2025).

allow_methods/allow_headers were "*" — wider than anything the frontend
actually sends (frontend/src/api/client.ts only ever does GET/POST with
Content-Type + X-CIE-Token). Preflight responses must reflect the tightened,
explicit lists instead.
"""

from __future__ import annotations

import os

os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from fastapi.testclient import TestClient

from cie.api.main import create_app
from cie.security.capability_token import CapabilityTokenManager

TOKEN = "test-session-token"


@pytest.fixture
def client() -> TestClient:
    services = {"token_manager": CapabilityTokenManager()}
    app = create_app(services=services, session_token=TOKEN)
    with TestClient(app) as c:
        yield c


def test_preflight_allows_only_expected_methods(client: TestClient) -> None:
    resp = client.options(
        "/api/knowledge",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-cie-token",
        },
    )
    allowed = resp.headers["access-control-allow-methods"]
    assert "POST" in allowed
    assert "GET" in allowed
    assert "DELETE" not in allowed
    assert "PUT" not in allowed
    assert allowed != "*"


def test_preflight_rejects_unlisted_method(client: TestClient) -> None:
    resp = client.options(
        "/api/knowledge",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )
    # Starlette's CORSMiddleware answers with 400 when the requested method
    # isn't in allow_methods.
    assert resp.status_code == 400
