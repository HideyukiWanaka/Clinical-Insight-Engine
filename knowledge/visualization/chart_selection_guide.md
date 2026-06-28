# Chart Selection Guide
# Domain: visualization
# Version: 1.0.0
# Status: Stable
# Consumers: visualization
# Immutable during execution (AP-014)

## Purpose

Provides the Visualization Agent with a deterministic chart selection framework
based on data characteristics from statistical results. Every chart selection
must reference this guide in the selection_rationale field.

---

## Primary Selection Framework

### Step 1 — Identify the analytical objective of the figure

| Objective | Chart family |
|-----------|-------------|
| Show distribution of a continuous variable | Distribution charts |
| Compare a continuous variable across groups | Group comparison charts |
| Show relationship between two continuous variables | Correlation / regression charts |
| Show proportions or counts of categorical variables | Categorical charts |
| Show survival over time | Survival charts |
| Summarise effect sizes across multiple analyses | Summary charts |
| Check statistical assumptions | Diagnostic charts |

---

### Step 2 — Select chart type by data characteristics

#### Distribution Charts

| Situation | Chart type | Selection rationale keyword |
|-----------|-----------|----------------------------|
| Single continuous variable, any n | Histogram with density overlay | `distribution_histogram` |
| Comparing distribution shape across 2–4 groups | Overlaid density plot | `distribution_density_overlay` |
| Normality assessment | QQ plot | `diagnostic_qq` |

#### Group Comparison Charts — Continuous Outcome

| n per group | Groups | Paired? | Chart type | Selection keyword |
|------------|--------|---------|-----------|------------------|
| Any | 2–6 | No | Box plot with jitter | `group_comparison_boxplot` |
| > 100 | 2–6 | No | Violin plot | `group_comparison_violin` |
| > 500 | 2–6 | No | Raincloud plot | `group_comparison_raincloud` |
| Any | 2 | Yes | Slopegraph | `paired_slopegraph` |
| Small n (< 30) | 2 | Yes | Paired box plot with lines | `paired_boxplot_lines` |

#### Correlation / Regression Charts

| Situation | Chart type | Selection keyword |
|-----------|-----------|------------------|
| Two continuous variables, n < 500 | Scatter plot with regression line + CI band | `correlation_scatter` |
| Two continuous variables, n ≥ 500 | Hexbin density plot | `correlation_hexbin` |
| Multiple predictors in regression | Coefficient plot (forest-style) | `regression_coefficient_plot` |

#### Categorical Proportion Charts

| Situation | Chart type | Selection keyword |
|-----------|-----------|------------------|
| Comparing proportions across 2–4 groups | Grouped bar chart | `categorical_grouped_bar` |
| Showing part-of-whole within groups | Stacked bar chart | `categorical_stacked_bar` |
| Binary outcome rate with CI | Dot plot with error bars | `categorical_proportion_dot` |

#### Survival Charts

| Situation | Chart type | Selection keyword |
|-----------|-----------|------------------|
| Always (for survival outcomes) | Kaplan-Meier curve with risk table | `survival_kaplan_meier` |
| KM + p-value | Add log-rank p-value annotation | `survival_kaplan_meier_pvalue` |

#### Summary / Meta-level Charts

| Situation | Chart type | Selection keyword |
|-----------|-----------|------------------|
| Multiple OR/HR from regression | Forest plot | `summary_forest_plot` |
| Multiple correlations | Heatmap correlation matrix | `summary_correlation_heatmap` |

#### Diagnostic Charts

| Situation | Chart type | Selection keyword |
|-----------|-----------|------------------|
| Normality check | QQ plot | `diagnostic_qq` |
| Regression assumption check | Residuals vs fitted plot | `diagnostic_residuals` |
| Influential points | Cook's distance plot | `diagnostic_cooks` |
| ROC curve | ROC with AUC annotation | `diagnostic_roc` |

---

## Mandatory Figure Components Checklist

Every figure specification must confirm all of the following:

| Component | Requirement | Fails check |
|-----------|-------------|------------|
| Title or caption | Present and descriptive | USB-002-A |
| X-axis label | Present with units | USB-002-B |
| Y-axis label | Present with units | USB-002-B |
| Statistical annotation | p-value, effect size, n | USB-002-A |
| Color palette | Okabe-Ito (default) | VZ-003 |
| Resolution | 300 DPI minimum | VZ-004 |
| Legend | Present if ≥ 2 groups | — |
| Error bars defined | SD / SE / 95% CI specified in caption | — |

---

## Multi-Figure Layout Rules

| n figures | Layout recommendation |
|-----------|----------------------|
| 1–2 | Single column, full width (180mm) |
| 3–4 | 2×2 grid using `patchwork::wrap_plots()` |
| 5–6 | 2×3 grid |
| > 6 | Split into main figure + supplementary figures |

```r
library(patchwork)
combined <- (fig1 | fig2) / (fig3 | fig4)
combined + plot_annotation(tag_levels = "A")
```

---

## Selection Rationale Output Template

Each figure in `visualization_specifications` must include:

```yaml
figure_id: "fig_01"
chart_type: "group_comparison_boxplot"
selection_rationale:
  objective: "between_group_comparison"
  outcome_type: "continuous"
  n_per_group: 87
  groups: 2
  paired: false
  guideline_reference: "visualization/chart_selection_guide.md Step 2 Group Comparison"
statistical_annotation:
  test: "Mann-Whitney U test"
  p_value: 0.023
  effect_size: "r = 0.31"
  n_total: 174
```
