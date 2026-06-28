"""CIE Platform — Correctness Evaluator.

Implements the Correctness evaluation dimension (weight_pct=40).
Checks CC-001 through CC-007 as defined in evaluation/correctness.yaml
and agents/reviewer.yaml (consistency_checks).

Architecture note:
  This evaluator is read-only. It never modifies artifacts.
  CC-006 logic branches on method_used to handle logistic vs. continuous
  outcomes correctly (IMPLEMENTATION GUIDE.md Section 2.1 / Phase 7 note).
"""

from __future__ import annotations

from cie.evaluation.base import (
    BaseEvaluator,
    CheckResult,
    DimensionScore,
    EvaluationDimension,
)


class CorrectnessEvaluator(BaseEvaluator):
    """Scientific correctness evaluator.

    Dimension: CORRECTNESS (weight_pct = 40).

    Runs checks CC-001 through CC-007 against the execution result,
    review report, and analysis plan artifacts.

    Expected artifact keys:
        - "execution_result" (dict): Output of r_executor.RExecutor.
            Must contain:
                primary_result.p_value (float)
                primary_result.ci_lower (float)
                primary_result.ci_upper (float)
                effect_size.value (float)
                effect_size.interpretation (str)
                method_used (str)
        - "review_report" (dict): Output of Reviewer Agent.
            Used for method_justification check.
        - "analysis_plan" (dict): Output of Statistics Agent.
            Must contain n_observations_expected (int or None).
    """

    @property
    def dimension(self) -> EvaluationDimension:
        """Returns CORRECTNESS."""
        return EvaluationDimension.CORRECTNESS

    @property
    def weight_pct(self) -> int:
        """Weight 40% per evaluation/correctness.yaml."""
        return 40

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def evaluate(self, artifacts: dict) -> DimensionScore:
        """Run CC-001 through CC-007 and return a DimensionScore.

        Args:
            artifacts: Artifact dict with keys "execution_result",
                "review_report", and "analysis_plan".

        Returns:
            DimensionScore with score in [0.0, 100.0] and all check details.
        """
        execution_result: dict = artifacts.get("execution_result") or {}
        review_report: dict = artifacts.get("review_report") or {}
        analysis_plan: dict = artifacts.get("analysis_plan") or {}

        primary = execution_result.get("primary_result") or {}
        effect = execution_result.get("effect_size") or {}
        method_used: str = execution_result.get("method_used", "")

        checks: list[CheckResult] = [
            self._check_cc001(primary),
            self._check_cc002(effect),
            self._check_cc003(primary, analysis_plan),
            self._check_cc004(primary),
            self._check_cc005(review_report),
            self._check_cc006(primary, method_used),
            self._check_cc007(effect),
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
    # Individual checks (CC-001 … CC-007)
    # ------------------------------------------------------------------

    def _check_cc001(self, primary: dict) -> CheckResult:
        """CC-001 (critical): p_value must be in [0.0, 1.0].

        Source: agents/reviewer.yaml CC-001
                evaluation/correctness.yaml COR-004 (result traceability)
        """
        p_value = primary.get("p_value")
        if p_value is None:
            passed = False
            message = "CC-001: p_value is missing from execution_result.primary_result."
        elif not isinstance(p_value, (int, float)):
            passed = False
            message = f"CC-001: p_value is not numeric (got {type(p_value).__name__})."
        else:
            passed = 0.0 <= float(p_value) <= 1.0
            message = (
                "CC-001: p_value is within valid range [0.0, 1.0]."
                if passed
                else f"CC-001: p_value={p_value} is outside valid range [0.0, 1.0]."
            )

        return CheckResult(
            check_id="CC-001",
            dimension=self.dimension,
            passed=passed,
            severity="critical",
            message=message,
            actual_value=str(p_value) if p_value is not None else None,
            expected_value="[0.0, 1.0]",
        )

    def _check_cc002(self, effect: dict) -> CheckResult:
        """CC-002 (critical): effect_size.value must be >= 0.0.

        Source: agents/reviewer.yaml CC-002
        """
        value = effect.get("value")
        if value is None:
            passed = False
            message = "CC-002: effect_size.value is missing from execution_result."
        elif not isinstance(value, (int, float)):
            passed = False
            message = f"CC-002: effect_size.value is not numeric (got {type(value).__name__})."
        else:
            passed = float(value) >= 0.0
            message = (
                "CC-002: effect_size.value is non-negative."
                if passed
                else f"CC-002: effect_size.value={value} is negative."
            )

        return CheckResult(
            check_id="CC-002",
            dimension=self.dimension,
            passed=passed,
            severity="critical",
            message=message,
            actual_value=str(value) if value is not None else None,
            expected_value=">= 0.0",
        )

    def _check_cc003(self, primary: dict, analysis_plan: dict) -> CheckResult:
        """CC-003 (critical): n_observations matches analysis_plan expected value (±5%).

        Source: agents/reviewer.yaml CC-003
        Tolerance: 5% relative to expected (IMPLEMENTATION GUIDE.md Phase 7).
        """
        n_actual = primary.get("n_observations")
        n_expected = analysis_plan.get("n_observations_expected")

        if n_actual is None:
            return CheckResult(
                check_id="CC-003",
                dimension=self.dimension,
                passed=False,
                severity="critical",
                message="CC-003: n_observations missing from execution_result.primary_result.",
            )

        if n_expected is None:
            # No expected value declared — treat as advisory pass
            return CheckResult(
                check_id="CC-003",
                dimension=self.dimension,
                passed=True,
                severity="critical",
                message="CC-003: n_observations_expected not declared in analysis_plan; check skipped.",
                actual_value=str(n_actual),
            )

        tolerance = abs(n_expected) * 0.05
        passed = abs(float(n_actual) - float(n_expected)) <= tolerance
        message = (
            f"CC-003: n_observations={n_actual} matches expected={n_expected} within 5%."
            if passed
            else (
                f"CC-003: n_observations={n_actual} deviates from expected={n_expected} "
                f"by more than 5% (tolerance={tolerance:.1f})."
            )
        )

        return CheckResult(
            check_id="CC-003",
            dimension=self.dimension,
            passed=passed,
            severity="critical",
            message=message,
            actual_value=str(n_actual),
            expected_value=f"{n_expected} ± 5%",
        )

    def _check_cc004(self, primary: dict) -> CheckResult:
        """CC-004 (advisory): CI width is rational — ci_upper > ci_lower.

        Source: agents/reviewer.yaml (derived from CC-006 direction check)
        """
        ci_lower = primary.get("ci_lower")
        ci_upper = primary.get("ci_upper")

        if ci_lower is None or ci_upper is None:
            return CheckResult(
                check_id="CC-004",
                dimension=self.dimension,
                passed=False,
                severity="advisory",
                message="CC-004: ci_lower or ci_upper missing from primary_result.",
            )

        passed = float(ci_upper) > float(ci_lower)
        message = (
            f"CC-004: CI [{ci_lower}, {ci_upper}] is valid (upper > lower)."
            if passed
            else f"CC-004: CI [{ci_lower}, {ci_upper}] is invalid (upper <= lower)."
        )

        return CheckResult(
            check_id="CC-004",
            dimension=self.dimension,
            passed=passed,
            severity="advisory",
            message=message,
            actual_value=f"[{ci_lower}, {ci_upper}]",
            expected_value="ci_upper > ci_lower",
        )

    def _check_cc005(self, review_report: dict) -> CheckResult:
        """CC-005 (advisory): method_justification field exists and is non-empty.

        Source: agents/reviewer.yaml (cross-validation of Statistics Agent output)
        """
        justification = review_report.get("method_justification")
        passed = bool(justification and str(justification).strip())
        message = (
            "CC-005: method_justification is present and non-empty."
            if passed
            else "CC-005: method_justification is missing or empty in review_report."
        )

        return CheckResult(
            check_id="CC-005",
            dimension=self.dimension,
            passed=passed,
            severity="advisory",
            message=message,
        )

    def _check_cc006(self, primary: dict, method_used: str) -> CheckResult:
        """CC-006 (critical): when p < 0.05, CI must not contain the null value.

        Branching logic (IMPLEMENTATION GUIDE.md Section 2.1, Phase 7 note):
          - Logistic regression / GLM: null value is OR=1.0
            -> valid iff ci_lower > 1.0 OR ci_upper < 1.0
          - Continuous outcomes (default): null value is 0
            -> valid iff ci_lower > 0 OR ci_upper < 0

        Source: agents/reviewer.yaml CC-006
        """
        p_value = primary.get("p_value")
        ci_lower = primary.get("ci_lower")
        ci_upper = primary.get("ci_upper")

        # Cannot check without p_value — CC-001 already flags this
        if p_value is None:
            return CheckResult(
                check_id="CC-006",
                dimension=self.dimension,
                passed=True,   # Defer: CC-001 is the authoritative check
                severity="critical",
                message="CC-006: p_value missing; deferring to CC-001.",
            )

        # Only applies when result is statistically significant
        if float(p_value) >= 0.05:
            return CheckResult(
                check_id="CC-006",
                dimension=self.dimension,
                passed=True,
                severity="critical",
                message=f"CC-006: p={p_value} >= 0.05; CI direction check not required.",
                actual_value=str(p_value),
            )

        if ci_lower is None or ci_upper is None:
            return CheckResult(
                check_id="CC-006",
                dimension=self.dimension,
                passed=False,
                severity="critical",
                message="CC-006: p < 0.05 but ci_lower/ci_upper missing; cannot verify CI direction.",
                actual_value=str(p_value),
            )

        ci_lower_f = float(ci_lower)
        ci_upper_f = float(ci_upper)
        method_lower = method_used.lower()

        is_logistic = "logistic" in method_lower or "glm" in method_lower

        if is_logistic:
            # OR CI must not straddle 1.0
            null_value = 1.0
            ci_valid = ci_lower_f > null_value or ci_upper_f < null_value
            null_desc = "OR=1.0"
        else:
            # Continuous outcome: CI must not straddle 0
            null_value = 0.0
            ci_valid = ci_lower_f > null_value or ci_upper_f < null_value
            null_desc = "0"

        message = (
            f"CC-006: p={p_value} < 0.05 and CI [{ci_lower}, {ci_upper}] "
            f"does not contain null ({null_desc}). Consistent."
            if ci_valid
            else (
                f"CC-006: p={p_value} < 0.05 but CI [{ci_lower}, {ci_upper}] "
                f"contains null ({null_desc}). Inconsistent — possible reporting error."
            )
        )

        return CheckResult(
            check_id="CC-006",
            dimension=self.dimension,
            passed=ci_valid,
            severity="critical",
            message=message,
            actual_value=f"p={p_value}, CI=[{ci_lower}, {ci_upper}]",
            expected_value=f"CI must not contain {null_desc}",
        )

    def _check_cc007(self, effect: dict) -> CheckResult:
        """CC-007 (advisory): effect_size.interpretation must be a valid label.

        Valid values: "negligible" | "small" | "medium" | "large".
        Source: agents/reviewer.yaml CC-007
        """
        valid_interpretations = {"negligible", "small", "medium", "large"}
        interpretation = effect.get("interpretation")

        if interpretation is None:
            passed = False
            message = "CC-007: effect_size.interpretation is missing."
        else:
            passed = str(interpretation).lower() in valid_interpretations
            message = (
                f"CC-007: effect_size.interpretation='{interpretation}' is valid."
                if passed
                else (
                    f"CC-007: effect_size.interpretation='{interpretation}' is not in "
                    f"the allowed set {sorted(valid_interpretations)}."
                )
            )

        return CheckResult(
            check_id="CC-007",
            dimension=self.dimension,
            passed=passed,
            severity="advisory",
            message=message,
            actual_value=str(interpretation) if interpretation is not None else None,
            expected_value=str(sorted(valid_interpretations)),
        )
