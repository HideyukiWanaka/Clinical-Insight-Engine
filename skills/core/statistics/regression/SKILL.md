# SKILL: Regression Analysis (Linear and Logistic)
# Skill ID: statistics/regression
# Version: 1.0.0
# Consumers: statistics agent
# Knowledge references:
#   - knowledge/official/statistics/method_selection_guide.md (Regression Analysis)
#   - knowledge/official/statistics/assumption_checklist.md (AC-004, AC-006, AC-007)
#   - knowledge/official/R/multivariate_analysis_reference.md
#   - knowledge/official/R/r_error_handling.md (ERR-N01, ERR-N02, ERR-F02)

## Overview

Reusable procedure for multivariable regression.
Handles both linear regression (continuous outcome) and
logistic regression (binary outcome) with full assumption checking
and correct result extraction.

Applies when:
- `intent_object.objective = "regression_analysis"`
- `intent_object.outcome_type ∈ {"continuous", "categorical_binary"}`

---

## Procedure

### Step 1 — Validate inputs and build formula

```r
outcome_var <- "var_1"
predictor_vars <- c("var_2", "var_3", "var_4")   # from analysis_plan

# Validate all vars present
all_vars <- c(outcome_var, predictor_vars)
stopifnot(all(all_vars %in% names(data)))

# Ensure factor coding for categorical predictors
for (v in predictor_vars) {
  if (!is.numeric(data[[v]])) data[[v]] <- factor(data[[v]])
}

formula_str <- paste(outcome_var, "~", paste(predictor_vars, collapse = " + "))
model_formula <- as.formula(formula_str)
```

### Step 2 — Fit model by outcome type

```r
outcome_type <- "continuous"   # from intent_object.outcome_type

if (outcome_type == "continuous") {
  model <- lm(model_formula, data = data, na.action = na.omit)
  model_family <- "gaussian"

} else if (outcome_type == "categorical_binary") {
  # Check for separation risk (n_events rule of thumb: ≥10 per predictor)
  n_events <- sum(data[[outcome_var]] == 1, na.rm = TRUE)
  epp      <- n_events / length(predictor_vars)   # events per predictor

  if (epp < 10) {
    # Firth penalized logistic — handles separation
    model <- logistf::logistf(model_formula, data = data)
    model_family <- "binomial_firth"
  } else {
    model <- glm(model_formula, data = data,
                 family    = binomial(link = "logit"),
                 na.action = na.omit)
    model_family <- "binomial"
  }
}
```

### Step 3 — Assumption checks

```r
assumption_results <- list()

if (model_family == "gaussian") {
  # AC-001: Normality of residuals
  sw_resid <- shapiro.test(residuals(model))
  assumption_results$normality_residuals <- list(
    p_value = sw_resid$p.value, passed = sw_resid$p.value > 0.05)

  # AC-004: Linearity (RESET test)
  reset_result <- lmtest::resettest(model)
  assumption_results$linearity <- list(
    p_value = reset_result$p.value, passed = reset_result$p.value > 0.05)
}

# AC-006: Multicollinearity (VIF) — for all regression types with ≥2 predictors
if (length(predictor_vars) >= 2 && model_family != "binomial_firth") {
  vif_vals <- car::vif(model)
  assumption_results$vif <- list(
    values = vif_vals,
    max_vif = max(vif_vals),
    passed  = all(vif_vals < 5)
  )
  if (max(vif_vals) >= 10) warning("ERR-N01: Critical multicollinearity detected (VIF ≥ 10)")
}

# AC-007: Influential points
if (model_family == "gaussian") {
  cooks_d <- cooks.distance(model)
  n_influential <- sum(cooks_d > 4 / nrow(model$model))
  assumption_results$influential_points <- list(
    n_influential = n_influential,
    threshold     = 4 / nrow(model$model)
  )
}
```

### Step 4 — Extract results

```r
if (model_family == "gaussian") {
  lm_sum <- summary(model)
  coef_df <- as.data.frame(lm_sum$coefficients)
  ci_mat  <- confint(model, level = 0.95)

  coefficients <- lapply(predictor_vars, function(v) {
    rows <- grep(paste0("^", v), rownames(coef_df), value = TRUE)
    lapply(setNames(rows, rows), function(r) list(
      estimate = coef_df[r, "Estimate"],
      se       = coef_df[r, "Std. Error"],
      t_value  = coef_df[r, "t value"],
      p_value  = coef_df[r, "Pr(>|t|)"],
      ci_lower = ci_mat[r, "2.5 %"],
      ci_upper = ci_mat[r, "97.5 %"]
    ))
  })

  model_fit <- list(
    r_squared     = lm_sum$r.squared,
    adj_r_squared = lm_sum$adj.r.squared,
    f_statistic   = lm_sum$fstatistic[1],
    f_p_value     = pf(lm_sum$fstatistic[1], lm_sum$fstatistic[2],
                       lm_sum$fstatistic[3], lower.tail = FALSE),
    aic           = AIC(model),
    bic           = BIC(model)
  )

} else {
  # Logistic or Firth — report OR + profile likelihood CI
  coefs <- if (model_family == "binomial") coef(model) else coef(model)
  ci    <- if (model_family == "binomial") confint(model) else confint(model)
  pvals <- if (model_family == "binomial") {
    summary(model)$coefficients[, "Pr(>|z|)"]
  } else {
    model$prob
  }

  coefficients <- lapply(predictor_vars, function(v) {
    rows <- grep(paste0("^", v), names(coefs), value = TRUE)
    lapply(setNames(rows, rows), function(r) list(
      or       = exp(coefs[r]),
      ci_lower = exp(ci[r, 1]),
      ci_upper = exp(ci[r, 2]),
      p_value  = pvals[r]
    ))
  })

  mcfadden_r2 <- if (model_family == "binomial")
    1 - (model$deviance / model$null.deviance) else NA

  model_fit <- list(
    mcfadden_r2  = mcfadden_r2,
    aic          = if (model_family=="binomial") AIC(model) else NA,
    n_events     = sum(data[[outcome_var]] == 1, na.rm = TRUE),
    events_per_predictor = epp
  )
}
```

### Step 5 — Structure output

```r
skill_result <- list(
  skill_id       = "statistics/regression",
  model_family   = model_family,
  outcome_var    = outcome_var,
  predictor_vars = predictor_vars,
  n_observations = nrow(model$model),
  coefficients   = coefficients,
  model_fit      = model_fit,
  assumption_checks = assumption_results,
  method_justification = paste0(
    "objective=regression_analysis, outcome_type=", outcome_type,
    ", epp=", if (outcome_type=="categorical_binary") round(epp,1) else "N/A",
    " → ", model_family
  )
)
```

---

## Validation Rules
- All `p_value` values must be in (0, 1)
- For logistic: if `p_value < 0.05`, OR CI must not include 1.0
- For linear: if `p_value < 0.05`, β CI must not include 0
- `model_family = "binomial_firth"` when `epp < 10`
- `vif.max_vif < 5` to pass assumption check (advisory if 5–10, critical if ≥10)
