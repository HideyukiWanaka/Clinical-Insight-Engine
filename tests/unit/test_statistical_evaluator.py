"""Unit tests for cie.evaluation.statistical.StatisticalEvaluator.

Tests cover ST-001 through ST-007 and dimension-level scoring.
Run with: pytest tests/unit/test_statistical_evaluator.py -v
"""

from __future__ import annotations

import pytest

from cie.evaluation.base import EvaluationDimension
from cie.evaluation.statistical import StatisticalEvaluator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def evaluator() -> StatisticalEvaluator:
    return StatisticalEvaluator()


def _make_artifacts(
    *,
    r_script: str = "set.seed(42)\nresult <- t.test(var_1 ~ var_2, data = df)",
    tests_performed: bool = True,
    normality_results: list | None = None,
    posthoc_performed: bool | None = None,
    omnibus_p_value: float | None = None,
    effect_value: float = 0.45,
    effect_interpretation: str = "small",
    design: str = "independent",
    method_used: str = "welch_t_test",
    n_hypotheses: int = 1,
    multiple_correction: str | None = None,
    expected_cells: list | None = None,
) -> dict:
    """Build a minimal valid artifact dict for StatisticalEvaluator tests."""
    if normality_results is None:
        normality_results = [{"test": "shapiro", "p": 0.12, "passed": True}]

    return {
        "r_script_content": r_script,
        "assumption_report": {
            "tests_performed": tests_performed,
            "normality_results": normality_results,
        },
        "execution_result": {
            "primary_result": {"p_value": 0.03},
            "effect_size": {
                "value": effect_value,
                "interpretation": effect_interpretation,
            },
            "method_used": method_used,
            "posthoc_performed": posthoc_performed,
            "omnibus_p_value": omnibus_p_value,
        },
        "analysis_plan": {
            "design": design,
            "n_hypotheses": n_hypotheses,
            "multiple_correction": multiple_correction,
            "expected_cells": expected_cells or [],
        },
    }


# ---------------------------------------------------------------------------
# Evaluator metadata
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_dimension(self, evaluator: StatisticalEvaluator) -> None:
        assert evaluator.dimension == EvaluationDimension.STATISTICAL

    def test_weight_pct(self, evaluator: StatisticalEvaluator) -> None:
        """Weight must be 35 per evaluation/statistical.yaml."""
        assert evaluator.weight_pct == 35

    def test_returns_7_checks(self, evaluator: StatisticalEvaluator) -> None:
        result = evaluator.evaluate(_make_artifacts())
        assert len(result.check_results) == 7


# ---------------------------------------------------------------------------
# ST-001: set.seed(42)
# ---------------------------------------------------------------------------

