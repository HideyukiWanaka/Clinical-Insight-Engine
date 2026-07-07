"""tests/integration/test_api_endpoints.py — Phase 1 REST contract tests.

Verifies ``spec/api/rest-api-contract.md`` §2–§5 against the real FastAPI app
via ``TestClient``. Agents are lightweight fakes (like the E2E suite) so the
tests are deterministic and need neither a live LLM nor R — but the real
``CapabilityTokenManager`` is used, so the token issue→run→revoke path (and the
per-agent scope allow-list) is genuinely exercised.

Covered:
- §2 auth wall: unauthenticated requests → 401 on every /api/* endpoint.
- §3 happy-path envelopes carry execution_id.
- §5 / §3.2 / §3.3 no silent failures: a failing agent surfaces
  error_detail / r_script_provenance.reason.
- §3.7 path traversal is rejected.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")

from fastapi.testclient import TestClient  # noqa: E402

from cie.agents.base import AgentInput, AgentOutput  # noqa: E402
from cie.api.main import create_app  # noqa: E402
from cie.security.capability_token import CapabilityTokenManager  # noqa: E402

TOKEN = "test-session-token"
AUTH = {"X-CIE-Token": TOKEN}


class FakeAgent:
    """Minimal agent stub: records the input, returns a canned AgentOutput."""

    def __init__(self, agent_id: str, payload: dict, *, status: str = "success",
                 error_message: str | None = None) -> None:
        self.agent_id = agent_id
        self._payload = payload
        self._status = status
        self._error_message = error_message
        self.last_input: AgentInput | None = None

    async def run(self, agent_input: AgentInput) -> AgentOutput:
        self.last_input = agent_input
        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status=self._status,
            output_payload=self._payload if self._status == "success" else {},
            output_schema_ref="cie://schemas/task-context.schema.json",
            error_code=None if self._status == "success" else "FAKE_FAIL",
            error_message=self._error_message,
        )


class FakeContextGuard:
    """Async sanitize_stdout that redacts a marker token (RT-004 stand-in)."""

    async def sanitize_stdout(self, stdout: str, execution_id: str) -> str:
        return stdout.replace("SECRET", "[REDACTED]")


class FakeKnowledgeLoader:
    """Returns an empty FrozenKnowledgeSet-like object."""

    class _Frozen:
        entries: tuple = ()

    def load_for_execution(self, execution_id: str) -> "FakeKnowledgeLoader._Frozen":
        return self._Frozen()


def _make_services(tmp_path, **overrides) -> dict:
    services = {
        "token_manager": CapabilityTokenManager(),
        "context_guard": FakeContextGuard(),
        "workspace_dir": str(tmp_path),
        "planner": FakeAgent("planner", {
            "intent_object": {"objective": "between_group_comparison"},
            "confidence_score": 0.9,
            "requires_human_clarification": False,
            "clarification_options": [],
        }),
        "statistics": FakeAgent("statistics", {
            "analysis_proposal": {
                "explanation_markdown": "Use a t-test.",
                "code_candidates": [
                    {"candidate_id": "c1", "label": "t-test", "r_code": "t.test(...)"}
                ],
                "recommended_candidate_id": "c1",
            },
            "r_script_provenance": {"llm_generated": True, "reason": None},
        }),
        "runtime_agent": FakeAgent("runtime", {
            "execution_result": {
                "status": "completed", "exit_code": 0,
                "sanitized_stdout_summary": "[1] 2\nSECRET-leak",
            },
            "statistical_results": {"p_value": 0.03},
            "generated_files": ["r_output/result.json"],
        }),
        "visualization": FakeAgent("visualization", {
            "figure_manifest": [{"figure_id": "fig1", "actual_path": "viz/fig1.png"}],
        }),
        "reporting": FakeAgent("reporting", {
            "manuscript_sections": [
                {"section_id": "results", "content": "We found...", "llm_generated": True}
            ],
        }),
        "knowledge_loader": FakeKnowledgeLoader(),
    }
    services.update(overrides)
    return services


@pytest.fixture
def client(tmp_path) -> TestClient:
    app = create_app(services=_make_services(tmp_path), session_token=TOKEN)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# §2 — auth wall
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/intent"),
        ("post", "/api/propose"),
        ("post", "/api/run"),
        ("post", "/api/visualize"),
        ("post", "/api/report"),
        ("get", "/api/files"),
        ("get", "/api/knowledge"),
    ],
)
def test_unauthenticated_requests_are_401(client: TestClient, method: str, path: str) -> None:
    kwargs = {"json": {}} if method == "post" else {}
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "UNAUTHORIZED"


def test_wrong_token_is_401(client: TestClient) -> None:
    resp = client.get("/api/files", headers={"X-CIE-Token": "nope"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# §3 — happy-path envelopes
# ---------------------------------------------------------------------------

def test_intent_returns_intent_object(client: TestClient) -> None:
    resp = client.post("/api/intent", headers=AUTH,
                       json={"prompt": "compare groups", "dataset_uploaded": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["execution_id"]
    assert body["intent_object"]["objective"] == "between_group_comparison"
    assert body["confidence_score"] == pytest.approx(0.9)


def test_propose_returns_proposal(client: TestClient) -> None:
    resp = client.post("/api/propose", headers=AUTH, json={"intent_object": {}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["execution_id"]
    assert body["analysis_proposal"]["recommended_candidate_id"] == "c1"


def test_run_returns_results(client: TestClient) -> None:
    resp = client.post("/api/run", headers=AUTH,
                       json={"r_script": "print(1+1)", "persist_workspace": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["execution_id"]
    assert body["execution_result"]["status"] == "completed"
    assert body["statistical_results"]["p_value"] == pytest.approx(0.03)
    assert body["error_detail"] is None


def test_visualize_returns_figures(client: TestClient) -> None:
    resp = client.post("/api/visualize", headers=AUTH,
                       json={"statistical_results": {"p_value": 0.03}, "intent_object": {}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["figures"][0]["path"] == "viz/fig1.png"


def test_report_returns_sections(client: TestClient) -> None:
    resp = client.post("/api/report", headers=AUTH,
                       json={"statistical_results": {}, "intent_object": {}})
    assert resp.status_code == 200
    body = resp.json()
    section = body["manuscript_sections"][0]
    assert section["section_id"] == "results"
    assert section["is_ai_generated"] is True


# ---------------------------------------------------------------------------
# §5 / §3.2 / §3.3 — no silent failures
# ---------------------------------------------------------------------------

def test_propose_failure_carries_reason(tmp_path) -> None:
    services = _make_services(
        tmp_path,
        statistics=FakeAgent("statistics", {}, status="failed",
                             error_message="llm_error: no key"),
    )
    app = create_app(services=services, session_token=TOKEN)
    with TestClient(app) as c:
        resp = c.post("/api/propose", headers=AUTH, json={"intent_object": {}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis_proposal"] is None
    assert body["r_script_provenance"]["reason"] == "llm_error: no key"


def test_run_failure_populates_error_detail(tmp_path) -> None:
    services = _make_services(
        tmp_path,
        runtime_agent=FakeAgent("runtime", {}, status="failed",
                                error_message="RuntimeExecutionError: boom"),
    )
    app = create_app(services=services, session_token=TOKEN)
    with TestClient(app) as c:
        resp = c.post("/api/run", headers=AUTH, json={"r_script": "stop()"})
    assert resp.status_code == 200
    assert resp.json()["error_detail"] == "RuntimeExecutionError: boom"


def test_intent_failure_returns_500_with_reason(tmp_path) -> None:
    services = _make_services(
        tmp_path,
        planner=FakeAgent("planner", {}, status="failed", error_message="AGENT_ERROR: llm"),
    )
    app = create_app(services=services, session_token=TOKEN)
    with TestClient(app) as c:
        resp = c.post("/api/intent", headers=AUTH, json={"prompt": "x"})
    assert resp.status_code == 500
    assert resp.json()["detail"]["detail"] == "AGENT_ERROR: llm"


# ---------------------------------------------------------------------------
# §3.6 / §3.7 — files + path traversal
# ---------------------------------------------------------------------------

def test_files_listing_and_content(client: TestClient, tmp_path) -> None:
    (tmp_path / "analysis.R").write_text("print(1+1)\n", encoding="utf-8")
    resp = client.get("/api/files", headers=AUTH)
    assert resp.status_code == 200
    files = resp.json()["files"]
    assert any(f["path"] == "analysis.R" and f["kind"] == "text" for f in files)

    content = client.get("/api/files/content", headers=AUTH, params={"path": "analysis.R"})
    assert content.status_code == 200
    assert content.json()["language"] == "r"


def test_path_traversal_rejected(client: TestClient) -> None:
    resp = client.get("/api/files/content", headers=AUTH,
                      params={"path": "../../../etc/passwd"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "PATH_TRAVERSAL"


def test_symlinked_file_outside_workspace_not_listed(
    client: TestClient, tmp_path
) -> None:
    """A symlink planted inside the workspace must not surface an outside file
    in the listing (OWASP A01:2025 — broken access control via symlink escape).
    """
    outside_dir = tmp_path.parent / "outside_secret"
    outside_dir.mkdir(exist_ok=True)
    (outside_dir / "secret.txt").write_text("top secret", encoding="utf-8")
    (tmp_path / "escape_link.txt").symlink_to(outside_dir / "secret.txt")

    resp = client.get("/api/files", headers=AUTH)
    assert resp.status_code == 200
    paths = [f["path"] for f in resp.json()["files"]]
    assert "escape_link.txt" not in paths


def test_symlinked_directory_contents_not_listed(client: TestClient, tmp_path) -> None:
    outside_dir = tmp_path.parent / "outside_dir"
    outside_dir.mkdir(exist_ok=True)
    (outside_dir / "leaked.txt").write_text("leaked", encoding="utf-8")
    (tmp_path / "linked_subdir").symlink_to(outside_dir)

    resp = client.get("/api/files", headers=AUTH)
    assert resp.status_code == 200
    paths = [f["path"] for f in resp.json()["files"]]
    assert not any("leaked.txt" in p for p in paths)


# ---------------------------------------------------------------------------
# §3.8 / §3.9 — knowledge
# ---------------------------------------------------------------------------

def test_knowledge_list_ok(client: TestClient) -> None:
    resp = client.get("/api/knowledge", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["entries"] == []


def test_knowledge_reindex_is_501_phase5(client: TestClient) -> None:
    resp = client.post("/api/knowledge/reindex", headers=AUTH)
    assert resp.status_code == 501
    assert resp.json()["detail"]["error_code"] == "NOT_IMPLEMENTED"
