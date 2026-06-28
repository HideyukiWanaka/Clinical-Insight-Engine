"""CIE Platform — Statistical Validity & Reproducibility Evaluator.

Implements the Statistical evaluation dimension (weight_pct=35).
Checks ST-001 through ST-007 as defined in evaluation/statistical.yaml
and the prompt specification.

Architecture note:
  This evaluator is read-only. It never modifies artifacts.
  ST-003 (post-hoc) requires omnibus p-value consistency check.
  ST-005 (paired design) checks for inappropriate independent-samples test use.
"""

from __future__ import annotations

import re

from cie.evaluation.base import (
    BaseEvaluator,
    CheckResult,
    DimensionScore,
    EvaluationDimension,
)

# Independent-samples tests that are invalid for paired designs
_INDEPENDENT_TESTS = frozenset({
    "welch_t_test",
    "mann_whitney_u",
    "independent_t_test",
    "t_test_independent",
    "two_sample_t_test",
})

# Valid Cohen's d interpretation thresholds (per statistical.yaml and convention)
_COHEN_D_THRESHOLDS: list[tuple[float, str]] = [
    (0.2, "negligible"),
    (0.5, "small"),
    (0.8, "medium"),
]


def _cohen_d_label(value: float) -> str:
    """Return the expected Cohen's d interpretation label for a given value."""
    for threshold, label in _COHEN_D_THRESHOLDS:
        if value < threshold:
            return label
    return "large"


