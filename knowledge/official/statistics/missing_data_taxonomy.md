# Missing Data Taxonomy
# Domain: statistics
# Version: 1.0.0
# Status: Stable
# Consumers: data-quality, statistics
# Immutable during execution (AP-014)

## Purpose

Enables the Data Quality Agent to classify missing data mechanisms and
quantify impact, and guides the Statistics Agent in selecting appropriate
handling strategies for each variable.

---

## Missing Data Mechanism Classification

### MCAR — Missing Completely At Random
- **Definition:** Missingness is unrelated to any variable (observed or unobserved).
- **Test:** Little's MCAR test (`naniar::mcar_test()`)
- **Implication:** Complete case analysis is unbiased (though potentially inefficient).
- **Recommended handling:** Complete case analysis or simple imputation acceptable.

### MAR — Missing At Random
- **Definition:** Missingness depends only on observed variables, not on the missing value itself.
- **Detection:** Compare distributions of observed variables between missing and non-missing groups.
- **Implication:** Multiple imputation or maximum likelihood methods are appropriate.
- **Recommended handling:** Multiple Imputation by Chained Equations (MICE).

### MNAR — Missing Not At Random
- **Definition:** Missingness depends on the unobserved (missing) value itself.
- **Example:** Patients with very high pain scores drop out and their pain score is missing.
- **Detection:** Cannot be confirmed from data alone — requires domain knowledge.
- **Implication:** Standard imputation methods are biased; sensitivity analysis required.
- **Recommended handling:** Document as limitation; consider sensitivity analysis or pattern mixture models.

---

## Data Quality Agent Thresholds and Actions

### Per-Variable Missing Rate

| Missing rate | Classification | Required action |
|-------------|---------------|----------------|
| 0% | Complete | No action |
| > 0% – < 5% | Low | Warning only; document |
| 5% – < 20% | Moderate | Warning; recommend imputation strategy |
| ≥ 20% | High | Critical issue; block pipeline until resolved |
| ≥ 50% | Severe | Critical issue; recommend variable exclusion |

### Per-Row (Subject) Missing Rate

| Missing rate per row | Action |
|---------------------|--------|
| < 10% of columns missing | Include in analysis with appropriate imputation |
| 10% – 30% of columns missing | Advisory; flag row for analyst review |
| > 30% of columns missing | Recommend exclusion; add to `recommended_exclusions` |

---

## Imputation Strategy Selection Guide

### When to use each strategy

| Strategy | Appropriate when | R implementation |
|----------|-----------------|-----------------|
| Complete case analysis | MCAR confirmed; <5% missing | Default (na.rm=TRUE) |
| Mean/median imputation | MCAR; single variable; <5% missing | `tidyr::replace_na()` |
| MICE (Multiple Imputation) | MAR; <40% missing; multiple variables | `mice::mice()` |
| Last observation carried forward (LOCF) | Longitudinal data; regulatory context | `zoo::na.locf()` |
| Sensitivity analysis | MNAR suspected | Run analysis under multiple assumptions |

### MICE Implementation Standard

```r
library(mice)
# m=5: 5 imputed datasets (minimum standard)
# method="pmm" for continuous, "logreg" for binary
imp <- mice(data, m=5, method="pmm", seed=42, printFlag=FALSE)
# Pool results across imputed datasets
fit <- with(imp, lm(outcome ~ predictor))
pooled <- pool(fit)
summary(pooled)
```

**Fixed seed (42) must be declared in R script for reproducibility (STAT-005-A).**

---

## Documentation Requirements

For every variable with missing data, the Statistics Agent must document:

```yaml
variable: "var_n"
missing_rate_pct: 12.5
mechanism_classification: "MAR"
mechanism_evidence: "Missing rate higher in older patients (observed variable)"
handling_strategy: "MICE"
imputation_parameters:
  m: 5
  method: "pmm"
  seed: 42
sensitivity_analysis_planned: false
```

This documentation must appear in `analysis_plan.missing_data_handling`
and be referenced in the Methods section of the manuscript.

---

## Sensitivity Analysis for Missing Data

When MNAR is suspected or missing rate is ≥ 20%, a sensitivity analysis is recommended:

1. **Best-case scenario:** Assume all missing outcomes were favorable.
2. **Worst-case scenario:** Assume all missing outcomes were unfavorable.
3. **Tipping point analysis:** Determine what proportion of missing data would need to be unfavorable to reverse the conclusion.

Document sensitivity analysis results in `unresolved_items` if they materially alter conclusions.
