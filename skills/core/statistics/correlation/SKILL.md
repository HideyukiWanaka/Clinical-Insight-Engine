# SKILL: Correlation Analysis
# Skill ID: statistics/correlation
# Version: 1.0.0
# Consumers: statistics agent
# Knowledge references:
#   - knowledge/statistics/method_selection_guide.md (Correlation Analysis)
#   - knowledge/statistics/assumption_checklist.md (AC-001)
#   - knowledge/R/comparison_correlation_reference.md

## Overview

Reusable procedure for correlation analysis between two continuous variables.
Selects Pearson or Spearman based on normality; provides bootstrap CI for Spearman.

Applies when:
- `intent_object.objective = "correlation_analysis"`
- `intent_object.outcome_type = "continuous"`
- `intent_object.predictor_type = "continuous"`

---

## Procedure

### Step 1 — Validate inputs

```r
var_x <- "var_1"
var_y <- "var_2"

stopifnot(var_x %in% names(data), var_y %in% names(data))
stopifnot(is.numeric(data[[var_x]]), is.numeric(data[[var_y]]))

n_complete <- sum(complete.cases(data[, c(var_x, var_y)]))
if (n_complete < 10) warning("Small sample (n<10): interpret correlation with caution")
```

### Step 2 — Normality check → method selection

```r
sw_x <- shapiro.test(data[[var_x]][!is.na(data[[var_x]])])
sw_y <- shapiro.test(data[[var_y]][!is.na(data[[var_y]])])
normality_passed <- sw_x$p.value > 0.05 && sw_y$p.value > 0.05

method <- if (normality_passed) "pearson" else "spearman"
```

### Step 3 — Run correlation test

```r
result_cor <- cor.test(
  x           = data[[var_x]],
  y           = data[[var_y]],
  method      = method,
  alternative = "two.sided",
  conf.level  = 0.95,
  exact       = if (method == "spearman") FALSE else NULL
)

r_value <- as.numeric(result_cor$estimate)
p_value <- result_cor$p.value

# Pearson: CI available directly
# Spearman: CI requires bootstrap (cor.test does not provide CI for Spearman)
if (method == "pearson") {
  ci_lower <- result_cor$conf.int[1]
  ci_upper <- result_cor$conf.int[2]
} else {
  set.seed(42)
  boot_fn <- function(d, idx) cor(d[idx, 1], d[idx, 2], method = "spearman")
  boot_res <- boot::boot(
    data      = data.frame(data[[var_x]], data[[var_y]]),
    statistic = boot_fn,
    R         = 1000
  )
  boot_ci  <- boot::boot.ci(boot_res, type = "perc")
  ci_lower <- boot_ci$percent[4]
  ci_upper <- boot_ci$percent[5]
}
```

### Step 4 — Effect size interpretation

```r
r_abs <- abs(r_value)
interpretation <- dplyr::case_when(
  r_abs < 0.1 ~ "negligible",
  r_abs < 0.3 ~ "weak",
  r_abs < 0.5 ~ "moderate",
  TRUE         ~ "strong"
)
```

### Step 5 — Structure output

```r
skill_result <- list(
  skill_id    = "statistics/correlation",
  method_used = method,
  var_x       = var_x,
  var_y       = var_y,
  n_complete  = n_complete,

  primary_result = list(
    r_value  = r_value,
    p_value  = p_value,
    ci_lower = ci_lower,
    ci_upper = ci_upper,
    ci_method = if (method=="pearson") "fisher_z" else "bootstrap_percentile"
  ),

  effect_size = list(
    measure        = if (method=="pearson") "pearson_r" else "spearman_rho",
    value          = r_value,
    interpretation = interpretation
  ),

  assumption_checks = list(
    normality = list(
      var_x = list(statistic=sw_x$statistic, p_value=sw_x$p.value, passed=sw_x$p.value>0.05),
      var_y = list(statistic=sw_y$statistic, p_value=sw_y$p.value, passed=sw_y$p.value>0.05),
      both_passed = normality_passed
    )
  )
)
```

---

## Validation Rules
- `r_value` must be in [-1, 1]
- `p_value` must be in (0, 1)
- If `p_value < 0.05`: CI must not include 0
- Spearman CI must use bootstrap (set.seed(42) mandatory)
- `method_used = "pearson"` only when both variables pass normality

---

## Examples

```json
{
  "method_used": "spearman",
  "primary_result": {"r_value": 0.42, "p_value": 0.003, "ci_lower": 0.18, "ci_upper": 0.61, "ci_method": "bootstrap_percentile"},
  "effect_size": {"measure": "spearman_rho", "interpretation": "moderate"}
}
```

---

## Tests

### TEST-C01: Spearman selected when normality fails
```r
stopifnot(result$method_used == "spearman")
stopifnot(result$primary_result$ci_method == "bootstrap_percentile")
```

### TEST-C02: Pearson CI is not bootstrap
```r
# When normality passes
stopifnot(result$primary_result$ci_method == "fisher_z")
```

### TEST-C03: CI excludes 0 when p < 0.05
```r
if (result$primary_result$p_value < 0.05) {
  ci_l <- result$primary_result$ci_lower
  ci_u <- result$primary_result$ci_upper
  stopifnot(ci_l > 0 || ci_u < 0)
}
```

### TEST-C04: r_value in [-1, 1]
```r
stopifnot(result$primary_result$r_value >= -1 && result$primary_result$r_value <= 1)
```
