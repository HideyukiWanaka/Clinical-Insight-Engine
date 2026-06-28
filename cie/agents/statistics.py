"""CIE Platform — Statistics Agent.

Selects statistically appropriate methods, produces an analysis plan, and
specifies the R script template.  This agent NEVER executes code — execution
belongs to the Runtime Agent.

Key rules (agents/statistics.yaml):
  ST-001  Immediately blocked if data_quality_report.quality_gate_passed=False.
  ST-002  Every selected method includes a justification field.
  ST-003  Assumption checks are declared when metadata alone is insufficient.
  ST-004  Effect sizes and CIs always reported alongside p-values.
  ST-005  Multiple comparison correction applied when >1 hypothesis tested.
  ST-006  Schema-conforming JSON output only.
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
# Method catalogue (statistics.yaml method_selection_framework)
# ---------------------------------------------------------------------------

_METHODS: dict[str, dict] = {
    "independent_samples_t_test": {
        "method_id": "independent_samples_t_test",
        "name": "Independent Samples t-test",
        "r_function": "t.test",
        "r_packages": ["base"],
        "assumption": "normal",
        "effect_size_measure": "Cohen's d",
        "effect_size_benchmark": "Small=0.2, Medium=0.5, Large=0.8",
        "justification_template": (
            "Continuous outcome, two independent groups, parametric assumption."
        ),
    },
    "mann_whitney_u_test": {
        "method_id": "mann_whitney_u_test",
        "name": "Mann-Whitney U Test",
        "r_function": "wilcox.test",
        "r_packages": ["base"],
        "assumption": "non_parametric",
        "effect_size_measure": "rank-biserial r",
        "effect_size_benchmark": "Small=0.1, Medium=0.3, Large=0.5",
        "justification_template": (
            "Continuous outcome, two independent groups, non-parametric."
        ),
    },
    "paired_t_test": {
        "method_id": "paired_t_test",
        "name": "Paired Samples t-test",
        "r_function": "t.test",
        "r_packages": ["base"],
        "assumption": "normal",
        "effect_size_measure": "Cohen's dz",
        "effect_size_benchmark": "Small=0.2, Medium=0.5, Large=0.8",
        "justification_template": (
            "Continuous outcome, paired/repeated-measures, parametric."
        ),
    },
    "wilcoxon_signed_rank_test": {
        "method_id": "wilcoxon_signed_rank_test",
        "name": "Wilcoxon Signed-Rank Test",
        "r_function": "wilcox.test",
        "r_packages": ["base"],
        "assumption": "non_parametric",
        "effect_size_measure": "rank-biserial r",
        "effect_size_benchmark": "Small=0.1, Medium=0.3, Large=0.5",
        "justification_template": (
            "Continuous outcome, paired/repeated-measures, non-parametric."
        ),
    },
    "one_way_anova": {
        "method_id": "one_way_anova",
        "name": "One-Way ANOVA",
        "r_function": "aov",
        "r_packages": ["base"],
        "assumption": "normal",
        "effect_size_measure": "eta-squared",
        "effect_size_benchmark": "Small=0.01, Medium=0.06, Large=0.14",
        "justification_template": (
            "Continuous outcome, >2 independent groups, parametric."
        ),
    },
    "kruskal_wallis_test": {
        "method_id": "kruskal_wallis_test",
        "name": "Kruskal-Wallis Test",
        "r_function": "kruskal.test",
        "r_packages": ["base"],
        "assumption": "non_parametric",
        "effect_size_measure": "eta-squared H",
        "effect_size_benchmark": "Small=0.01, Medium=0.06, Large=0.14",
        "justification_template": (
            "Continuous outcome, >2 independent groups, non-parametric."
        ),
    },
    "chi_square_test_or_fishers_exact": {
        "method_id": "chi_square_test_or_fishers_exact",
        "name": "Chi-Square or Fisher's Exact Test",
        "r_function": "chisq.test",
        "r_packages": ["base"],
        "assumption": "categorical",
        "effect_size_measure": "Cramér's V",
        "effect_size_benchmark": "Small=0.1, Medium=0.3, Large=0.5",
        "justification_template": (
            "Categorical outcome, group comparison."
        ),
    },
    "logistic_regression": {
        "method_id": "logistic_regression",
        "name": "Logistic Regression",
        "r_function": "glm",
        "r_packages": ["base"],
        "assumption": "categorical",
        "effect_size_measure": "odds ratio",
        "effect_size_benchmark": "OR: Small=1.5, Medium=2.5, Large=4.3",
        "justification_template": (
            "Binary outcome, regression analysis with predictors."
        ),
    },
    "kaplan_meier_estimator": {
        "method_id": "kaplan_meier_estimator",
        "name": "Kaplan-Meier Estimator + Log-Rank Test",
        "r_function": "survfit",
        "r_packages": ["survival"],
        "assumption": "survival",
        "effect_size_measure": "hazard ratio",
        "effect_size_benchmark": "HR departure from 1.0",
        "justification_template": (
            "Survival/time-to-event outcome."
        ),
    },
    "pearson_correlation": {
        "method_id": "pearson_correlation",
        "name": "Pearson Correlation",
        "r_function": "cor.test",
        "r_packages": ["base"],
        "assumption": "normal",
        "effect_size_measure": "r",
        "effect_size_benchmark": "Small=0.1, Medium=0.3, Large=0.5",
        "justification_template": (
            "Continuous outcome, correlation analysis, parametric."
        ),
    },
    "spearman_rank_correlation": {
        "method_id": "spearman_rank_correlation",
        "name": "Spearman Rank Correlation",
        "r_function": "cor.test",
        "r_packages": ["base"],
        "assumption": "non_parametric",
        "effect_size_measure": "rho",
        "effect_size_benchmark": "Small=0.1, Medium=0.3, Large=0.5",
        "justification_template": (
            "Correlation analysis, non-parametric."
        ),
    },
    "multiple_linear_regression": {
        "method_id": "multiple_linear_regression",
        "name": "Multiple Linear Regression",
        "r_function": "lm",
        "r_packages": ["base"],
        "assumption": "normal",
        "effect_size_measure": "R-squared",
        "effect_size_benchmark": "Small=0.02, Medium=0.13, Large=0.26",
        "justification_template": (
            "Continuous outcome, regression with multiple predictors."
        ),
    },
}

_ASSUMPTION_CHECKS_BY_METHOD: dict[str, list[dict]] = {
    "independent_samples_t_test": [
        {
            "check_id": "normality_shapiro_wilk",
            "description": "Shapiro-Wilk normality test per group.",
            "r_function": "shapiro.test",
            "on_violation": "Switch to mann_whitney_u_test",
        },
        {
            "check_id": "levene_homoscedasticity",
            "description": "Levene's test for equality of variances.",
            "r_function": "leveneTest",
            "on_violation": "Use Welch correction (var.equal=FALSE, default in t.test)",
        },
    ],
    "paired_t_test": [
        {
            "check_id": "normality_difference_scores",
            "description": "Shapiro-Wilk normality test on difference scores.",
            "r_function": "shapiro.test",
            "on_violation": "Switch to wilcoxon_signed_rank_test",
        }
    ],
    "one_way_anova": [
        {
            "check_id": "normality_shapiro_wilk",
            "description": "Shapiro-Wilk normality test per group.",
            "r_function": "shapiro.test",
            "on_violation": "Switch to kruskal_wallis_test",
        },
        {
            "check_id": "bartlett_homoscedasticity",
            "description": "Bartlett's test for equality of variances.",
            "r_function": "bartlett.test",
            "on_violation": "Use Welch ANOVA: oneway.test(var.equal=FALSE)",
        },
    ],
    "pearson_correlation": [
        {
            "check_id": "bivariate_normality",
            "description": "Visual and Shapiro-Wilk check for bivariate normality.",
            "r_function": "shapiro.test",
            "on_violation": "Switch to spearman_rank_correlation",
        }
    ],
}


class StatisticsAgent(BaseAgent):
    """Statistical method selection and analysis plan generation agent.

    Does NOT execute R code — it produces a declarative ``analysis_plan``
    and ``r_script_specification`` that the Runtime Agent consumes.

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
        return "statistics"

    @property
    def input_schema_ref(self) -> str:
        return "cie://schemas/analysis-request.schema.json"

    @property
    def output_schema_ref(self) -> str:
        return "cie://schemas/analysis-plan.schema.json"

    @property
    def required_scopes(self) -> list[CapabilityScope]:
        return [
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.R_CODE_GENERATE_TEMPLATE,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ]

    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        """Select methods, generate analysis plan, and specify R script.

        Steps:
          1. ST-001: Block if data quality gate failed.
          2. Extract intent_object from payload.
          3. Select primary statistical method.
          4. Declare assumption checks (ST-003).
          5. Build output payload (ST-002: full justification per method).
          6. Return AgentOutput.
        """
        payload = agent_input.payload

        # Step 1 — ST-001: quality gate check
        dq_report = payload.get("data_quality_report") or {}
        if not dq_report.get("quality_gate_passed", False):
            raise AgentError(
                "QUALITY_GATE_BLOCKED: Statistical analysis cannot proceed — "
                "data quality gate has not passed.",
                agent_id=self.agent_id,
            )

        # Step 2 — extract intent object
        intent_obj: dict = payload.get("intent_object") or {}
        objective: str = intent_obj.get("objective", "")
        outcome_type: str = intent_obj.get("outcome_type", "unknown")
        n_groups: int | None = intent_obj.get("n_groups_estimate")
        paired: bool | None = intent_obj.get("paired")
        distribution: str = intent_obj.get("distribution_assumptions", "unknown")

        # Step 3 — method selection
        method = self._select_method(objective, outcome_type, n_groups, paired, distribution)
        method_with_justification = {
            **method,
            "justification": (
                f"{method['justification_template']} "
                f"objective={objective!r}, outcome_type={outcome_type!r}, "
                f"n_groups={n_groups}, paired={paired}, "
                f"distribution={distribution!r}."
            ),
        }

        # Step 4 — assumption checks (ST-003)
        assumption_checks = _ASSUMPTION_CHECKS_BY_METHOD.get(method["method_id"], [])

        # Step 5 — assemble output payload (ST-004: effect sizes required)
        now_iso = datetime.now(timezone.utc).isoformat()
        output_payload: dict = {
            "execution_id": agent_input.execution_id,
            "selected_methods": [method_with_justification],
            "analysis_plan": {
                "method_id": method["method_id"],
                "primary_test": method["method_id"],
                "effect_size_measure": method.get("effect_size_measure"),
                "confidence_level": 0.95,
                "multiple_comparison_correction": (
                    "bonferroni" if len(intent_obj.get("outcome_variables", [])) > 1 else None
                ),
            },
            "r_script_specification": {
                "primary_function": method.get("r_function", ""),
                "packages_required": method.get("r_packages", []),
                "seed": 42,
                "seed_rationale": "STAT-005-A reproducibility requirement",
            },
            "assumption_checks_required": assumption_checks,
            "expected_output_schema": {
                "test_statistic": True,
                "p_value": True,
                "effect_size": True,
                "confidence_interval_95": True,
                "sample_size_per_group": True,
            },
            "interpretation_guidelines": {
                "effect_size_benchmark": method.get("effect_size_benchmark", ""),
                "reporting_standard": "APA 7th edition",
                "p_value_threshold": 0.05,
            },
            "created_at": now_iso,
        }

        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status="success",
            output_payload=output_payload,
            output_schema_ref=self.output_schema_ref,
        )

    def _select_method(
        self,
        objective: str,
        outcome_type: str,
        n_groups: int | None,
        paired: bool | None,
        distribution: str,
    ) -> dict:
        """Map intent_object properties to a method from the catalogue.

        Follows statistics.yaml method_selection_framework.  Falls back to
        mann_whitney_u_test (safest non-parametric default) when no exact
        match is found so the agent always produces a result (ST-003 declares
        assumption checks when the match is ambiguous).
        """
        is_parametric = distribution == "assumed_normal"

        if objective == "survival_analysis" or outcome_type == "survival":
            return _METHODS["kaplan_meier_estimator"]

        if objective in {"correlation_analysis"}:
            return (
                _METHODS["pearson_correlation"]
                if is_parametric
                else _METHODS["spearman_rank_correlation"]
            )

        if objective in {"regression_analysis"}:
            if outcome_type in {"categorical_binary"}:
                return _METHODS["logistic_regression"]
            return _METHODS["multiple_linear_regression"]

        if outcome_type in {
            "categorical_binary", "categorical_nominal", "categorical_ordinal"
        }:
            return _METHODS["chi_square_test_or_fishers_exact"]

        # Continuous outcome — group comparison
        groups = n_groups if n_groups is not None else 2
        if paired:
            return (
                _METHODS["paired_t_test"]
                if is_parametric
                else _METHODS["wilcoxon_signed_rank_test"]
            )
        if groups > 2:
            return (
                _METHODS["one_way_anova"]
                if is_parametric
                else _METHODS["kruskal_wallis_test"]
            )
        # Default: two-group independent comparison
        return (
            _METHODS["independent_samples_t_test"]
            if is_parametric
            else _METHODS["mann_whitney_u_test"]
        )
