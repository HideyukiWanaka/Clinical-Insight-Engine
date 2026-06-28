# Statistical Method Selection Guide
# Domain: statistics
# Version: 1.0.0
# Status: Stable
# Consumers: statistics
# Immutable during execution (AP-014)

## Purpose

Provides the Statistics Agent with a complete, deterministic decision framework
for selecting appropriate statistical methods from the intent_object fields.
Every selection must be traceable to this guide via the justification field.

---

## Primary Decision Framework

### Axis 1 — Objective × Outcome Type × Predictor Type

#### Between-Group Comparison — Continuous Outcome

| Groups | Paired? | Assumed Normal? | Method | R Function |
|--------|---------|----------------|--------|-----------|
| 2 | No | Yes | Independent samples t-test | `t.test(var ~ group, var.equal=FALSE)` |
| 2 | No | No | Mann-Whitney U test | `wilcox.test(var ~ group)` |
| 2 | Yes | Yes | Paired t-test | `t.test(pre, post, paired=TRUE)` |
| 2 | Yes | No | Wilcoxon signed-rank test | `wilcox.test(pre, post, paired=TRUE)` |
| ≥3 | No | Yes | One-way ANOVA | `aov(var ~ group)` |
| ≥3 | No | No | Kruskal-Wallis test | `kruskal.test(var ~ group)` |
| ≥3 | Yes | Yes | Repeated-measures ANOVA | `aov(var ~ time + Error(id/time))` |
| ≥3 | Yes | No | Friedman test | `friedman.test(var ~ time \| id)` |

#### Between-Group Comparison — Categorical Binary Outcome

| Expected cell count | Method | R Function |
|--------------------|--------|-----------|
| All cells ≥ 5 | Chi-square test | `chisq.test(table(group, outcome))` |
| Any cell < 5 | Fisher's exact test | `fisher.test(table(group, outcome))` |

#### Regression Analysis — Continuous Outcome

| Situation | Method | R Function |
|-----------|--------|-----------|
| Single continuous predictor | Simple linear regression | `lm(outcome ~ predictor)` |
| Multiple predictors | Multiple linear regression | `lm(outcome ~ pred1 + pred2 + ...)` |
| Repeated measures / clustered data | Linear mixed-effects model | `lme4::lmer(outcome ~ pred + (1\|id))` |

#### Regression Analysis — Binary Outcome

| Situation | Method | R Function |
|-----------|--------|-----------|
| Standard logistic | Logistic regression | `glm(outcome ~ preds, family=binomial)` |
| Rare outcome (<10%) | Consider Firth's penalized | `logistf::logistf(outcome ~ preds)` |
| Clustered / repeated | Mixed logistic | `lme4::glmer(outcome ~ pred + (1\|id), family=binomial)` |

#### Survival Analysis

| Situation | Method | R Function |
|-----------|--------|-----------|
| Descriptive curves | Kaplan-Meier estimator | `survival::survfit(Surv(time, event) ~ group)` |
| Two-group comparison | Log-rank test | `survival::survdiff(Surv(time, event) ~ group)` |
| Multivariable | Cox proportional hazards | `survival::coxph(Surv(time, event) ~ preds)` |
| Time-varying covariates | Extended Cox model | `survival::coxph()` with `tt()` argument |

#### Correlation Analysis

| Outcome type | Predictor type | Method | R Function |
|-------------|---------------|--------|-----------|
| Continuous | Continuous | Pearson (if normal) | `cor.test(x, y, method="pearson")` |
| Continuous | Continuous | Spearman (if non-normal) | `cor.test(x, y, method="spearman")` |
| Ordinal | Any | Spearman | `cor.test(x, y, method="spearman")` |

#### Diagnostic Accuracy

| Metric | R Function |
|--------|-----------|
| Sensitivity, Specificity, PPV, NPV | `caret::confusionMatrix()` |
| ROC curve and AUC | `pROC::roc(outcome, predictor)` |

#### Prediction Model

| Outcome type | Method | R Package |
|-------------|--------|-----------|
| Binary | Logistic regression + calibration | `glm` + `CalibrationCurves` |
| Survival | Cox model + C-statistic | `survival` + `survcomp` |

---

## Multiple Comparison Correction

**Rule: Apply correction whenever n_hypotheses > 1.**

| Situation | Recommended correction | R Function |
|-----------|----------------------|-----------|
| Few planned comparisons | Bonferroni | `p.adjust(p_values, method="bonferroni")` |
| Many comparisons / discovery | Benjamini-Hochberg FDR | `p.adjust(p_values, method="BH")` |
| Family-wise error rate control | Holm | `p.adjust(p_values, method="holm")` |

**Justification field must state:** which correction was applied and why.

---

## Effect Size Selection by Method

| Method | Effect Size Measure | Interpretation thresholds (Cohen) |
|--------|--------------------|---------------------------------|
| t-test | Cohen's d | Small: 0.2, Medium: 0.5, Large: 0.8 |
| Mann-Whitney U | Rank-biserial correlation r | Small: 0.1, Medium: 0.3, Large: 0.5 |
| Chi-square | Cramér's V | Small: 0.1, Medium: 0.3, Large: 0.5 |
| ANOVA | η² (eta-squared) | Small: 0.01, Medium: 0.06, Large: 0.14 |
| Logistic regression | Odds Ratio (OR) + 95% CI | No universal threshold; report with CI |
| Cox regression | Hazard Ratio (HR) + 95% CI | No universal threshold; report with CI |
| Pearson/Spearman | r | Small: 0.1, Medium: 0.3, Large: 0.5 |

---

## Confidence Interval Reporting Standard

- Always report 95% CI unless pre-specified otherwise.
- Report as `[lower, upper]` with same decimal precision as point estimate.
- For ratios (OR, HR, RR): report on original scale, not log scale.
- CI must be consistent with p-value direction (if p<0.05, CI must exclude null).

---

## Sample Size Adequacy Rules

| n per group | Guidance |
|------------|---------|
| < 10 | Extreme caution. Non-parametric methods preferred. Flag as advisory. |
| 10–30 | Small sample. Test normality carefully. |
| ≥ 30 | Central limit theorem generally applicable for continuous outcomes. |
| < 5 per cell | Fisher's exact test mandatory for categorical outcomes. |

---

## Method Justification Template

Every selected method must populate the `justification` field using this structure:

```
Method: [method name]
Rationale:
  - objective: [intent_object.objective value]
  - outcome_type: [intent_object.outcome_type value]
  - predictor_type: [intent_object.predictor_type value]
  - n_per_group: [estimated from dataset_structural_metadata]
  - normality_assumed: [true/false — confirmed by assumption check or sample size rule]
  - multiple_comparisons: [n_hypotheses value and correction applied]
```
