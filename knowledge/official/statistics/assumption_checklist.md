# Statistical Assumption Checklist
# Domain: statistics
# Version: 1.0.0
# Status: Stable
# Consumers: statistics
# Immutable during execution (AP-014)

## Purpose

Provides the Statistics Agent with explicit, executable assumption checks
for every method category. Each check maps to an R implementation and a
pass/fail decision rule that drives method selection or triggers
non-parametric alternatives.

---

## Assumption Check Catalogue

### AC-001 — Normality

**Required for:** t-test, ANOVA, Pearson correlation, linear regression

| n per group | Recommended test | R implementation | Pass criterion |
|------------|-----------------|-----------------|---------------|
| n < 50 | Shapiro-Wilk | `shapiro.test(x)` | p > 0.05 |
| 50 ≤ n < 200 | Kolmogorov-Smirnov | `ks.test(x, "pnorm", mean(x), sd(x))` | p > 0.05 |
| n ≥ 200 | Visual QQ-plot + skewness/kurtosis | `qqnorm(x); qqline(x)` | |

**Decision rule:**
- PASS → proceed with parametric method
- FAIL → switch to non-parametric alternative per method_selection_guide.md
- BORDERLINE (p 0.03–0.07) → set `requires_human_clarification=true`

**R code block:**
```r
normality_result <- shapiro.test(data[[var_n]])
normality_passed <- normality_result$p.value > 0.05
```

---

### AC-002 — Homoscedasticity (Equality of Variances)

**Required for:** Independent samples t-test, one-way ANOVA, linear regression

| Test | R implementation | Pass criterion |
|------|-----------------|---------------|
| Levene's test (robust) | `car::leveneTest(var ~ group)` | p > 0.05 |
| Bartlett's test (sensitive to non-normality) | `bartlett.test(var ~ group)` | p > 0.05 (use only if normality confirmed) |

**Decision rule:**
- t-test: if FAIL → use Welch t-test (`t.test(..., var.equal=FALSE)`) — already the default
- ANOVA: if FAIL → use Welch's ANOVA (`oneway.test(..., var.equal=FALSE)`) or Kruskal-Wallis

---

### AC-003 — Independence of Observations

**Required for:** All methods except paired/repeated-measures designs

**Checks (logical, not statistical):**
1. Confirm no repeated measurements per subject from dataset metadata.
2. Confirm no clustering structure (e.g. patients nested in hospitals).
3. If clustering detected → flag in `assumption_checks_required` and recommend mixed-effects model.

**Decision rule:**
- Independent confirmed → proceed with standard methods
- Clustering suspected → escalate to mixed-effects model; set `requires_human_clarification=true`

---

### AC-004 — Linearity

**Required for:** Linear regression, logistic regression (log-odds linearity)

| Check | R implementation |
|-------|-----------------|
| Scatter plot of residuals vs fitted | `plot(model, which=1)` |
| Component-plus-residual plots | `car::crPlots(model)` |
| RESET test | `lmtest::resettest(model)` |

**Decision rule:**
- Non-linearity detected → consider polynomial terms or spline transformation
- Document transformation in `r_script_specification` and `analysis_plan`

---

### AC-005 — Proportional Hazards

**Required for:** Cox proportional hazards regression

| Check | R implementation | Pass criterion |
|-------|-----------------|---------------|
| Schoenfeld residuals | `survival::cox.zph(model)` | p > 0.05 for each covariate |
| Log-log survival plot | Visual inspection | Parallel lines |

**Decision rule:**
- FAIL → consider time-varying coefficients, stratified Cox model, or restricted time window
- Document in `analysis_plan` with justification

---

### AC-006 — Multicollinearity

**Required for:** Multiple linear regression, logistic regression (≥2 predictors)

| Check | R implementation | Pass criterion |
|-------|-----------------|---------------|
| Variance Inflation Factor (VIF) | `car::vif(model)` | All VIF < 5 (strict: < 3) |
| Correlation matrix of predictors | `cor(predictor_matrix)` | No |r| > 0.8 |

**Decision rule:**
- VIF ≥ 10 → critical multicollinearity; remove or combine predictors before proceeding
- VIF 5–10 → advisory; document and consider regularization

---

### AC-007 — Outlier Influence

**Required for:** Linear regression

| Check | R implementation | Action threshold |
|-------|-----------------|-----------------|
| Cook's distance | `cooks.distance(model)` | > 4/n = influential |
| Leverage (hat values) | `hatvalues(model)` | > 2(p+1)/n = high leverage |
| Studentized residuals | `rstudent(model)` | |value| > 3 = outlier |

**Decision rule:**
- Influential points detected → flag as advisory; do not automatically exclude
- Sensitivity analysis with and without influential points is recommended

---

## Assumption Check Output Schema

Each executed assumption check must produce a structured record:

```yaml
check_id: "AC-001"
method_applied: "shapiro.test"
variable: "var_1"
test_statistic: 0.973
p_value: 0.082
passed: true
decision: "Proceed with parametric method"
r_code_executed: "shapiro.test(data[['var_1']])"
```

---

## Assumption Violation Cascade

When an assumption fails, apply the following cascade in order:

```
Normality fails (AC-001)
  → Switch to non-parametric method
  → Re-run homoscedasticity check (AC-002) if applicable
  → Update analysis_plan.selected_methods
  → Update r_script_specification accordingly
  → Record decision_branch_taken in workflow trace
```

All assumption check results and resulting method changes must be recorded
in the `analysis_plan` before R script generation proceeds.
