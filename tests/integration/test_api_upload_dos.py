"""Integration tests for upload size limits on POST /api/dataset and
POST /api/knowledge/ingest (OWASP A03:2025 — unbounded upload DoS).

Both endpoints must reject an oversized upload with 413 before it is fully
buffered or handed to downstream processing (build_dataset_context /
IngestionGuard). MAX_*_BYTES is monkeypatched down so the test doesn't need
to generate real 50-100 MB payloads.
"""

from __future__ import annotations

import os

os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

import pytest
from fastapi.testclient import TestClient

import cie.api.routes.dataset as dataset_route
import cie.api.routes.knowledge as knowledge_route
from cie.api.main import create_app
from cie.security.capability_token import CapabilityTokenManager

TOKEN = "test-session-token"
AUTH = {"X-CIE-Token": TOKEN}


class FakeDraft:
    def __init__(self, draft_id: str) -> None:
        self.draft_id = draft_id
        self.extracted_metadata: dict = {}
        self.extracted_domain = "general"
        self.extracted_trust_level = "unverified"
        self.extracted_knowledge_items: list = []
        self.extraction_limitations: list = []


class FakeKnowledgeIngestion:
    async def ingest(self, path, file_bytes: bytes, *, uploaded_by: str) -> FakeDraft:
        return FakeDraft(draft_id="draft-1")


@pytest.fixture
def client(tmp_path) -> TestClient:
    services = {
        "token_manager": CapabilityTokenManager(),
        "knowledge_ingestion": FakeKnowledgeIngestion(),
    }
    app = create_app(services=services, session_token=TOKEN)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# POST /api/dataset
# ---------------------------------------------------------------------------


def test_dataset_upload_under_limit_succeeds(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(dataset_route, "MAX_CSV_BYTES", 1000)
    resp = client.post(
        "/api/dataset",
        headers=AUTH,
        files={"file": ("data.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert resp.status_code == 200


def test_dataset_upload_over_limit_rejected(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(dataset_route, "MAX_CSV_BYTES", 100)
    resp = client.post(
        "/api/dataset",
        headers=AUTH,
        files={"file": ("data.csv", b"x" * 500, "text/csv")},
    )
    assert resp.status_code == 413
    assert resp.json()["detail"]["error_code"] == "FILE_TOO_LARGE"


# ---------------------------------------------------------------------------
# POST /api/knowledge/ingest
# ---------------------------------------------------------------------------


def test_knowledge_ingest_under_limit_succeeds(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(knowledge_route, "MAX_FILE_SIZE_BYTES", 1000)
    resp = client.post(
        "/api/knowledge/ingest",
        headers=AUTH,
        files={"file": ("doc.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json()["draft_id"] == "draft-1"


def test_knowledge_ingest_over_limit_rejected(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(knowledge_route, "MAX_FILE_SIZE_BYTES", 100)
    resp = client.post(
        "/api/knowledge/ingest",
        headers=AUTH,
        files={"file": ("doc.txt", b"x" * 500, "text/plain")},
    )
    assert resp.status_code == 413
    assert resp.json()["detail"]["error_code"] == "FILE_TOO_LARGE"
