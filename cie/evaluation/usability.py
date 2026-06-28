"""CIE Platform — Output Usability & Explainability Evaluator.

Implements the Usability evaluation dimension (weight_pct=10).
Checks US-001 through US-004 as specified in evaluation/usability.yaml.

Note per usability.yaml §metadata:
  blocking: false — usability evaluation is non-blocking by default.
  All checks in this evaluator use advisory severity unless the score
  drops below the hard-block threshold (70), which is enforced by
  EvaluatorService, not this evaluator.
"""

from __future__ import annotations

from cie.evaluation.base import (
    BaseEvaluator,
    CheckResult,
    DimensionScore,
    EvaluationDimension,
)

# Thresholds from usability.yaml / prompt spec
_MAX_UNRESOLVED_ITEMS = 3
_MIN_WORD_COUNT = 800          # reasonable lower bound for a clinical manuscript
_MAX_WORD_COUNT = 8000         # upper bound
_MIN_METHODS_CHARS = 200       # US-004: methods_text >= 200 characters


class UsabilityEvaluator(BaseEvaluator):
    """Output usability and explainability evaluator.

    Dimension: USABILITY (weight_pct = 10).

    Runs checks US-001 through US-004.

    Expected artifact keys:
        - "review_report" (dict): From Reviewer Agent.
            May contain: unresolved_items (list).
        - "manuscript_sections" (dict): From Reporting Agent.
            May contain:
                word_count (int)
                methods_text (str)
        - "figure_manifest" (list[dict]): From Visualization Agent.
            Each entry represents a generated figure.
    """

    @property
    def dimension(self) -> EvaluationDimension:
        """Returns USABILITY."""
        return EvaluationDimension.USABILITY

    @property
    def weight_pct(self) -> int:
        """Weight 10% per evaluation/usability.yaml."""
        return 10

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def evaluate(self, artifacts: dict) -> DimensionScore:
        """Run US-001 through US-004 and return a DimensionScore.

        Args:
            artifacts: Artifact dict with "review_report",
                "manuscript_sections", and "figure_manifest".

        Returns:
            DimensionScore with score in [0.0, 100.0] and check details.
        """
        review_report: dict = artifacts.get("review_report") or {}
        manuscript: dict = artifacts.get("manuscript_sections") or {}
        figure_manifest: list = artifacts.get("figure_manifest") or []

        checks: list[CheckResult] = [
            self._check_us001(review_report),
            self._check_us002(manuscript),
            self._check_us003(figure_manifest),
            self._check_us004(manuscript),
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
    # Individual checks (US-001 … US-004)
    # ------------------------------------------------------------------

    def _check_us001(self, review_report: dict) -> CheckResult:
        """US-001 (advisory): unresolved_items must be 3 or fewer.

        Source: usability.yaml USB-005-A (Actionability of Findings).
        """
        unresolved = review_report.get("unresolved_items") or []
        count = len(unresolved)
        passed = count <= _MAX_UNRESOLVED_ITEMS

        message = (
            f"US-001: {count} unresolved item(s) — within acceptable limit (<= {_MAX_UNRESOLVED_ITEMS})."
            if passed
            else (
                f"US-001: {count} unresolved item(s) exceeds limit of {_MAX_UNRESOLVED_ITEMS}. "
                "Reduce outstanding items or escalate for human review."
            )
        )

        return CheckResult(
            check_id="US-001",
            dimension=self.dimension,
            passed=passed,
            severity="advisory",
            message=message,
            actual_value=str(count),
            expected_value=f"<= {_MAX_UNRESOLVED_ITEMS}",
        )

    def _check_us002(self, manuscript: dict) -> CheckResult:
        """US-002 (advisory): manuscript word_count must be within target range.

        Source: usability.yaml USB-001 (Report Interpretability).
        Acceptable range: [800, 8000] words.
        """
        word_count = manuscript.get("word_count")

        if word_count is None:
            return CheckResult(
                check_id="US-002",
                dimension=self.dimension,
                passed=True,   # advisory: skip gracefully if not declared
                severity="advisory",
                message="US-002: word_count not declared in manuscript_sections; check skipped.",
            )

        try:
            wc = int(word_count)
        except (TypeError, ValueError):
            return CheckResult(
                check_id="US-002",
                dimension=self.dimension,
                passed=False,
                severity="advisory",
                message=f"US-002: word_count={word_count!r} is not numeric.",
            )

        passed = _MIN_WORD_COUNT <= wc <= _MAX_WORD_COUNT
        message = (
            f"US-002: word_count={wc} is within target range [{_MIN_WORD_COUNT}, {_MAX_WORD_COUNT}]."
            if passed
            else (
                f"US-002: word_count={wc} is outside target range [{_MIN_WORD_COUNT}, {_MAX_WORD_COUNT}]. "
                "Revise manuscript length for clinical readability."
            )
        )

        return CheckResult(
            check_id="US-002",
            dimension=self.dimension,
            passed=passed,
            severity="advisory",
            message=message,
            actual_value=str(wc),
            expected_value=f"[{_MIN_WORD_COUNT}, {_MAX_WORD_COUNT}]",
        )

    def _check_us003(self, figure_manifest: list) -> CheckResult:
        """US-003 (advisory): at least one figure must have been generated.

        Source: usability.yaml USB-002 (Figure Clarity).
        """
        count = len(figure_manifest)
        passed = count >= 1

        message = (
            f"US-003: {count} figure(s) generated — meets minimum requirement."
            if passed
            else (
                "US-003: No figures were generated. "
                "At least one figure is expected for clinical manuscript completeness."
            )
        )

        return CheckResult(
            check_id="US-003",
            dimension=self.dimension,
            passed=passed,
            severity="advisory",
            message=message,
            actual_value=str(count),
            expected_value=">= 1",
        )

    def _check_us004(self, manuscript: dict) -> CheckResult:
        """US-004 (advisory): methods_text must be at least 200 characters.

        Source: usability.yaml USB-001-A (method explanation in plain language).
        """
        methods_text = manuscript.get("methods_text") or ""
        char_count = len(str(methods_text).strip())
        passed = char_count >= _MIN_METHODS_CHARS

        message = (
            f"US-004: methods_text has {char_count} characters — meets minimum ({_MIN_METHODS_CHARS})."
            if passed
            else (
                f"US-004: methods_text has {char_count} characters, below minimum of {_MIN_METHODS_CHARS}. "
                "Methods section must include a plain-language explanation of statistical methods."
            )
        )

        return CheckResult(
            check_id="US-004",
            dimension=self.dimension,
            passed=passed,
            severity="advisory",
            message=message,
            actual_value=str(char_count),
            expected_value=f">= {_MIN_METHODS_CHARS} characters",
        )
