"""CIE Platform — Visualization Agent.

Selects chart types, produces visualization specifications, and declares
ggplot2 script templates from validated statistical results.  This agent
NEVER accesses raw patient data and NEVER executes R code.

Key rules (agents/visualization.yaml):
  VZ-001  No raw patient data — only aggregated statistical results.
  VZ-002  Chart type selected from data characteristics, not aesthetics.
  VZ-003  All palettes colorblind-safe; Okabe-Ito is the default.
  VZ-004  Every figure must have a caption_draft.
  VZ-005  Schema-conforming JSON output only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.audit import AuditService
from cie.core.exceptions import AgentError
from cie.schemas.validator import SchemaRegistry
from cie.security.capability_token import CapabilityScope
from cie.security.policy_engine import PolicyEngine

# ---------------------------------------------------------------------------
# Colorblind-safe palette (VZ-003)
# ---------------------------------------------------------------------------

OKABE_ITO_PALETTE: list[str] = [
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#009E73",  # bluish green
    "#F0E442",  # yellow
    "#0072B2",  # blue
    "#D55E00",  # vermilion
    "#CC79A7",  # reddish purple
    "#000000",  # black
]

# ---------------------------------------------------------------------------
# Chart type catalogue (visualization.yaml chart_selection_framework)
# ---------------------------------------------------------------------------

_CHART_SPECS: dict[str, dict] = {
    "box_plot_with_jitter": {
        "chart_type": "box_plot_with_jitter",
        "ggplot2_geom": ["geom_boxplot", "geom_jitter"],
        "description": "Distribution comparison between groups with individual data points.",
    },
    "violin_plot": {
        "chart_type": "violin_plot",
        "ggplot2_geom": ["geom_violin", "geom_boxplot"],
        "description": "Kernel density mirrored for detailed distribution shape.",
    },
    "slopegraph": {
        "chart_type": "slopegraph",
        "ggplot2_geom": ["geom_line", "geom_point"],
        "description": "Paired data slope visualization showing individual trajectories.",
    },
    "scatter_plot_with_regression_line": {
        "chart_type": "scatter_plot_with_regression_line",
        "ggplot2_geom": ["geom_point", "geom_smooth"],
        "description": "Correlation scatter plot with fitted regression line and CI band.",
    },
    "kaplan_meier_curve": {
        "chart_type": "kaplan_meier_curve",
        "ggplot2_geom": ["geom_step", "geom_ribbon"],
        "description": "Survival probability over time with confidence bands.",
        "r_packages": ["survival", "survminer"],
    },
    "grouped_bar_chart": {
        "chart_type": "grouped_bar_chart",
        "ggplot2_geom": ["geom_col"],
        "description": "Proportional comparison of categorical outcomes between groups.",
    },
    "histogram_with_density_overlay": {
        "chart_type": "histogram_with_density_overlay",
        "ggplot2_geom": ["geom_histogram", "geom_density"],
        "description": "Distribution shape assessment for normality checking.",
    },
    "forest_plot": {
        "chart_type": "forest_plot",
        "ggplot2_geom": ["geom_pointrange"],
        "description": "Effect size summary with confidence intervals for multiple outcomes.",
    },
}


class VisualizationAgent(BaseAgent):
    """Scientific visualization specification agent.

    Selects chart types and generates ggplot2 script specifications from
    validated statistical results.  Never accesses raw patient data.

    Args:
        policy_engine: Enforces capability scope checks.
        schema_registry: Validates input and output payloads.
        audit_service: Records execution outcomes.
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        schema_registry: SchemaRegistry,
        audit_service: AuditService,
    ) -> None:
        super().__init__(policy_engine, schema_registry, audit_service)

    @property
    def agent_id(self) -> str:
        return "visualization"

    @property
    def input_schema_ref(self) -> str:
        return "cie://schemas/analysis-request.schema.json"

    @property
    def output_schema_ref(self) -> str:
        return "cie://schemas/visualization-plan.schema.json"

    @property
    def required_scopes(self) -> list[CapabilityScope]:
        return [
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ]

    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        """Select chart types and produce visualization specifications.

        Steps:
          1. VZ-001: Verify statistical_results present (no raw data path).
          2. Extract intent_object and statistical_results.
          3. Select chart type (VZ-002).
          4. Build figure specification with caption_draft (VZ-004).
          5. Declare ggplot2 R script specification.
          6. Return AgentOutput.
        """
        payload = agent_input.payload

        # Step 1 — VZ-001: statistical_results must be present
        statistical_results = payload.get("statistical_results")
        if not statistical_results:
            raise AgentError(
                "MISSING_STATISTICAL_INPUT: Visualization requires validated "
                "statistical results from the Statistics Agent.",
                agent_id=self.agent_id,
            )

        # Step 2 — extract context
        intent_obj: dict = payload.get("intent_object") or {}
        objective: str = intent_obj.get("objective", "")
        outcome_type: str = intent_obj.get("outcome_type", "unknown")
        paired: bool | None = intent_obj.get("paired")
        journal_guidelines: dict = payload.get("journal_figure_guidelines") or {}

        # Step 3 — chart type selection (VZ-002)
        chart_key = self._select_chart_type(objective, outcome_type, paired)
        chart_base = _CHART_SPECS.get(chart_key, _CHART_SPECS["box_plot_with_jitter"])

        # Step 4 — build figure specification (VZ-004: caption required)
        now_iso = datetime.now(timezone.utc).isoformat()
        figure_id = f"fig_{chart_base['chart_type']}_001"
        figure_spec = {
            "figure_id": figure_id,
            "chart_type": chart_base["chart_type"],
            "ggplot2_geoms": chart_base["ggplot2_geom"],
            "description": chart_base["description"],
            "color_palette": OKABE_ITO_PALETTE,  # VZ-003
            "palette_name": "Okabe-Ito",
            "output_standards": {
                "resolution_dpi": journal_guidelines.get("resolution_dpi", 300),
                "format": journal_guidelines.get("format", "pdf"),
                "font_family": journal_guidelines.get("font_family", "Helvetica Neue"),
                "base_font_size_pt": 10,
                "figure_width_mm": 180,
                "figure_height_mm": 120,
            },
            "caption_draft": {
                "figure_label": f"Figure 1",
                "description": chart_base["description"],
                "statistical_annotations": [
                    "p-value",
                    "effect size",
                    "95% confidence interval",
                    "n per group",
                ],
                "note": "Values are mean ± SD unless otherwise stated.",
            },
        }

        # Step 5 — R script specification
        r_packages = list(chart_base.get("r_packages", ["ggplot2"]))
        if "ggplot2" not in r_packages:
            r_packages.insert(0, "ggplot2")

        output_payload: dict = {
            "execution_id": agent_input.execution_id,
            "visualization_specifications": [figure_spec],
            "r_script_specification": {
                "primary_function": "ggplot",
                "packages_required": r_packages,
                "theme": "theme_bw",
                "seed": 42,
            },
            "figure_manifest": [
                {
                    "figure_id": figure_id,
                    "expected_filename": f"{figure_id}.pdf",
                    "format": "pdf",
                    "resolution_dpi": 300,
                }
            ],
            "caption_drafts": [figure_spec["caption_draft"]],
            "created_at": now_iso,
        }

        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status="success",
            output_payload=output_payload,
            output_schema_ref=self.output_schema_ref,
        )

    def _select_chart_type(
        self,
        objective: str,
        outcome_type: str,
        paired: bool | None,
    ) -> str:
        """Map study objective to a chart type key (VZ-002).

        Selection is driven by data characteristics, not aesthetics.
        """
        if objective == "survival_analysis" or outcome_type == "survival":
            return "kaplan_meier_curve"

        if objective in {"correlation_analysis", "regression_analysis"}:
            return "scatter_plot_with_regression_line"

        if outcome_type in {
            "categorical_binary", "categorical_nominal", "categorical_ordinal"
        }:
            return "grouped_bar_chart"

        if objective in {"descriptive_only"}:
            return "histogram_with_density_overlay"

        # Continuous group comparison
        if paired:
            return "slopegraph"

        return "box_plot_with_jitter"
