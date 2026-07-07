"""Integration tests for SecurityHeadersMiddleware (OWASP A05:2025).

Every response — success or error, protected or not — must carry the
baseline hardening headers.
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


def test_security_headers_present_on_success(client: TestClient) -> None:
    # /api/knowledge/reindex needs no wired services (always 501 — Phase 5).
    resp = client.post("/api/knowledge/reindex", headers={"X-CIE-Token": TOKEN})
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Content-Security-Policy"] == "default-src 'self'"
    assert "max-age=31536000" in resp.headers["Strict-Transport-Security"]


def test_security_headers_present_on_401(client: TestClient) -> None:
    resp = client.get("/api/knowledge")
    assert resp.status_code == 401
    assert resp.headers["X-Frame-Options"] == "DENY"
