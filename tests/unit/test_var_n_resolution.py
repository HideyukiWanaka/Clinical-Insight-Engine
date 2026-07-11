"""Unit tests for var_n -> real-column-name resolution in R/ggplot2 prompt building.

dataset_structural_metadata and intent_object.{outcome,predictor}_variables are
var_n-keyed (Planner privacy boundary, DQ-001), but dataset.csv on disk keeps
its original headers, so Statistics/Visualization R-generation prompts must
resolve var_n back to the real column name via var_n_alias_map before asking
the LLM to write R code — otherwise the generated code references a column
that does not exist in dataset.csv.

Test matrix:
- test_statistics_resolve_column_metadata   — var_n keys -> real names
- test_statistics_resolve_variable_list     — var_n values -> real names
- test_statistics_r_gen_message_uses_real_names — end-to-end prompt content
- test_visualization_resolve_column_metadata
- test_visualization_resolve_variable_list
- test_visualization_r_gen_message_uses_real_names
"""

from __future__ import annotations

from cie.agents import statistics as statistics_mod
from cie.agents import visualization as visualization_mod
from cie.agents.statistics import StatisticsAgent
from cie.agents.visualization import VisualizationAgent

_ALIAS_MAP = {"var_1": "収縮期血圧_mmHg", "var_2": "性別"}


def test_statistics_resolve_column_metadata() -> None:
    resolved = statistics_mod._resolve_column_metadata(
        {"var_1": {"inferred_type": "continuous"}, "var_2": {"inferred_type": "categorical_binary"}},
        _ALIAS_MAP,
    )
    assert resolved == {
        "収縮期血圧_mmHg": {"inferred_type": "continuous"},
        "性別": {"inferred_type": "categorical_binary"},
    }


def test_statistics_resolve_variable_list() -> None:
    resolved = statistics_mod._resolve_variable_list(
        [{"var_n": "var_1", "role": "primary_outcome"}], _ALIAS_MAP
    )
    assert resolved == [{"var_n": "収縮期血圧_mmHg", "role": "primary_outcome"}]


def test_statistics_r_gen_message_uses_real_names() -> None:
    msg = StatisticsAgent._build_r_gen_user_message(
        method={
            "method_id": "independent_samples_t_test",
            "r_function": "t.test",
            "r_packages": ["base"],
            "effect_size_measure": "Cohen's d",
        },
        intent_obj={
            "objective": "between_group_comparison",
            "outcome_type": "continuous",
            "paired": False,
            "outcome_variables": [{"var_n": "var_1", "role": "primary_outcome"}],
            "predictor_variables": [{"var_n": "var_2", "role": "grouping_variable"}],
            "distribution_assumptions": "assumed_normal",
        },
        column_metadata={"収縮期血圧_mmHg": {"inferred_type": "continuous"}},
        references=[],
        alias_map=_ALIAS_MAP,
    )
    assert "収縮期血圧_mmHg" in msg
    assert '"var_1"' not in msg
    assert '"var_2"' not in msg


def test_visualization_resolve_column_metadata() -> None:
    resolved = visualization_mod._resolve_column_metadata(
        {"var_1": {"inferred_type": "continuous"}}, _ALIAS_MAP
    )
    assert resolved == {"収縮期血圧_mmHg": {"inferred_type": "continuous"}}


def test_visualization_resolve_variable_list() -> None:
    resolved = visualization_mod._resolve_variable_list(
        [{"var_n": "var_2", "role": "grouping_variable"}], _ALIAS_MAP
    )
    assert resolved == [{"var_n": "性別", "role": "grouping_variable"}]


def test_visualization_r_gen_message_uses_real_names() -> None:
    msg = VisualizationAgent._build_viz_r_gen_user_message(
        chart_key="box_plot_with_jitter",
        figure_id="fig_box_plot_001",
        chart_base={
            "chart_type": "box_plot_with_jitter",
            "ggplot2_geom": ["geom_boxplot", "geom_jitter"],
            "description": "Box plot with jitter",
        },
        intent_obj={
            "objective": "between_group_comparison",
            "outcome_type": "continuous",
            "paired": False,
            "outcome_variables": [{"var_n": "var_1", "role": "primary_outcome"}],
            "predictor_variables": [{"var_n": "var_2", "role": "grouping_variable"}],
        },
        statistical_results={"method_id": "independent_samples_t_test", "p_value": 0.01},
        column_metadata={"収縮期血圧_mmHg": {"inferred_type": "continuous"}},
        references=[],
        alias_map=_ALIAS_MAP,
    )
    assert "収縮期血圧_mmHg" in msg
    assert '"var_1"' not in msg
    assert '"var_2"' not in msg
