"""Unit tests for cie.reporting.result_formatter."""

from __future__ import annotations

from cie.reporting.result_formatter import format_statistical_results


def test_formats_core_fields() -> None:
    sr = {
        "test_name": "Welch t-test",
        "method_id": "independent_samples_t_test",
        "test_statistic": -4.6315,
        "df": 74.8589,
        "p_value": 1.5e-05,
        "effect_size": 1.0356,
        "effect_size_measure": "Cohen's d",
        "sample_size": 80,
        "ci_lower": -13.84,
        "ci_upper": -5.52,
    }
    out = format_statistical_results(sr)
    assert "Welch t-test" in out
    assert "< 0.001" in out            # small p-value rendered APA-style
    assert "Cohen's d" in out
    assert "95%信頼区間" in out
    assert "[-13.84, -5.52]" in out


def test_large_p_value_is_not_abbreviated() -> None:
    out = format_statistical_results({"p_value": 0.42})
    assert "0.420" in out
    assert "< 0.001" not in out


def test_none_results_explains_reason() -> None:
    out = format_statistical_results(None, reason="result_json_not_produced_by_script")
    assert "生成されませんでした" in out
    assert "result_json_not_produced_by_script" in out


def test_group_summaries_and_extras_rendered() -> None:
    sr = {
        "p_value": 0.01,
        "group_summaries": {"M": {"n": 40, "mean": 130.2}, "F": {"n": 40, "mean": 122.1}},
        "warning": "small_sample",
    }
    out = format_statistical_results(sr)
    assert "群別要約" in out
    assert "M:" in out and "F:" in out
    assert "warning" in out  # unexpected key surfaced under その他
