"""Integration tests for POST /api/workspace/reset (workspace-persistence §3).

Reset physically deletes the visible ``.RData`` + ``workspace_summary.json``
under the runtime OUTPUT_DIR so the next run starts empty. This is an ordinary
file deletion of a convenience cache (not knowledge soft-delete).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cie.api.main import create_app
from cie.security.capability_token import CapabilityTokenManager

TOKEN = "test-token"
AUTH = {"X-CIE-Token": TOKEN}


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "r_output"
    d.mkdir()
    return d


@pytest.fixture
def client(tmp_path: Path, output_dir: Path) -> TestClient:
    services = {
        "token_manager": CapabilityTokenManager(),
        "workspace_dir": str(tmp_path),
        "r_output_dir": output_dir,
    }
    app = create_app(services=services, session_token=TOKEN)
    with TestClient(app) as c:
        yield c


def test_reset_requires_auth(client: TestClient) -> None:
    assert client.post("/api/workspace/reset").status_code == 401


def test_reset_deletes_rdata_and_summary(client: TestClient, output_dir: Path) -> None:
    (output_dir / ".RData").write_bytes(b"binary")
    (output_dir / "workspace_summary.json").write_text("[]", encoding="utf-8")

    resp = client.post("/api/workspace/reset", headers=AUTH)
    assert resp.status_code == 200
    assert set(resp.json()["removed"]) == {".RData", "workspace_summary.json"}
    assert not (output_dir / ".RData").exists()
    assert not (output_dir / "workspace_summary.json").exists()


def test_reset_is_noop_when_nothing_persisted(client: TestClient) -> None:
    resp = client.post("/api/workspace/reset", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["removed"] == []


def test_reset_only_removes_workspace_files(client: TestClient, output_dir: Path) -> None:
    """Other artifacts (e.g. result.json, figures) must be left intact."""
    (output_dir / ".RData").write_bytes(b"x")
    (output_dir / "result.json").write_text("{}", encoding="utf-8")

    resp = client.post("/api/workspace/reset", headers=AUTH)
    assert resp.json()["removed"] == [".RData"]
    assert (output_dir / "result.json").exists()
