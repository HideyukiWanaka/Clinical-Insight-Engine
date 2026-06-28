"""Unit tests for cie.agents.visualization.VisualizationAgent.

Test matrix:
- test_agent_id_and_scopes                  — agent_id="visualization", correct scopes
- test_missing_statistical_results_blocked  — VZ-001: no statistical_results → failed
- test_chart_type_continuous_comparison     — box_plot_with_jitter for default
- test_chart_type_paired_comparison         — slopegraph when paired=True
- test_chart_type_survival                  — kaplan_meier_curve
- test_chart_type_categorical               — grouped_bar_chart
- test_chart_type_correlation               — scatter_plot_with_regression_line
- test_colorblind_safe_palette_default      — VZ-003 Okabe-Ito palette in spec
- test_caption_draft_present                — VZ-004 every figure spec has caption_draft
- test_output_has_required_fields           — all mandatory keys present
- test_figure_manifest_populated            — figure_manifest has at least one entry
- test_r_packages_include_ggplot2           — ggplot2 always in packages_required
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from cie.agents.base import AgentInput
from cie.agents.visualization import OKABE_ITO_PALETTE, VisualizationAgent
from cie.security.capability_token import CapabilityScope, CapabilityToken

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXEC_ID = str(uuid.uuid4())
NODE_ID = "visualization_node"

_STAT_RESULTS = {
    "method_id": "independent_samples_t_test",
    "p_value": 0.034,
    "effect_size": 0.52,
    "n_total": 120,
}

_BASE_INTENT = {
    "objective": "between_group_comparison",
    "outcome_type": "continuous",
    "paired": False,
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
) -> VisualizationAgent:
    return VisualizationAgent(mock_policy_engine, mock_schema_registry, mock_audit)


@pytest.fixture
def token() -> CapabilityToken:
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id="visualization",
        bound_step_id=NODE_ID,
        granted_scopes=frozenset({
            CapabilityScope.DATASET_READ_VALIDATED,
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

    def test_agent_id_and_scopes(self, agent: VisualizationAgent) -> None:
        assert agent.agent_id == "visualization"
        assert CapabilityScope.DATASET_READ_VALIDATED in agent.required_scopes
        assert CapabilityScope.AUDIT_WRITE_ENTRY in agent.required_scopes


# ---------------------------------------------------------------------------
# VZ-001: Guard against missing statistical results
# ---------------------------------------------------------------------------


class TestVZ001Guard:

    async def test_missing_statistical_results_blocked(
        self, agent: VisualizationAgent, token: CapabilityToken
    ) -> None:
        """VZ-001: absent statistical_results → status='failed'."""
        payload = {k: v for k, v in _BASE_PAYLOAD.items() if k != "statistical_results"}
        result = await agent.run(_make_input(payload, token))

        assert result.status == "failed"
        assert "MISSING_STATISTICAL_INPUT" in (result.error_message or "")

    async def test_empty_statistical_results_blocked(
        self, agent: VisualizationAgent, token: CapabilityToken
    ) -> None:
        """VZ-001: empty statistical_results dict → status='failed'."""
        payload = {**_BASE_PAYLOAD, "statistical_results": {}}
        result = await agent.run(_make_input(payload, token))

        assert result.status == "failed"
        assert "MISSING_STATISTICAL_INPUT" in (result.error_message or "")


# ---------------------------------------------------------------------------
# VZ-002: Chart type selection (data-driven)
# ---------------------------------------------------------------------------


class TestChartTypeSelection:

    async def test_chart_type_continuous_comparison(
        self, agent: VisualizationAgent, token: CapabilityToken
    ) -> None:
        """Default continuous 2-group unpaired → box_plot_with_jitter."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        assert result.status == "success"
        specs = result.output_payload["visualization_specifications"]
        assert specs[0]["chart_type"] == "box_plot_with_jitter"

    async def test_chart_type_paired_comparison(
        self, agent: VisualizationAgent, token: CapabilityToken
    ) -> None:
        """Continuous, paired=True → slopegraph."""
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "paired": True},
        }
        result = await agent.run(_make_input(payload, token))

        specs = result.output_payload["visualization_specifications"]
        assert specs[0]["chart_type"] == "slopegraph"

    async def test_chart_type_survival(
        self, agent: VisualizationAgent, token: CapabilityToken
    ) -> None:
        """Survival analysis → kaplan_meier_curve."""
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "objective": "survival_analysis", "outcome_type": "survival"},
        }
        result = await agent.run(_make_input(payload, token))

        specs = result.output_payload["visualization_specifications"]
        assert specs[0]["chart_type"] == "kaplan_meier_curve"

    async def test_chart_type_categorical(
        self, agent: VisualizationAgent, token: CapabilityToken
    ) -> None:
        """Categorical binary outcome → grouped_bar_chart."""
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "outcome_type": "categorical_binary"},
        }
        result = await agent.run(_make_input(payload, token))

        specs = result.output_payload["visualization_specifications"]
        assert specs[0]["chart_type"] == "grouped_bar_chart"

    async def test_chart_type_correlation(
        self, agent: VisualizationAgent, token: CapabilityToken
    ) -> None:
        """Correlation objective → scatter_plot_with_regression_line."""
        payload = {
            **_BASE_PAYLOAD,
            "intent_object": {**_BASE_INTENT, "objective": "correlation_analysis"},
        }
        result = await agent.run(_make_input(payload, token))

        specs = result.output_payload["visualization_specifications"]
        assert specs[0]["chart_type"] == "scatter_plot_with_regression_line"