class StatisticalEvaluator(BaseEvaluator):
    """Statistical validity and reproducibility evaluator.

    Dimension: STATISTICAL (weight_pct = 35).

    Runs checks ST-001 through ST-007 against the R script content,
    assumption report, and execution result artifacts.

    Expected artifact keys:
        - "r_script_content" (str): Raw R script text.
        - "execution_result" (dict): Output of r_executor.RExecutor.
            May contain:
                primary_result.p_value (float)
                effect_size.value (float)
                effect_size.interpretation (str)
                posthoc_performed (bool | None)
                omnibus_p_value (float | None)
                r_packages (list[dict] | None)
                dataset_hash (str | None)
        - "assumption_report" (dict): Assumption check results.
            May contain:
                normality_results (list)
                tests_performed (bool)
        - "analysis_plan" (dict): From Statistics Agent.
            May contain:
                design (str)          # "paired" | "independent"
                n_hypotheses (int)
                multiple_correction (str | None)
                expected_cells (list[dict] | None)  # For Fisher exact check
    """

    @property
    def dimension(self) -> EvaluationDimension:
        """Returns STATISTICAL."""
        return EvaluationDimension.STATISTICAL

    @property
    def weight_pct(self) -> int:
        """Weight 35% per evaluation/statistical.yaml."""
        return 35

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def evaluate(self, artifacts: dict) -> DimensionScore:
        """Run ST-001 through ST-007 and return a DimensionScore.

        Args:
            artifacts: Artifact dict with keys "r_script_content",
                "execution_result", "assumption_report", "analysis_plan".

        Returns:
            DimensionScore with score in [0.0, 100.0] and all check details.
        """
        r_script: str = artifacts.get("r_script_content") or ""
        execution_result: dict = artifacts.get("execution_result") or {}
        assumption_report: dict = artifacts.get("assumption_report") or {}
        analysis_plan: dict = artifacts.get("analysis_plan") or {}

        primary = execution_result.get("primary_result") or {}
        effect = execution_result.get("effect_size") or {}

        checks: list[CheckResult] = [
            self._check_st001(r_script),
            self._check_st002(assumption_report),
            self._check_st003(execution_result),
            self._check_st004(effect),
            self._check_st005(analysis_plan, execution_result),
            self._check_st006(analysis_plan, execution_result),
            self._check_st007(analysis_plan, execution_result),
        ]

        score = self._pass_score(checks)
        critical_failure = any(
            c.severity == "critical" and not c.passed for c in checks
        )

        return DimensionScore(
            dimension=self.dimension,
            score=score,
            weight_pct=self.weight_pct,
            check_results=checks,
            critical_failure=critical_failure,
        )

    # ------------------------------------------------------------------
    # Individual checks (ST-001 … ST-007)
    # ------------------------------------------------------------------

    def _check_st001(self, r_script: str) -> CheckResult:
        """ST-001 (critical): set.seed(42) must exist in the R script.

        Source: statistical.yaml STAT-005-A (Reproducibility — random seed).
        Prompt spec: ST-001.
        """
        if not r_script:
            return CheckResult(
                check_id="ST-001",
                dimension=self.dimension,
                passed=False,
                severity="critical",
                message="ST-001: r_script_content is empty or missing.",
            )

        # Accept set.seed() with any seed value, but must be present
        has_seed = bool(re.search(r"set\.seed\s*\(", r_script))
        # Stricter check: specifically set.seed(42) per spec
        has_seed_42 = bool(re.search(r"set\.seed\s*\(\s*42\s*\)", r_script))

        passed = has_seed_42
        if has_seed and not has_seed_42:
            message = (
                "ST-001: set.seed() found but not set.seed(42). "
                "CIE standard requires set.seed(42) for cross-execution reproducibility."
            )
        elif passed:
            message = "ST-001: set.seed(42) found in R script."
        else:
            message = "ST-001: set.seed(42) is missing from R script. Reproducibility cannot be guaranteed."

        return CheckResult(
            check_id="ST-001",
            dimension=self.dimension,
            passed=passed,
            severity="critical",
            message=message,
            actual_value="set.seed(42) present" if passed else "not found",
            expected_value="set.seed(42)",
        )

    def _check_st002(self, assumption_report: dict) -> CheckResult:
        """ST-002 (critical): assumption checks must have been performed.

        Source: statistical.yaml STAT-002-A (Assumption Check Validity).
        Prompt spec: ST-002.
        """
        tests_performed = assumption_report.get("tests_performed")
        normality_results = assumption_report.get("normality_results")

        if not assumption_report:
            return CheckResult(
                check_id="ST-002",
                dimension=self.dimension,
                passed=False,
                severity="critical",
                message="ST-002: assumption_report is missing from artifacts.",
            )

        if not tests_performed:
            return CheckResult(
                check_id="ST-002",
                dimension=self.dimension,
                passed=False,
                severity="critical",
                message="ST-002: tests_performed=False; assumption checks were not executed.",
            )

        has_normality = bool(normality_results)
        message = (
            "ST-002: Assumption checks were performed and normality_results are present."
            if has_normality
            else (
                "ST-002: tests_performed=True but normality_results is empty. "
                "Assumption checks may be incomplete."
            )
        )

        return CheckResult(
            check_id="ST-002",
            dimension=self.dimension,
            passed=has_normality,
            severity="critical",
            message=message,
            actual_value=f"normality_results count: {len(normality_results) if normality_results else 0}",
            expected_value=">= 1 normality result",
        )

    def _check_st003(self, execution_result: dict) -> CheckResult:
        """ST-003 (critical): post-hoc tests run only when omnibus p < 0.05.

        Source: statistical.yaml STAT-001-C (multiple comparison declaration).
        Prompt spec: ST-003.

        Logic:
          - posthoc_performed=True  and omnibus_p >= 0.05 → FAIL (post-hoc without significance)
          - posthoc_performed=False and omnibus_p < 0.05  → advisory (missed opportunity, not critical)
          - posthoc_performed=None                        → skip check (no multi-group comparison)
          - posthoc_performed=True  and omnibus_p < 0.05  → PASS
        """
        posthoc = execution_result.get("posthoc_performed")
        omnibus_p = execution_result.get("omnibus_p_value")

        if posthoc is None:
            return CheckResult(
                check_id="ST-003",
                dimension=self.dimension,
                passed=True,
                severity="critical",
                message="ST-003: posthoc_performed is None; multi-group post-hoc check not applicable.",
            )

        if omnibus_p is None:
            # Post-hoc was performed but no omnibus p is recorded
            if posthoc:
                return CheckResult(
                    check_id="ST-003",
                    dimension=self.dimension,
                    passed=False,
                    severity="critical",
                    message=(
                        "ST-003: posthoc_performed=True but omnibus_p_value is missing. "
                        "Cannot verify consistency."
                    ),
                )
            return CheckResult(
                check_id="ST-003",
                dimension=self.dimension,
                passed=True,
                severity="critical",
                message="ST-003: posthoc_performed=False and omnibus_p_value not available; OK.",
            )

        omnibus_p_f = float(omnibus_p)

        if posthoc and omnibus_p_f >= 0.05:
            passed = False
            message = (
                f"ST-003: post-hoc tests were performed (posthoc_performed=True) "
                f"but omnibus p={omnibus_p_f:.4f} >= 0.05. "
                "Post-hoc testing without a significant omnibus result inflates Type I error."
            )
        elif not posthoc and omnibus_p_f < 0.05:
            # Not a critical failure — maybe user intentionally skipped
            passed = True
            message = (
                f"ST-003: omnibus p={omnibus_p_f:.4f} < 0.05 but post-hoc was not performed. "
                "Consider whether post-hoc comparisons are needed."
            )
        else:
            passed = True
            message = (
                f"ST-003: post-hoc consistency verified "
                f"(posthoc={posthoc}, omnibus_p={omnibus_p_f:.4f})."
            )

        return CheckResult(
            check_id="ST-003",
            dimension=self.dimension,
            passed=passed,
            severity="critical",
            message=message,
            actual_value=f"posthoc={posthoc}, omnibus_p={omnibus_p}",
            expected_value="post-hoc only when omnibus p < 0.05",
        )

    def _check_st004(self, effect: dict) -> CheckResult:
        """ST-004 (advisory): effect size interpretation label must match the value.

        Thresholds (Cohen's d convention):
          < 0.2  → "negligible"
          < 0.5  → "small"
          < 0.8  → "medium"
          >= 0.8 → "large"

        Source: statistical.yaml STAT-003-A (Result Completeness).
        Prompt spec: ST-004.
        """
        value = effect.get("value")
        interpretation = effect.get("interpretation")

        if value is None or interpretation is None:
            return CheckResult(
                check_id="ST-004",
                dimension=self.dimension,
                passed=True,  # advisory: skip if data unavailable
                severity="advisory",
                message="ST-004: effect_size.value or interpretation missing; check skipped.",
            )

        try:
            value_f = float(value)
        except (TypeError, ValueError):
            return CheckResult(
                check_id="ST-004",
                dimension=self.dimension,
                passed=False,
                severity="advisory",
                message=f"ST-004: effect_size.value={value!r} is not numeric.",
            )

        expected_label = _cohen_d_label(abs(value_f))  # Use absolute value
        passed = str(interpretation).lower() == expected_label

        message = (
            f"ST-004: effect_size.interpretation='{interpretation}' matches "
            f"expected='{expected_label}' for value={value_f:.4f}."
            if passed
            else (
                f"ST-004: effect_size.interpretation='{interpretation}' does not match "
                f"expected='{expected_label}' for value={value_f:.4f} "
                f"(|d|={abs(value_f):.4f})."
            )
        )

        return CheckResult(
            check_id="ST-004",
            dimension=self.dimension,
            passed=passed,
            severity="advisory",
            message=message,
            actual_value=f"'{interpretation}' (value={value_f:.4f})",
            expected_value=f"'{expected_label}'",
        )

    def _check_st005(
        self, analysis_plan: dict, execution_result: dict
    ) -> CheckResult:
        """ST-005 (critical): paired design must not use independent-samples tests.

        Source: statistical.yaml STAT-002-A, prompt spec ST-005.
        """
        design = analysis_plan.get("design", "")
        method_used: str = execution_result.get("method_used", "")

        if str(design).lower() != "paired":
            return CheckResult(
                check_id="ST-005",
                dimension=self.dimension,
                passed=True,
                severity="critical",
                message=f"ST-005: design='{design}'; paired-design check not applicable.",
            )

        # design is "paired" — check that an independent-samples test was not used
        method_lower = method_used.lower().replace("-", "_").replace(" ", "_")
        used_independent = any(t in method_lower for t in _INDEPENDENT_TESTS)

        if used_independent:
            message = (
                f"ST-005: Paired design detected but independent-samples test "
                f"'{method_used}' was used. This violates the paired-design assumption "
                "and invalidates the analysis."
            )
        else:
            message = (
                f"ST-005: Paired design and method='{method_used}' are consistent."
            )

        return CheckResult(
            check_id="ST-005",
            dimension=self.dimension,
            passed=not used_independent,
            severity="critical",
            message=message,
            actual_value=f"design='{design}', method='{method_used}'",
            expected_value="paired-appropriate test (e.g. paired_t_test, wilcoxon_signed_rank)",
        )

    def _check_st006(
        self, analysis_plan: dict, execution_result: dict
    ) -> CheckResult:
        """ST-006 (advisory): Fisher exact test should be used for small expected cell counts.

        Triggered when analysis involves categorical variables with any expected
        cell count < 5. Checks whether the method_used indicates Fisher exact test.

        Source: statistical.yaml STAT-002-A (assumption checking).
        Prompt spec: ST-006.
        """
        expected_cells: list[dict] = analysis_plan.get("expected_cells") or []

        if not expected_cells:
            return CheckResult(
                check_id="ST-006",
                dimension=self.dimension,
                passed=True,
                severity="advisory",
                message="ST-006: No expected_cells declared; Fisher exact check not applicable.",
            )

        small_cells = [
            c for c in expected_cells
            if isinstance(c.get("expected_count"), (int, float))
            and float(c["expected_count"]) < 5
        ]

        if not small_cells:
            return CheckResult(
                check_id="ST-006",
                dimension=self.dimension,
                passed=True,
                severity="advisory",
                message="ST-006: All expected cell counts >= 5; chi-square is appropriate.",
            )

        method_used: str = execution_result.get("method_used", "")
        uses_fisher = "fisher" in method_used.lower()

        message = (
            f"ST-006: {len(small_cells)} cell(s) with expected count < 5 detected and "
            "Fisher's exact test was correctly applied."
            if uses_fisher
            else (
                f"ST-006: {len(small_cells)} cell(s) with expected count < 5 detected "
                f"but method='{method_used}' is not Fisher's exact test. "
                "Consider using Fisher's exact test for small expected counts."
            )
        )

        return CheckResult(
            check_id="ST-006",
            dimension=self.dimension,
            passed=uses_fisher,
            severity="advisory",
            message=message,
            actual_value=f"method='{method_used}', small_cells={len(small_cells)}",
            expected_value="fisher_exact when any expected cell count < 5",
        )

    def _check_st007(
        self, analysis_plan: dict, execution_result: dict
    ) -> CheckResult:
        """ST-007 (advisory): multiple testing correction applied when n_hypotheses > 1.

        Source: statistical.yaml STAT-001-C.
        Prompt spec: ST-007.
        """
        n_hypotheses = analysis_plan.get("n_hypotheses")
        multiple_correction = analysis_plan.get("multiple_correction")

        if n_hypotheses is None:
            return CheckResult(
                check_id="ST-007",
                dimension=self.dimension,
                passed=True,
                severity="advisory",
                message="ST-007: n_hypotheses not declared; multiple testing check skipped.",
            )

        try:
            n = int(n_hypotheses)
        except (TypeError, ValueError):
            return CheckResult(
                check_id="ST-007",
                dimension=self.dimension,
                passed=True,
                severity="advisory",
                message=f"ST-007: n_hypotheses={n_hypotheses!r} is not numeric; check skipped.",
            )

        if n <= 1:
            return CheckResult(
                check_id="ST-007",
                dimension=self.dimension,
                passed=True,
                severity="advisory",
                message=f"ST-007: n_hypotheses={n}; multiple testing correction not required.",
            )

        # Multiple hypotheses — correction should be declared
        has_correction = bool(multiple_correction and str(multiple_correction).strip())
        message = (
            f"ST-007: n_hypotheses={n} > 1 and multiple_correction='{multiple_correction}' is declared."
            if has_correction
            else (
                f"ST-007: n_hypotheses={n} > 1 but multiple_correction is not declared. "
                "Apply Bonferroni, Holm, or Benjamini-Hochberg correction."
            )
        )

        return CheckResult(
            check_id="ST-007",
            dimension=self.dimension,
            passed=has_correction,
            severity="advisory",
            message=message,
            actual_value=str(multiple_correction),
            expected_value="multiple_correction declared when n_hypotheses > 1",
        )
