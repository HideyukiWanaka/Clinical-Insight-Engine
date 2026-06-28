"""Unit tests for cie.evaluation.correctness.CorrectnessEvaluator.

Tests cover CC-001 through CC-007 and the DimensionScore scoring rules.
Run with: pytest tests/unit/test_correctness_evaluator.py -v
"""

from __future__ import annotations

import pytest

from cie.evaluation.base import EvaluationDimension
from cie.evaluation.correctness import CorrectnessEvaluator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def evaluator() -> CorrectnessEvaluator:
    """Return a fresh CorrectnessEvaluator instance."""
    return CorrectnessEvaluator()


def _make_artifacts(
    *,
    p_value: float = 0.03,
    effect_value: float = 0.5,
    effect_interpretation: str = "medium",
    ci_lower: float = 0.1,
    ci_upper: float = 0.9,
    n_observations: int = 100,
    n_observations_expected: int | None = 100,
    method_used: str = "t-test",
    method_justification: str = "Selected based on normality test.",
) -> dict:
    """Build a minimal artifacts dict for testing.

    All keyword arguments have valid defaults, so tests can override only
    the field they want to exercise.
    """
    return {
        "execution_result": {
            "primary_result": {
                "p_value": p_value,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "n_observations": n_observations,
            },
            "effect_size": {
                "value": effect_value,
                "interpretation": effect_interpretation,
            },
            "method_used": method_used,
        },
        "review_report": {
            "method_justification": method_justification,
        },
        "analysis_plan": {
            "n_observations_expected": n_observations_expected,
        },
    }


# ---------------------------------------------------------------------------
# Evaluator metadata
# ---------------------------------------------------------------------------

class TestEvaluatorMetadata:
    def test_dimension(self, evaluator: CorrectnessEvaluator) -> None:
        assert evaluator.dimension == EvaluationDimension.CORRECTNESS

    def test_weight_pct(self, evaluator: CorrectnessEvaluator) -> None:
        """Weight must be 40 per evaluation/correctness.yaml."""
        assert evaluator.weight_pct == 40


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestValidResultsPass:
    def test_valid_results_pass(self, evaluator: CorrectnessEvaluator) -> None:
        """All checks pass with valid, self-consistent artifacts."""
        artifacts = _make_artifacts()
        result = evaluator.evaluate(artifacts)

        assert result.critical_failure is False
        assert result.score > 0.0
        assert all(r.passed for r in result.check_results)

    def test_dimension_score_fields(self, evaluator: CorrectnessEvaluator) -> None:
        artifacts = _make_artifacts()
        result = evaluator.evaluate(artifacts)

        assert result.dimension == EvaluationDimension.CORRECTNESS
        assert result.weight_pct == 40
        assert 0.0 <= result.score <= 100.0
        assert len(result.check_results) == 7  # CC-001 through CC-007


# ---------------------------------------------------------------------------
# CC-001: p_value range
# ---------------------------------------------------------------------------

class TestCC001:
    def test_invalid_p_value_fails_cc001(self, evaluator: CorrectnessEvaluator) -> None:
        """p_value=1.5 must trigger CC-001 critical failure."""
        artifacts = _make_artifacts(p_value=1.5)
        result = evaluator.evaluate(artifacts)

        cc001 = next(r for r in result.check_results if r.check_id == "CC-001")
        assert cc001.passed is False
        assert cc001.severity == "critical"

    def test_p_value_zero_passes(self, evaluator: CorrectnessEvaluator) -> None:
        artifacts = _make_artifacts(p_value=0.0, ci_lower=0.1, ci_upper=0.9)
        result = evaluator.evaluate(artifacts)
        cc001 = next(r for r in result.check_results if r.check_id == "CC-001")
        assert cc001.passed is True

    def test_p_value_one_passes(self, evaluator: CorrectnessEvaluator) -> None:
        artifacts = _make_artifacts(p_value=1.0)
        result = evaluator.evaluate(artifacts)
        cc001 = next(r for r in result.check_results if r.check_id == "CC-001")
        assert cc001.passed is True

    def test_negative_p_value_fails(self, evaluator: CorrectnessEvaluator) -> None:
        artifacts = _make_artifacts(p_value=-0.01)
        result = evaluator.evaluate(artifacts)
        cc001 = next(r for r in result.check_results if r.check_id == "CC-001")
        assert cc001.passed is False


