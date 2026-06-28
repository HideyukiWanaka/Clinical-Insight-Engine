# R mice Package Function Reference
# Domain: R
# Version: 1.0.0
# Status: Stable
# Package version: mice 3.19.0 (2025-12-09, verified against CRAN May 2026)
# Consumers: statistics
# Source: CRAN mice package documentation, amices.org, stefvanbuuren.name/fimd
# Immutable during execution (AP-014)

## Purpose

Provides the Statistics Agent with accurate, argument-level reference for
multiple imputation using the mice package. Covers the complete
mice → with → pool workflow required for CIE clinical analyses.

---

## Core Workflow Overview

```
Raw data with missing values
        ↓
  mice()          → mids object (m imputed datasets stacked)
        ↓
  with()          → mira object (analysis run on each imputed dataset)
        ↓
  pool()          → mipo object (results pooled by Rubin's rules)
        ↓
  summary(pool()) → Final pooled estimates
```

---

## mice() — Multiple Imputation by Chained Equations

```r
imp <- mice(
  data      = data,          # Data frame with missing values
  m         = 5,             # Number of imputed datasets (minimum standard: 5)
  method    = NULL,          # Imputation method per variable (auto-detected if NULL)
  maxit     = 5,             # Number of iterations
  seed      = 42,            # MANDATORY for reproducibility (STAT-005-A)
  printFlag = FALSE          # Suppress iteration output in scripts
)
```

### Arguments
| Argument | Default | Description |
|---------|---------|-------------|
| `m` | 5 | Number of imputed datasets. Use 5 (minimum) to 20 for sensitivity. |
| `method` | auto | Imputation method. Auto-detected per column type. |
| `maxit` | 5 | Iterations per variable. Increase to 20–50 for complex data. |
| `seed` | NA | **Must always be set explicitly** for reproducibility. Use 42. |
| `predictorMatrix` | auto | Control which variables predict which. |
| `printFlag` | TRUE | Set FALSE in scripts to suppress output. |

### Method selection by variable type

| Variable type | Recommended method | Code |
|-------------|-------------------|------|
| Continuous | Predictive mean matching | `"pmm"` (default for numeric) |
| Binary (0/1) | Logistic regression | `"logreg"` (default for factor with 2 levels) |
| Unordered categorical | Polytomous regression | `"polyreg"` |
| Ordered categorical | Proportional odds | `"polr"` |
| Count data | Predictive mean matching | `"pmm"` |

```r
# Explicitly specify methods per variable
methods_vec <- c(
  var_1 = "pmm",      # Continuous
  var_2 = "logreg",   # Binary
  var_3 = "polyreg",  # Nominal categorical
  var_4 = ""          # Empty string = do not impute this variable
)
imp <- mice(data, m = 5, method = methods_vec, seed = 42, printFlag = FALSE)
```

### Excluding variables from imputation
```r
# Method 1 — Set method to empty string
methods_vec["id_column"] <- ""

# Method 2 — Remove from predictorMatrix
pred_matrix <- mice::quickpred(data, mincor = 0.1)
pred_matrix[, "id_column"] <- 0  # Do not use id_column as predictor
pred_matrix["id_column", ] <- 0  # Do not impute id_column
```

### Inspecting imputation quality
```r
# Convergence check — trace plots should show random mixing without trend
plot(imp)

# Missing data pattern
md.pattern(data)

# Distribution of imputed vs observed values
densityplot(imp, ~ var_1)  # Overlay of observed (blue) and imputed (red) per dataset
```

---

## with() — Apply Analysis to Each Imputed Dataset

```r
# Linear regression on each imputed dataset
fits <- with(imp, lm(outcome ~ predictor1 + predictor2))

# Logistic regression
fits <- with(imp, glm(outcome ~ predictor1, family = binomial))

# Cox regression
fits <- with(imp, survival::coxph(survival::Surv(time, status) ~ predictor))

# t-test (via lm equivalent)
fits <- with(imp, lm(outcome ~ group))
```

