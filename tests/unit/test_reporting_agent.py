"""Unit tests for cie.agents.reporting.ReportingAgent.

Test matrix:
- test_agent_id_and_scopes                  — agent_id="reporting", correct scopes
- test_missing_statistical_results_blocked  — RP-002: no statistical_results → failed
- test_checklist_inferred_for_rct           — RP-003: RCT → CONSORT
- test_checklist_inferred_for_observational — RP-003: observational → STROBE
- test_checklist_inferred_for_cohort        — RP-003: cohort → STROBE
- test_checklist_inferred_for_prediction    — RP-003: prediction_model → TRIPOD
- test_explicit_checklist_not_overridden    — user-supplied checklist preserved
- test_unresolved_items_populated           — RP-004: unresolved_items not empty
- test_output_has_required_fields           — manuscript_sections, table_specifications, etc.
- test_traceability_tags_in_methods_section — RP-001: [TRACE:] tags present
- test_traceability_tags_in_results_section — RP-001: [TRACE:] tags in results
- test_word_count_estimate_present          — word_count_estimate is an int ≥ 0
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from cie.agents.base import AgentInput
from cie.agents.reporting import ReportingAgent
from cie.security.capability_token import CapabilityScope, CapabilityToken

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXEC_ID = str(uuid.uuid4())
NODE_ID = "reporting_node"

_STAT_RESULTS = {
    "method_id": "independent_samples_t_test",
    "p_value": 0.034,
    "effect_size": 0.52,
    "n_total": 120,
    "confidence_interval": [0.12, 0.92],
}

_BASE_INTENT = {
    "objective": "between_group_comparison",
    "outcome_type": "continuous",
    "study_design": "randomized_controlled_trial",
}

_BASE_PAYLOAD = {
    "execution_id": EXEC_ID,
    "intent_object": _BASE_INTENT,
    "statistical_results": _STAT_RESULTS,
}


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
) -> ReportingAgent:
    return ReportingAgent(mock_policy_engine, mock_schema_registry, mock_audit)


@pytest.fixture
def token() -> CapabilityToken:
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id="reporting",
        bound_step_id=NODE_ID,
        granted_scopes=frozenset({
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.REPORT_COMPILE_MANUSCRIPT,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        }),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=300),
    )


def _make_input(payload: dict, token: CapabilityToken) -> AgentInput:
    return AgentInput(
        execution_id=EXEC_ID,
        node_id=NODE_ID,
        capability_token=token,
        payload=payload,
        input_schema_ref="cie://schemas/analysis-request.schema.json",
    )


# ---------------------------------------------------------------------------
# Identity tests
# ---------------------------------------------------------------------------


class TestAgentIdentity:

    def test_agent_id_and_scopes(self, agent: ReportingAgent) -> None:
        assert agent.agent_id == "reporting"
        assert CapabilityScope.DATASET_READ_VALIDATED in agent.required_scopes
        assert CapabilityScope.REPORT_COMPILE_MANUSCRIPT in agent.required_scopes
        assert CapabilityScope.AUDIT_WRITE_ENTRY in agent.required_scopes


# ---------------------------------------------------------------------------
# RP-002: Guard against missing statistical results
# ---------------------------------------------------------------------------


class TestRP002Guard:

    async def test_missing_statistical_results_blocked(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """RP-002: absent statistical_results → status='failed'."""
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "statistical_results"}
        result = await agent.run(_make_input(payload, token))

        assert result.status == "failed"
        assert "MISSING_STATISTICAL_INPUT" in (result.error_message or "")

    async def test_empty_statistical_results_blocked(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """RP-002: empty statistical_results dict → status='failed'."""
        payload = {**_BASE_PAYLOAD, "statistical_results": {}}
        result = await agent.run(_make_input(payload, token))

        assert result.status == "failed"
        assert "MISSING_STATISTICAL_INPUT" in (result.error_message or "")


# ---------------------------------------------------------------------------
# RP-003: Checklist inference
# ---------------------------------------------------------------------------


class TestRP003ChecklistInference:

    async def test_checklist_inferred_for_rct(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """RP-003: study_design='randomized_controlled_trial' → CONSORT."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        assert result.status == "success"
        checklist_status = result.output_payload["reporting_checklist_status"]
        assert checklist_status["checklist_id"] == "CONSORT"
        assert checklist_status["checklist_inferred"] is True

    async def test_checklist_inferred_for_observational(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """RP-003: study_design='observational' → STROBE."""
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "study_design": "observational"},
        }
        result = await agent.run(_make_input(payload, token))

        checklist_status = result.output_payload["reporting_checklist_status"]
        assert checklist_status["checklist_id"] == "STROBE"

    async def test_checklist_inferred_for_cohort(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """RP-003: study_design='cohort' → STROBE."""
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "study_design": "cohort"},
        }
        result = await agent.run(_make_input(payload, token))

        checklist_status = result.output_payload["reporting_checklist_status"]
        assert checklist_status["checklist_id"] == "STROBE"

    async def test_checklist_inferred_for_prediction(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """RP-003: study_design='prediction_model' → TRIPOD."""
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "study_design": "prediction_model"},
        }
        result = await agent.run(_make_input(payload, token))

        checklist_status = result.output_payload["reporting_checklist_status"]
        assert checklist_status["checklist_id"] == "TRIPOD"

    async def test_explicit_checklist_not_overridden(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """User-supplied reporting_checklist_id takes precedence over inference."""
        payload = {**_BASE_PAYLOAD, "reporting_checklist_id": "PRISMA"}
        result = await agent.run(_make_input(payload, token))

        checklist_status = result.output_payload["reporting_checklist_status"]
        assert checklist_status["checklist_id"] == "PRISMA"
        assert checklist_status["checklist_inferred"] is False


# ---------------------------------------------------------------------------
# RP-004: Unresolved items always populated
# ---------------------------------------------------------------------------


class TestRP004UnresolvedItems:

    async def test_unresolved_items_populated(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """RP-004: unresolved_items must always contain human-required decisions."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        unresolved = result.output_payload["unresolved_items"]
        assert isinstance(unresolved, list)
        assert len(unresolved) > 0


# ---------------------------------------------------------------------------
# RP-001: Traceability
# ---------------------------------------------------------------------------


class TestRP001Traceability:

    async def test_traceability_tags_in_methods_section(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """RP-001: [TRACE:] markers must appear in the Methods section content."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        sections = {s["section_id"]: s for s in result.output_payload["manuscript_sections"]}
        assert "methods" in sections
        assert "[TRACE:" in sections["methods"]["content"]

    async def test_traceability_tags_in_results_section(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """RP-001: [TRACE:] markers must appear in the Results section content."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        sections = {s["section_id"]: s for s in result.output_payload["manuscript_sections"]}
        assert "results" in sections
        assert "[TRACE:" in sections["results"]["content"]


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputContract:

    async def test_output_has_required_fields(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """All mandatory output fields must be present."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        op = result.output_payload
        for field in (
            "execution_id", "manuscript_sections", "table_specifications",
            "reporting_checklist_status", "unresolved_items",
            "word_count_estimate", "created_at",
        ):
            assert field in op, f"Missing required field: {field}"

    async def test_word_count_estimate_present(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """word_count_estimate must be a non-negative integer."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        wc = result.output_payload["word_count_estimate"]
        assert isinstance(wc, int)
        assert wc >= 0

    async def test_table_specifications_populated(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """table_specifications must have at least one entry."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        tables = result.output_payload["table_specifications"]
        assert isinstance(tables, list)
        assert len(tables) >= 1
        assert "table_id" in tables[0]

    async def test_checklist_items_present_for_consort(
        self, agent: ReportingAgent, token: CapabilityToken
    ) -> None:
        """CONSORT checklist must contain items with item_id and status."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        items = result.output_payload["reporting_checklist_status"]["items"]
        assert isinstance(items, list)
        assert len(items) > 0
        for item in items:
            assert "item_id" in item
            assert "status" in item
