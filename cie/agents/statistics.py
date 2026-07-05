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

import json
import logging
import re
from datetime import datetime, timezone

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.audit import AuditService
from cie.core.exceptions import AgentError
from cie.cache.r_script_cache import RScriptCache
from cie.core.llm_client import LLMClient, LLMError
from cie.knowledge.reference_library import MarkdownReferenceLibrary
from cie.schemas.validator import SchemaRegistry
from cie.security.capability_token import CapabilityScope
from cie.security.policy_engine import PolicyEngine
from cie.skills.loader import SkillLoader

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# R-script generation system prompt (knowledge-grounded LLM codegen)
# ---------------------------------------------------------------------------

_R_GEN_SYSTEM_PROMPT = """\
You are a biostatistics R programmer for the CIE Platform. Produce a single,
complete, runnable R script that performs the requested statistical analysis.

STRICT REQUIREMENTS:
1. Output ONLY R code inside one ```r ... ``` fenced block. No prose outside it.
2. Read the dataset from dataset.csv inside the workspace directory:
       data <- read.csv(file.path(Sys.getenv("WORKSPACE_DIR"), "dataset.csv"),
                        stringsAsFactors = FALSE)
   Never hard-code an absolute path and never fabricate data.
3. Use the column names given in dataset_columns. If the exact grouping/outcome
   columns are ambiguous, select them defensively and comment your choice.
4. set.seed(42) for reproducibility before any stochastic step.
5. Ground your implementation in the provided KNOWLEDGE REFERENCE PATTERNS
   (correct function arguments, result extraction, effect sizes). You MAY add
   steps not covered by the references when they are statistically necessary
   (e.g. assumption checks), but never contradict the references.
6. Compute and print: the test statistic, p-value, effect size (with its name),
   and 95% confidence interval where applicable.
7. Write a machine-readable result as JSON to file.path(Sys.getenv("OUTPUT_DIR"),
   "result.json"). Prefer jsonlite::toJSON(..., auto_unbox=TRUE) guarded by
   requireNamespace; otherwise emit valid JSON manually. The JSON object MUST
   use exactly these keys where applicable (downstream agents read them):
     - method_id           (string, the analysis method id)
     - test_name           (string, human-readable test name)
     - test_statistic      (number)
     - df                  (number or null)
     - p_value             (number)
     - effect_size         (number)
     - effect_size_measure (string, e.g. "Cohen's d")
     - ci_lower            (number)
     - ci_upper            (number)
     - sample_size         (integer, total n analysed)
     - group_summaries     (optional object: per-group n/mean/sd)
8. Wrap the analysis in tryCatch so failures print a clear message and quit with
   a non-zero status.
"""

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

# ---------------------------------------------------------------------------
# Method-ID → Skill-ID mapping (ADR-0002: user/ > core/ priority via SkillLoader)
# ---------------------------------------------------------------------------