class TestST001:
    def test_set_seed_missing_fails_st001(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        """R script without set.seed(42) must trigger ST-001 critical failure."""
        artifacts = _make_artifacts(r_script="result <- t.test(var_1 ~ var_2)")
        result = evaluator.evaluate(artifacts)

        st001 = next(r for r in result.check_results if r.check_id == "ST-001")
        assert st001.passed is False
        assert st001.severity == "critical"
        assert result.critical_failure is True
        assert result.score == 0.0

    def test_set_seed_42_passes(self, evaluator: StatisticalEvaluator) -> None:
        artifacts = _make_artifacts(r_script="set.seed(42)\nt.test(var_1 ~ var_2)")
        result = evaluator.evaluate(artifacts)

        st001 = next(r for r in result.check_results if r.check_id == "ST-001")
        assert st001.passed is True

    def test_set_seed_wrong_value_fails(self, evaluator: StatisticalEvaluator) -> None:
        """set.seed(123) is not set.seed(42) → must fail."""
        artifacts = _make_artifacts(r_script="set.seed(123)\nt.test(var_1 ~ var_2)")
        result = evaluator.evaluate(artifacts)

        st001 = next(r for r in result.check_results if r.check_id == "ST-001")
        assert st001.passed is False

    def test_empty_script_fails(self, evaluator: StatisticalEvaluator) -> None:
        artifacts = _make_artifacts(r_script="")
        result = evaluator.evaluate(artifacts)

        st001 = next(r for r in result.check_results if r.check_id == "ST-001")
        assert st001.passed is False


# ---------------------------------------------------------------------------
# ST-002: assumption checks
# ---------------------------------------------------------------------------

class TestST002:
    def test_assumption_checks_performed(self, evaluator: StatisticalEvaluator) -> None:
        artifacts = _make_artifacts(
            tests_performed=True,
            normality_results=[{"test": "shapiro", "p": 0.3, "passed": True}],
        )
        result = evaluator.evaluate(artifacts)
        st002 = next(r for r in result.check_results if r.check_id == "ST-002")
        assert st002.passed is True

    def test_tests_not_performed_fails(self, evaluator: StatisticalEvaluator) -> None:
        artifacts = _make_artifacts(tests_performed=False)
        result = evaluator.evaluate(artifacts)
        st002 = next(r for r in result.check_results if r.check_id == "ST-002")
        assert st002.passed is False
        assert st002.severity == "critical"

    def test_empty_normality_results_fails(self, evaluator: StatisticalEvaluator) -> None:
        artifacts = _make_artifacts(tests_performed=True, normality_results=[])
        result = evaluator.evaluate(artifacts)
        st002 = next(r for r in result.check_results if r.check_id == "ST-002")
        assert st002.passed is False


# ---------------------------------------------------------------------------
# ST-003: post-hoc consistency with omnibus p-value
# ---------------------------------------------------------------------------

class TestST003:
    def test_posthoc_without_significant_omnibus_fails_st003(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        """post-hoc performed when omnibus p >= 0.05 must fail."""
        artifacts = _make_artifacts(
            posthoc_performed=True,
            omnibus_p_value=0.20,  # not significant
        )
        result = evaluator.evaluate(artifacts)
        st003 = next(r for r in result.check_results if r.check_id == "ST-003")
        assert st003.passed is False
        assert st003.severity == "critical"

    def test_posthoc_with_significant_omnibus_passes(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        artifacts = _make_artifacts(
            posthoc_performed=True,
            omnibus_p_value=0.01,  # significant
        )
        result = evaluator.evaluate(artifacts)
        st003 = next(r for r in result.check_results if r.check_id == "ST-003")
        assert st003.passed is True

    def test_no_posthoc_not_applicable(self, evaluator: StatisticalEvaluator) -> None:
        """posthoc_performed=None means check is not applicable."""
        artifacts = _make_artifacts(posthoc_performed=None)
        result = evaluator.evaluate(artifacts)
        st003 = next(r for r in result.check_results if r.check_id == "ST-003")
        assert st003.passed is True

    def test_posthoc_true_missing_omnibus_fails(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        """posthoc=True but no omnibus_p recorded → cannot verify → fail."""
        artifacts = _make_artifacts(
            posthoc_performed=True,
            omnibus_p_value=None,
        )
        result = evaluator.evaluate(artifacts)
        st003 = next(r for r in result.check_results if r.check_id == "ST-003")
        assert st003.passed is False


# ---------------------------------------------------------------------------
# ST-004: effect size label correctness
# ---------------------------------------------------------------------------

class TestST004:
    def test_effect_size_label_correct_st004(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        """Cohen's d = 0.45 → 'small' is correct."""
        artifacts = _make_artifacts(
            effect_value=0.45,
            effect_interpretation="small",
        )
        result = evaluator.evaluate(artifacts)
        st004 = next(r for r in result.check_results if r.check_id == "ST-004")
        assert st004.passed is True

    def test_effect_size_label_wrong_advisory(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        """Cohen's d = 0.45 labeled as 'large' is wrong (advisory)."""
        artifacts = _make_artifacts(
            effect_value=0.45,
            effect_interpretation="large",
        )
        result = evaluator.evaluate(artifacts)
        st004 = next(r for r in result.check_results if r.check_id == "ST-004")
        assert st004.passed is False
        assert st004.severity == "advisory"
        # Score > 0 because it's advisory only
        assert result.critical_failure is False

    @pytest.mark.parametrize("value,expected_label", [
        (0.1, "negligible"),
        (0.3, "small"),
        (0.6, "medium"),
        (1.0, "large"),
    ])
    def test_cohen_d_thresholds(
        self,
        evaluator: StatisticalEvaluator,
        value: float,
        expected_label: str,
    ) -> None:
        artifacts = _make_artifacts(
            effect_value=value,
            effect_interpretation=expected_label,
        )
        result = evaluator.evaluate(artifacts)
        st004 = next(r for r in result.check_results if r.check_id == "ST-004")
        assert st004.passed is True


# ---------------------------------------------------------------------------
# ST-005: paired design
# ---------------------------------------------------------------------------

class TestST005:
    def test_paired_with_independent_test_fails_st005(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        """Paired design + welch_t_test → ST-005 critical failure."""
        artifacts = _make_artifacts(
            design="paired",
            method_used="welch_t_test",
        )
        result = evaluator.evaluate(artifacts)
        st005 = next(r for r in result.check_results if r.check_id == "ST-005")
        assert st005.passed is False
        assert st005.severity == "critical"

    def test_paired_with_mann_whitney_fails(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        artifacts = _make_artifacts(design="paired", method_used="mann_whitney_u")
        result = evaluator.evaluate(artifacts)
        st005 = next(r for r in result.check_results if r.check_id == "ST-005")
        assert st005.passed is False

    def test_paired_with_paired_t_test_passes(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        artifacts = _make_artifacts(design="paired", method_used="paired_t_test")
        result = evaluator.evaluate(artifacts)
        st005 = next(r for r in result.check_results if r.check_id == "ST-005")
        assert st005.passed is True

    def test_independent_design_skips_st005(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        """Independent design: ST-005 is not applicable."""
        artifacts = _make_artifacts(design="independent", method_used="welch_t_test")
        result = evaluator.evaluate(artifacts)
        st005 = next(r for r in result.check_results if r.check_id == "ST-005")
        assert st005.passed is True


# ---------------------------------------------------------------------------
# ST-006: Fisher exact test for small expected cells
# ---------------------------------------------------------------------------

class TestST006:
    def test_small_cells_with_fisher_passes(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        artifacts = _make_artifacts(
            expected_cells=[{"expected_count": 3}],
            method_used="fisher_exact",
        )
        result = evaluator.evaluate(artifacts)
        st006 = next(r for r in result.check_results if r.check_id == "ST-006")
        assert st006.passed is True

    def test_small_cells_without_fisher_fails(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        artifacts = _make_artifacts(
            expected_cells=[{"expected_count": 2}],
            method_used="chi_square",
        )
        result = evaluator.evaluate(artifacts)
        st006 = next(r for r in result.check_results if r.check_id == "ST-006")
        assert st006.passed is False
        assert st006.severity == "advisory"

    def test_no_small_cells_skips(self, evaluator: StatisticalEvaluator) -> None:
        artifacts = _make_artifacts(
            expected_cells=[{"expected_count": 10}],
            method_used="chi_square",
        )
        result = evaluator.evaluate(artifacts)
        st006 = next(r for r in result.check_results if r.check_id == "ST-006")
        assert st006.passed is True


# ---------------------------------------------------------------------------
# ST-007: multiple testing correction
# ---------------------------------------------------------------------------

class TestST007:
    def test_multiple_hypotheses_with_correction_passes(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        artifacts = _make_artifacts(n_hypotheses=3, multiple_correction="bonferroni")
        result = evaluator.evaluate(artifacts)
        st007 = next(r for r in result.check_results if r.check_id == "ST-007")
        assert st007.passed is True

    def test_multiple_hypotheses_no_correction_fails(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        artifacts = _make_artifacts(n_hypotheses=3, multiple_correction=None)
        result = evaluator.evaluate(artifacts)
        st007 = next(r for r in result.check_results if r.check_id == "ST-007")
        assert st007.passed is False
        assert st007.severity == "advisory"

    def test_single_hypothesis_skips_correction(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        artifacts = _make_artifacts(n_hypotheses=1, multiple_correction=None)
        result = evaluator.evaluate(artifacts)
        st007 = next(r for r in result.check_results if r.check_id == "ST-007")
        assert st007.passed is True


# ---------------------------------------------------------------------------
# Scoring rules
# ---------------------------------------------------------------------------

class TestScoringRules:
    def test_all_pass_gives_high_score(self, evaluator: StatisticalEvaluator) -> None:
        result = evaluator.evaluate(_make_artifacts())
        assert result.critical_failure is False
        assert result.score > 0.0

    def test_critical_failure_zeroes_score(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        artifacts = _make_artifacts(r_script="")  # ST-001 critical fail
        result = evaluator.evaluate(artifacts)
        assert result.score == 0.0
        assert result.critical_failure is True

    def test_empty_artifacts_no_exception(
        self, evaluator: StatisticalEvaluator
    ) -> None:
        result = evaluator.evaluate({})
        assert result.score == 0.0
