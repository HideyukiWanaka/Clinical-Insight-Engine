"""Unit tests for cie.agents.reviewer.ReviewerAgent.

Test matrix:
- test_agent_id_and_scopes               — canonical agent_id and required scopes
- test_all_consistent_returns_passed     — clean artifacts → review_passed=True, score=1.0
- test_p_value_in_manuscript_no_results  — CC-001: manuscript p-value, no stat results → critical
- test_effect_size_mismatch              — CC-002: effect size in manuscript, absent in results
- test_sample_size_mismatch              — CC-003: n=100 in manuscript vs n=50 in results → critical
- test_missing_figure_in_manifest        — CC-004: Figure 3 cited but not in manifest → critical
- test_unresolved_mandatory_checklist    — CC-005: mandatory item unresolved → critical
- test_ci_crosses_null_with_significant_p — CC-006: CI [−0.1, 0.3], p=0.04 → critical
- test_unresolved_items_advisory         — CC-007: unresolved_items → advisory, not critical
- test_review_passed_false_when_any_critical — any critical → review_passed=False
- test_readiness_score_decreases_with_findings — score calculation
- test_empty_payload_review_passes       — fully empty payload is accepted (no artifacts → no failures)
- test_figure_ref_missing_from_manifest  — multiple fig refs, one missing → exactly 1 critical
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from cie.agents.base import AgentInput, AgentOutput
from cie.agents.reviewer import ReviewerAgent
from cie.security.capability_token import CapabilityScope, CapabilityToken

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXEC_ID = str(uuid.uuid4())
NODE_ID = "reviewer_node"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_policy_engine() -> MagicMock:
    pe = MagicMock()
    pe.enforce_multi = AsyncMock()
    return pe


@pytest.fixture
def mock_schema_registry() -> MagicMock:
    sr = MagicMock()
    sr.validate = MagicMock()
    return sr


@pytest.fixture
def mock_audit() -> MagicMock:
    svc = MagicMock()
    svc.write = AsyncMock()
    return svc


@pytest.fixture
def agent(
    mock_policy_engine: MagicMock,
    mock_schema_registry: MagicMock,
    mock_audit: MagicMock,
) -> ReviewerAgent:
    return ReviewerAgent(
        policy_engine=mock_policy_engine,
        schema_registry=mock_schema_registry,
        audit_service=mock_audit,
    )


@pytest.fixture
def token() -> CapabilityToken:
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id="reviewer",
        bound_step_id=NODE_ID,
        granted_scopes=frozenset({
            CapabilityScope.WORKFLOW_STATE_READ,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        }),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=300),
    )


def _make_input(payload: dict[str, Any], token: CapabilityToken) -> AgentInput:
    return AgentInput(
        execution_id=EXEC_ID,
        node_id=NODE_ID,
        capability_token=token,
        payload=payload,
        input_schema_ref="cie://schemas/task.schema.json",
    )


def _run(agent: ReviewerAgent, payload: dict, token: CapabilityToken) -> AgentOutput:
    return asyncio.run(agent.run(_make_input(payload, token)))


# ---------------------------------------------------------------------------
# Clean baseline payload
# ---------------------------------------------------------------------------


def _clean_payload() -> dict[str, Any]:
    return {
        "statistical_results": {
            "sample_size": 120,
            "p_value": 0.03,
            "effect_size": 0.45,
            "ci_lower": 0.1,
            "ci_upper": 0.8,
        },
        "figure_manifest": [
            {"figure_id": "1", "label": "Figure 1", "caption": "Kaplan-Meier curve"},
            {"figure_id": "2", "label": "Figure 2", "caption": "Forest plot"},
        ],
        "manuscript_sections": {
            "results": (
                "We found a significant effect (p=0.03, Cohen's d = 0.45). "
                "The sample size was n=120. See Figure 1 and Figure 2."
            ),
        },
        "reporting_checklist_status": {
            "CONSORT-1": {"mandatory": True, "resolved": True},
            "CONSORT-2": {"mandatory": False, "resolved": False},
        },
    }


# ---------------------------------------------------------------------------
# Identity tests
# ---------------------------------------------------------------------------


class TestAgentIdentity:
    def test_agent_id(self, agent: ReviewerAgent) -> None:
        assert agent.agent_id == "reviewer"

    def test_required_scopes(self, agent: ReviewerAgent) -> None:
        scopes = agent.required_scopes
        assert CapabilityScope.WORKFLOW_STATE_READ in scopes
        assert CapabilityScope.AUDIT_WRITE_ENTRY in scopes

    def test_input_schema_ref(self, agent: ReviewerAgent) -> None:
        assert agent.input_schema_ref == "cie://schemas/task.schema.json"

    def test_output_schema_ref(self, agent: ReviewerAgent) -> None:
        assert agent.output_schema_ref == "cie://schemas/report.schema.json"


# ---------------------------------------------------------------------------
# All-consistent baseline
# ---------------------------------------------------------------------------


class TestCleanArtifacts:
    def test_all_consistent_returns_passed(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        output = _run(agent, _clean_payload(), token)
        assert output.status == "success"
        assert output.output_payload["review_passed"] is True
        assert output.output_payload["critical_findings"] == []
        assert output.output_payload["readiness_score"] == 1.0

    def test_consistency_matrix_keys_present(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        output = _run(agent, _clean_payload(), token)
        matrix = output.output_payload["consistency_matrix"]
        for check_id in ("CC-001", "CC-002", "CC-003", "CC-004", "CC-005"):
            assert check_id in matrix

    def test_review_report_has_required_fields(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        output = _run(agent, _clean_payload(), token)
        report = output.output_payload["review_report"]
        assert "report_id" in report
        assert "reviewed_at" in report
        assert report["summary"]["review_passed"] is True


# ---------------------------------------------------------------------------
# CC-001: p-values
# ---------------------------------------------------------------------------


class TestCC001PValues:
    def test_p_value_in_manuscript_no_results(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {},       # no p-values
            "figure_manifest": [],
            "manuscript_sections": {"results": "We found p=0.03."},
            "reporting_checklist_status": {},
        }
        output = _run(agent, payload, token)
        cc001 = [f for f in output.output_payload["critical_findings"] if f["check_id"] == "CC-001"]
        assert len(cc001) == 1
        assert output.output_payload["review_passed"] is False


# ---------------------------------------------------------------------------
# CC-002: effect sizes
# ---------------------------------------------------------------------------


class TestCC002EffectSizes:
    def test_effect_size_in_manuscript_absent_in_results(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {"p_value": 0.03},   # no effect_size
            "figure_manifest": [],
            "manuscript_sections": {"results": "Cohen's d = 0.45"},
            "reporting_checklist_status": {},
        }
        output = _run(agent, payload, token)
        cc002 = [f for f in output.output_payload["critical_findings"] if f["check_id"] == "CC-002"]
        assert len(cc002) == 1


# ---------------------------------------------------------------------------
# CC-003: sample size
# ---------------------------------------------------------------------------


class TestCC003SampleSize:
    def test_sample_size_mismatch_is_critical(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {"sample_size": 50},
            "figure_manifest": [],
            "manuscript_sections": {"results": "n=100 participants were enrolled."},
            "reporting_checklist_status": {},
        }
        output = _run(agent, payload, token)
        cc003 = [f for f in output.output_payload["critical_findings"] if f["check_id"] == "CC-003"]
        assert len(cc003) == 1
        assert "50" in cc003[0]["description"]
        assert "100" in cc003[0]["description"]

    def test_matching_sample_size_passes(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {"sample_size": 100},
            "figure_manifest": [],
            "manuscript_sections": {"results": "n=100 participants."},
            "reporting_checklist_status": {},
        }
        output = _run(agent, payload, token)
        cc003 = [f for f in output.output_payload["critical_findings"] if f["check_id"] == "CC-003"]
        assert len(cc003) == 0


# ---------------------------------------------------------------------------
# CC-004: figures
# ---------------------------------------------------------------------------


class TestCC004Figures:
    def test_missing_figure_in_manifest_is_critical(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {},
            "figure_manifest": [{"figure_id": "1", "label": "Figure 1"}],
            "manuscript_sections": {
                "results": "See Figure 1 and Figure 3 for details.",
            },
            "reporting_checklist_status": {},
        }
        output = _run(agent, payload, token)
        cc004 = [f for f in output.output_payload["critical_findings"] if f["check_id"] == "CC-004"]
        assert len(cc004) == 1
        assert "3" in cc004[0]["description"]

    def test_all_figures_present_passes(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {},
            "figure_manifest": [
                {"figure_id": "1", "label": "Figure 1"},
                {"figure_id": "2", "label": "Figure 2"},
            ],
            "manuscript_sections": {"results": "Figure 1 and Figure 2."},
            "reporting_checklist_status": {},
        }
        output = _run(agent, payload, token)
        cc004 = [f for f in output.output_payload["critical_findings"] if f["check_id"] == "CC-004"]
        assert len(cc004) == 0


# ---------------------------------------------------------------------------
# CC-005: checklist
# ---------------------------------------------------------------------------


class TestCC005Checklist:
    def test_unresolved_mandatory_item_is_critical(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {},
            "figure_manifest": [],
            "manuscript_sections": {},
            "reporting_checklist_status": {
                "CONSORT-1": {"mandatory": True, "resolved": False},
            },
        }
        output = _run(agent, payload, token)
        cc005 = [f for f in output.output_payload["critical_findings"] if f["check_id"] == "CC-005"]
        assert len(cc005) == 1

    def test_non_mandatory_unresolved_does_not_block(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {},
            "figure_manifest": [],
            "manuscript_sections": {},
            "reporting_checklist_status": {
                "SPIRIT-3": {"mandatory": False, "resolved": False},
            },
        }
        output = _run(agent, payload, token)
        assert output.output_payload["review_passed"] is True


# ---------------------------------------------------------------------------
# CC-006: CI / significance consistency
# ---------------------------------------------------------------------------


class TestCC006CIConsistency:
    def test_significant_p_with_null_crossing_ci_is_critical(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {
                "p_value": 0.04,
                "ci_lower": -0.1,
                "ci_upper": 0.3,
            },
            "figure_manifest": [],
            "manuscript_sections": {},
            "reporting_checklist_status": {},
        }
        output = _run(agent, payload, token)
        cc006 = [f for f in output.output_payload["critical_findings"] if f["check_id"] == "CC-006"]
        assert len(cc006) == 1

    def test_non_significant_p_with_null_crossing_ci_passes(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {
                "p_value": 0.20,
                "ci_lower": -0.1,
                "ci_upper": 0.3,
            },
            "figure_manifest": [],
            "manuscript_sections": {},
            "reporting_checklist_status": {},
        }
        output = _run(agent, payload, token)
        cc006 = [f for f in output.output_payload["critical_findings"] if f["check_id"] == "CC-006"]
        assert len(cc006) == 0


# ---------------------------------------------------------------------------
# CC-007: unresolved_items
# ---------------------------------------------------------------------------


class TestCC007UnresolvedItems:
    def test_unresolved_items_produce_advisory(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {"unresolved_items": ["need_imputation", "check_outliers"]},
            "figure_manifest": [],
            "manuscript_sections": {},
            "reporting_checklist_status": {},
        }
        output = _run(agent, payload, token)
        cc007 = [f for f in output.output_payload["advisory_findings"] if f["check_id"] == "CC-007"]
        assert len(cc007) == 2
        assert output.output_payload["review_passed"] is True  # advisory only


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


class TestReadinessScore:
    def test_score_is_1_when_no_findings(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        output = _run(agent, {"statistical_results": {}, "figure_manifest": [],
                               "manuscript_sections": {}, "reporting_checklist_status": {}}, token)
        assert output.output_payload["readiness_score"] == 1.0

    def test_score_decreases_with_critical_finding(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {"p_value": 0.04, "ci_lower": -0.1, "ci_upper": 0.3},
            "figure_manifest": [],
            "manuscript_sections": {},
            "reporting_checklist_status": {},
        }
        output = _run(agent, payload, token)
        assert output.output_payload["readiness_score"] < 1.0

    def test_score_never_below_zero(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {
                "p_value": 0.04,
                "ci_lower": -0.5,
                "ci_upper": 0.5,
                "unresolved_items": [f"item_{i}" for i in range(30)],
            },
            "figure_manifest": [],
            "manuscript_sections": {"r": "p=0.04 n=999 Cohen's d = 0.5"},
            "reporting_checklist_status": {
                f"ITEM-{i}": {"mandatory": True, "resolved": False} for i in range(5)
            },
        }
        output = _run(agent, payload, token)
        assert output.output_payload["readiness_score"] >= 0.0

    def test_review_passed_false_when_any_critical(
        self, agent: ReviewerAgent, token: CapabilityToken
    ) -> None:
        payload = {
            "statistical_results": {},
            "figure_manifest": [],
            "manuscript_sections": {"r": "p=0.04"},  # manuscript has p-value, results empty
            "reporting_checklist_status": {},
        }
        output = _run(agent, payload, token)
        assert output.output_payload["review_passed"] is False