_METHOD_TO_SKILL_ID: dict[str, str] = {
    "independent_samples_t_test": "statistics/t-test",
    "mann_whitney_u_test": "statistics/t-test",
    "paired_t_test": "statistics/t-test",
    "wilcoxon_signed_rank_test": "statistics/t-test",
    "one_way_anova": "statistics/anova",
    "kruskal_wallis_test": "statistics/anova",
    "pearson_correlation": "statistics/correlation",
    "spearman_rank_correlation": "statistics/correlation",
    "multiple_linear_regression": "statistics/regression",
    "logistic_regression": "statistics/regression",
    "kaplan_meier_estimator": "statistics/survival",
    "chi_square_test_or_fishers_exact": "statistics/t-test",
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
        llm_client: LLMClient | None = None,
        reference_library: MarkdownReferenceLibrary | None = None,
        script_cache: RScriptCache | None = None,
        skill_loader: SkillLoader | None = None,
    ) -> None:
        super().__init__(policy_engine, schema_registry, audit_service)
        # When llm_client is None the agent falls back to specification-only
        # output (no executable R script) — preserves existing unit tests.
        self._llm_client = llm_client
        self._reference_library = reference_library
        self._script_cache = script_cache
        self._skill_loader = skill_loader

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

        # decision_assumption routed to the nonparametric fallback branch
        # (spec/workflow.yaml rules.normality=false → select_nonparametric):
        # force a nonparametric method regardless of the original assumption.
        if agent_input.node_id == "select_nonparametric":
            distribution = "non_parametric"

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

        # Step 6 — generate the executable R script via the LLM, grounded in the
        # knowledge reference library (RAG). Falls back to specification-only
        # (r_script=None) when no LLM client is configured.
        r_script, provenance = await self._generate_r_script(
            method=method, intent_obj=intent_obj, payload=payload
        )
        output_payload["r_script"] = r_script
        output_payload["r_script_provenance"] = provenance

        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status="success",
            output_payload=output_payload,
            output_schema_ref=self.output_schema_ref,
        )

    # ------------------------------------------------------------------
    # LLM R-script generation (knowledge-grounded, cached)
    # ------------------------------------------------------------------

    async def _generate_r_script(
        self, method: dict, intent_obj: dict, payload: dict
    ) -> tuple[str | None, dict]:
        """Generate an executable R script for *method* via the LLM.

        The prompt is grounded in the retrieved knowledge reference patterns
        (RAG) but the LLM may also produce steps not covered by the knowledge.
        Structurally-identical analyses are served from the RScriptCache to
        avoid re-spending tokens.

        Returns:
            (r_script, provenance). ``r_script`` is None when no LLM client is
            available (specification-only fallback).
        """
        provenance: dict = {
            "llm_generated": False,
            "from_cache": False,
            "knowledge_references": [],
        }

        if self._llm_client is None:
            provenance["reason"] = "no_llm_client_configured"
            return None, provenance

        column_metadata = (
            payload.get("dataset_structural_metadata")
            or payload.get("variable_metadata")
            or {}
        )
        column_signature = json.dumps(column_metadata, sort_keys=True, ensure_ascii=False)

        # 1. Cache lookup (token-saving for common analyses)
        signature = ""
        if self._script_cache is not None:
            signature = RScriptCache.make_signature(
                method["method_id"], intent_obj, column_signature
            )
            cached = self._script_cache.get(
                signature,
                provider=self._llm_client.provider,
                model=self._llm_client.model,
            )
            if cached is not None:
                provenance["llm_generated"] = True
                provenance["from_cache"] = True
                return cached, provenance

        # 2. Retrieve knowledge references (RAG grounding)
        references: list = []
        if self._reference_library is not None:
            query_terms = [
                method["method_id"],
                method.get("r_function", ""),
                intent_obj.get("objective", ""),
                intent_obj.get("outcome_type", ""),
            ]
            query_terms += [str(pkg) for pkg in method.get("r_packages", [])]
            references = self._reference_library.retrieve(query_terms, top_k=2)
            provenance["knowledge_references"] = [r.title for r in references]

        # 3. Build prompt (optionally grounded with SKILL.md instructions)
        skill_id = _METHOD_TO_SKILL_ID.get(method["method_id"])
        skill_block = (
            self._skill_loader.get_skill_prompt_block(skill_id)
            if self._skill_loader is not None and skill_id
            else ""
        )
        system_prompt = _R_GEN_SYSTEM_PROMPT + skill_block
        user_message = self._build_r_gen_user_message(
            method, intent_obj, column_metadata, references
        )
        try:
            raw = await self._llm_client.complete(system_prompt, user_message)
        except LLMError as exc:
            _log.warning("R script LLM generation failed: %s", exc)
            provenance["reason"] = f"llm_error: {exc}"
            return None, provenance

        r_script = self._extract_r_code(raw)
        if not r_script:
            provenance["reason"] = "empty_or_unparsable_llm_response"
            return None, provenance

        provenance["llm_generated"] = True

        # 4. Store in cache for reuse
        if self._script_cache is not None and signature:
            self._script_cache.put(
                signature,
                r_script,
                provider=self._llm_client.provider,
                model=self._llm_client.model,
                method_id=method["method_id"],
            )

        return r_script, provenance

    @staticmethod
    def _build_r_gen_user_message(
        method: dict, intent_obj: dict, column_metadata: dict, references: list
    ) -> str:
        """Assemble the user turn for R-script generation."""
        reference_block = "\n\n".join(
            f"### Reference: {r.title}\n{r.excerpt()}" for r in references
        ) or "(no matching reference documents found)"

        request = {
            "selected_method": {
                "method_id": method["method_id"],
                "r_function": method.get("r_function"),
                "r_packages": method.get("r_packages", []),
                "effect_size_measure": method.get("effect_size_measure"),
            },
            "intent_object": {
                "objective": intent_obj.get("objective"),
                "outcome_type": intent_obj.get("outcome_type"),
                "paired": intent_obj.get("paired"),
                "outcome_variables": intent_obj.get("outcome_variables", []),
                "predictor_variables": intent_obj.get("predictor_variables", []),
                "distribution_assumptions": intent_obj.get("distribution_assumptions"),
            },
            "dataset_columns": column_metadata,
        }
        return (
            "Generate a complete, runnable R script for the analysis below.\n\n"
            "=== ANALYSIS REQUEST ===\n"
            f"{json.dumps(request, ensure_ascii=False, indent=2)}\n\n"
            "=== KNOWLEDGE REFERENCE PATTERNS (ground your script in these) ===\n"
            f"{reference_block}\n"
        )

    @staticmethod
    def _extract_r_code(raw_text: str) -> str | None:
        """Extract R source from an LLM response.

        Prefers a fenced ```r ... ``` block; otherwise returns the whole text
        if it looks like R, else None.
        """
        match = re.search(r"```(?:r|R)?\s*\n(.*?)```", raw_text, re.DOTALL)
        if match:
            code = match.group(1).strip()
            return code or None
        text = raw_text.strip()
        return text or None

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