# ---------------------------------------------------------------------------
# VZ-003: Colorblind-safe palette
# ---------------------------------------------------------------------------


class TestVZ003Palette:

    async def test_colorblind_safe_palette_default(
        self, agent: VisualizationAgent, token: CapabilityToken
    ) -> None:
        """VZ-003: Okabe-Ito palette must be present in every figure spec."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        for spec in result.output_payload["visualization_specifications"]:
            assert spec["color_palette"] == OKABE_ITO_PALETTE
            assert spec["palette_name"] == "Okabe-Ito"

    def test_okabe_ito_palette_has_eight_colors(self) -> None:
        """Okabe-Ito palette constant must contain exactly 8 hex colors."""
        assert len(OKABE_ITO_PALETTE) == 8
        for color in OKABE_ITO_PALETTE:
            assert color.startswith("#"), f"Not a hex color: {color}"


# ---------------------------------------------------------------------------
# VZ-004: Caption required per figure
# ---------------------------------------------------------------------------


class TestVZ004Caption:

    async def test_caption_draft_present(
        self, agent: VisualizationAgent, token: CapabilityToken
    ) -> None:
        """VZ-004: every figure specification must include a caption_draft."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        for spec in result.output_payload["visualization_specifications"]:
            assert "caption_draft" in spec
            cap = spec["caption_draft"]
            assert "figure_label" in cap
            assert "description" in cap

    async def test_caption_drafts_list_matches_specs(
        self, agent: VisualizationAgent, token: CapabilityToken
    ) -> None:
        """caption_drafts list at top level mirrors visualization_specifications."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        op = result.output_payload
        assert len(op["caption_drafts"]) == len(op["visualization_specifications"])


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputContract:

    async def test_output_has_required_fields(
        self, agent: VisualizationAgent, token: CapabilityToken
    ) -> None:
        """All mandatory output fields must be present."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        op = result.output_payload
        for field in (
            "execution_id", "visualization_specifications",
            "r_script_specification", "figure_manifest",
            "caption_drafts", "created_at",
        ):
            assert field in op, f"Missing required field: {field}"

    async def test_figure_manifest_populated(
        self, agent: VisualizationAgent, token: CapabilityToken
    ) -> None:
        """figure_manifest must have at least one entry."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        manifest = result.output_payload["figure_manifest"]
        assert isinstance(manifest, list)
        assert len(manifest) >= 1
        assert "figure_id" in manifest[0]

    async def test_r_packages_include_ggplot2(
        self, agent: VisualizationAgent, token: CapabilityToken
    ) -> None:
        """ggplot2 must always appear in r_script_specification.packages_required."""
        result = await agent.run(_make_input(_BASE_PAYLOAD, token))

        r_spec = result.output_payload["r_script_specification"]
        assert "ggplot2" in r_spec["packages_required"]