# ---------------------------------------------------------------------------
# CC-002: effect_size.value >= 0
# ---------------------------------------------------------------------------

class TestCC002:
    def test_negative_effect_size_fails_cc002(
        self, evaluator: CorrectnessEvaluator
    ) -> None:
        """effect_size=-0.1 must trigger CC-002 critical failure."""
        artifacts = _make_artifacts(effect_value=-0.1)
        result = evaluator.evaluate(artifacts)

        cc002 = next(r for r in result.check_results if r.check_id == "CC-002")
        assert cc002.passed is False
        assert cc002.severity == "critical"

    def test_zero_effect_size_passes(self, evaluator: CorrectnessEvaluator) -> None:
        artifacts = _make_artifacts(effect_value=0.0)
        result = evaluator.evaluate(artifacts)
        cc002 = next(r for r in result.check_results if r.check_id == "CC-002")
        assert cc002.passed is True


# ---------------------------------------------------------------------------
# CC-003: n_observations within 5% of expected
# ---------------------------------------------------------------------------

class TestCC003:
    def test_exact_match_passes(self, evaluator: CorrectnessEvaluator) -> None:
        artifacts = _make_artifacts(n_observations=100, n_observations_expected=100)
        result = evaluator.evaluate(artifacts)
        cc003 = next(r for r in result.check_results if r.check_id == "CC-003")
        assert cc003.passed is True

    def test_within_tolerance_passes(self, evaluator: CorrectnessEvaluator) -> None:
        # 4% deviation is within 5%
        artifacts = _make_artifacts(n_observations=104, n_observations_expected=100)
        result = evaluator.evaluate(artifacts)
        cc003 = next(r for r in result.check_results if r.check_id == "CC-003")
        assert cc003.passed is True

    def test_outside_tolerance_fails(self, evaluator: CorrectnessEvaluator) -> None:
        # 10% deviation exceeds 5%
        artifacts = _make_artifacts(n_observations=110, n_observations_expected=100)
        result = evaluator.evaluate(artifacts)
        cc003 = next(r for r in result.check_results if r.check_id == "CC-003")
        assert cc003.passed is False

    def test_no_expected_skips_check(self, evaluator: CorrectnessEvaluator) -> None:
        artifacts = _make_artifacts(n_observations=100, n_observations_expected=None)
        result = evaluator.evaluate(artifacts)
        cc003 = next(r for r in result.check_results if r.check_id == "CC-003")
        assert cc003.passed is True  # graceful skip


# ---------------------------------------------------------------------------
# CC-006: CI direction consistent with significance
# ---------------------------------------------------------------------------

class TestCC006:
    def test_ci_inconsistent_with_p_fails_cc006(
        self, evaluator: CorrectnessEvaluator
    ) -> None:
        """p=0.01 with CI=[-0.5, 0.3] spans 0 -> CC-006 must fail."""
        artifacts = _make_artifacts(
            p_value=0.01,
            ci_lower=-0.5,
            ci_upper=0.3,
            method_used="t-test",
        )
        result = evaluator.evaluate(artifacts)

        cc006 = next(r for r in result.check_results if r.check_id == "CC-006")
        assert cc006.passed is False
        assert cc006.severity == "critical"

    def test_ci_consistent_with_p_passes_cc006(
        self, evaluator: CorrectnessEvaluator
    ) -> None:
        """p=0.01 with CI=[0.2, 0.8] does not span 0 -> CC-006 must pass."""
        artifacts = _make_artifacts(
            p_value=0.01,
            ci_lower=0.2,
            ci_upper=0.8,
            method_used="t-test",
        )
        result = evaluator.evaluate(artifacts)

        cc006 = next(r for r in result.check_results if r.check_id == "CC-006")
        assert cc006.passed is True

    def test_logistic_ci_spans_one_fails(
        self, evaluator: CorrectnessEvaluator
    ) -> None:
        """Logistic: p=0.01 with OR CI=[0.7, 1.3] spans 1.0 -> CC-006 fails."""
        artifacts = _make_artifacts(
            p_value=0.01,
            ci_lower=0.7,
            ci_upper=1.3,
            method_used="logistic_regression",
        )
        result = evaluator.evaluate(artifacts)

        cc006 = next(r for r in result.check_results if r.check_id == "CC-006")
        assert cc006.passed is False

    def test_logistic_ci_above_one_passes(
        self, evaluator: CorrectnessEvaluator
    ) -> None:
        """Logistic: p=0.01 with OR CI=[1.2, 2.5] does not span 1.0 -> CC-006 passes."""
        artifacts = _make_artifacts(
            p_value=0.01,
            ci_lower=1.2,
            ci_upper=2.5,
            method_used="logistic_regression",
        )
        result = evaluator.evaluate(artifacts)

        cc006 = next(r for r in result.check_results if r.check_id == "CC-006")
        assert cc006.passed is True

    def test_non_significant_result_skips_cc006(
        self, evaluator: CorrectnessEvaluator
    ) -> None:
        """p >= 0.05: CC-006 should pass unconditionally."""
        artifacts = _make_artifacts(
            p_value=0.20,
            ci_lower=-0.5,
            ci_upper=0.5,   # spans 0, but doesn't matter when p >= 0.05
        )
        result = evaluator.evaluate(artifacts)

        cc006 = next(r for r in result.check_results if r.check_id == "CC-006")
        assert cc006.passed is True