### Key rule
`with(mids_object, expression)` evaluates `expression` on each of the `m`
imputed datasets and returns a `mira` object.
The expression must be a **model-fitting call**, not a summary or test.

---

## pool() — Pool Results by Rubin's Rules

```r
pooled <- pool(fits)        # Pool mira object
summary(pooled)             # Pooled estimates, SE, t, p-values, CI
```

### Extracting pooled results
```r
pool_summary <- summary(pooled, conf.int = TRUE, conf.level = 0.95)

# Key columns:
# estimate   — pooled point estimate
# std.error  — pooled standard error
# statistic  — t-statistic
# p.value    — pooled p-value (two-sided)
# 2.5 %      — lower 95% CI
# 97.5 %     — upper 95% CI
```

### pool.r.squared() — R² for pooled linear models
```r
pool.r.squared(fits)           # R² and adjusted R²
pool.r.squared(fits, adjusted = TRUE)
```

---

## Complete Implementation Template

```r
library(mice)
library(survival)

# Step 1 — Inspect missing data pattern
md.pattern(data)

# Step 2 — Impute (seed mandatory)
imp <- mice(
  data      = data,
  m         = 5,
  method    = NULL,     # Auto-detect per variable type
  maxit     = 10,       # Increase from default 5 for complex datasets
  seed      = 42,
  printFlag = FALSE
)

# Step 3 — Check convergence
plot(imp)  # Inspect visually; save to OUTPUT_DIR if needed

# Step 4 — Run analysis on each imputed dataset
fits <- with(imp, lm(outcome_var ~ predictor_var + covariate_var))

# Step 5 — Pool results
pooled      <- pool(fits)
pool_result <- summary(pooled, conf.int = TRUE)

# Step 6 — Structure output for CIE output schema
results <- list(
  method              = "multiple_imputation_mice",
  m_datasets          = imp$m,
  maxit               = imp$iteration,
  seed                = 42,
  imputation_methods  = imp$method,
  pooled_estimates    = pool_result,
  fraction_missing    = pool_result$fmi  # Fraction of missing information per term
)
```

---

## complete() — Extract a Single Imputed Dataset

```r
# Extract imputed dataset number 1 (for diagnostics only)
data_imp1 <- complete(imp, action = 1)

# Extract all datasets in long format
data_long <- complete(imp, action = "long", include = TRUE)
# .imp = 0: original data; .imp = 1..m: imputed datasets
```

**Warning:** `complete()` should only be used for diagnostics.
**Never** run the primary analysis on a single `complete()` dataset —
always use `with()` + `pool()`.

---

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| Non-reproducible results | `seed` not set | Always set `seed = 42` |
| Poor convergence | `maxit` too low | Increase to 20–50 for complex data |
| Factor variables not imputed correctly | Variable stored as character, not factor | Convert to factor before `mice()` |
| `pool()` fails | Model doesn't have `tidy()` method | Use models supported by `broom` package |
| Analysis on single dataset | Using `complete(imp, 1)` for primary analysis | Use `with(imp, ...) %>% pool()` |
| Imputing ID or date columns | `method` includes all columns | Set `method["id"] <- ""` |

---

## mice and Survival Analysis

```r
# Cox regression with multiple imputation
fits_cox <- with(imp,
  survival::coxph(survival::Surv(time_var, event_var) ~ predictor_var + covariate_var)
)
pooled_cox <- pool(fits_cox)
summary(pooled_cox, conf.int = TRUE)
# Note: exp(estimate) = pooled HR; exp(conf.int) = pooled 95% CI for HR
```

---

## Version Notes (mice 3.19.0)

- `mice()` now imports `broom` — ensure `broom` is available for `pool()` to work
- Fully Conditional Specification (FCS) is the underlying algorithm
- `method = "pmm"` uses C-level `matcher` function (faster than previous versions)
- `mids` objects are S3 class — use `str(imp)` to inspect structure