# ---------------------------------------------------------------------------
# Scoring rules
# ---------------------------------------------------------------------------

class TestScoringRules:
    def test_critical_failure_zeroes_score(
        self, evaluator: CorrectnessEvaluator
    ) -> None:
        """Any critical failure must produce score=0.0."""
        artifacts = _make_artifacts(p_value=1.5)  # CC-001 critical failure
        result = evaluator.evaluate(artifacts)

        assert result.score == 0.0
        assert result.critical_failure is True

    def test_advisory_failure_reduces_score(
        self, evaluator: CorrectnessEvaluator
    ) -> None:
        """Advisory-only failure must reduce score but keep it > 0."""
        # Trigger CC-005 (advisory) by omitting method_justification
        artifacts = _make_artifacts(method_justification="")
        result = evaluator.evaluate(artifacts)

        cc005 = next(r for r in result.check_results if r.check_id == "CC-005")
        assert cc005.passed is False
        assert cc005.severity == "advisory"

        assert result.critical_failure is False
        assert result.score > 0.0
        assert result.score < 100.0

    def test_all_advisory_failures_still_positive_score(
        self, evaluator: CorrectnessEvaluator
    ) -> None:
        """All advisory checks failing should give score=50.0 (100 - 50 deduction)."""
        artifacts = _make_artifacts(
            method_justification="",          # CC-005 advisory fail
            effect_interpretation="invalid",  # CC-007 advisory fail
            ci_lower=0.5,                     # CC-004 advisory: upper > lower OK
            ci_upper=0.9,
        )
        result = evaluator.evaluate(artifacts)

        assert result.critical_failure is False
        assert result.score > 0.0

    def test_all_pass_gives_100_score(self, evaluator: CorrectnessEvaluator) -> None:
        artifacts = _make_artifacts()
        result = evaluator.evaluate(artifacts)

        # All 7 checks pass with default valid data
        assert all(r.passed for r in result.check_results)
        assert result.score == 100.0

    def test_dimension_score_weight(self, evaluator: CorrectnessEvaluator) -> None:
        """weight_pct must be 40 per evaluation/correctness.yaml."""
        artifacts = _make_artifacts()
        result = evaluator.evaluate(artifacts)
        assert result.weight_pct == 40


# ---------------------------------------------------------------------------
# Edge cases: missing artifact keys
# ---------------------------------------------------------------------------

class TestMissingArtifacts:
    def test_empty_artifacts_does_not_raise(
        self, evaluator: CorrectnessEvaluator
    ) -> None:
        """Missing artifacts must produce score=0 without raising exceptions."""
        result = evaluator.evaluate({})
        assert result.score == 0.0
        assert result.critical_failure is True

    def test_missing_execution_result(self, evaluator: CorrectnessEvaluator) -> None:
        result = evaluator.evaluate({"review_report": {}, "analysis_plan": {}})
        assert result.score == 0.0

    def test_check_results_always_present(
        self, evaluator: CorrectnessEvaluator
    ) -> None:
        """check_results list must always contain exactly 7 entries."""
        result = evaluator.evaluate({})
        assert len(result.check_results) == 7
