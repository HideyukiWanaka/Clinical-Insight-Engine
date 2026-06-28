# SKILL: Survival Analysis
# Skill ID: statistics/survival
# Version: 1.0.0
# Consumers: statistics agent
# Knowledge references:
#   - knowledge/official/statistics/method_selection_guide.md (Survival Analysis)
#   - knowledge/official/R/survival_reference.md
#   - knowledge/official/R/r_error_handling.md (ERR-D03)

## Overview

Reusable procedure for time-to-event analysis: Kaplan-Meier estimation,
log-rank test, and Cox proportional hazards regression.

Applies when:
- `intent_object.objective = "survival_analysis"`
- `intent_object.outcome_type = "survival"`

---

## Procedure

### Step 1 — Validate inputs

```r
time_var   <- "var_1"    # role = time_to_event
event_var  <- "var_2"    # role = event_indicator (0=censored, 1=event)
group_var  <- "var_3"    # role = grouping_variable or primary_predictor
covar_vars <- c("var_4", "var_5")   # role = covariate

# Validate time > 0
n_invalid_time <- sum(data[[time_var]] <= 0, na.rm = TRUE)
if (n_invalid_time > 0) stop(paste("ERR-D03:", n_invalid_time, "observations with time ≤ 0"))

# Validate event coding is 0/1
valid_events <- all(data[[event_var]] %in% c(0, 1, NA))
if (!valid_events) stop("ERR-D04: event_var must be coded 0/1")

data[[group_var]] <- factor(data[[group_var]])
```

### Step 2 — Kaplan-Meier + Log-rank

```r
library(survival)
surv_obj <- survival::Surv(data[[time_var]], data[[event_var]])

# KM curves
km_fit <- survival::survfit(
  as.formula(paste("surv_obj ~", group_var)),
  data = data
)
km_summary <- summary(km_fit)

# Log-rank test
lr_result <- survival::survdiff(
  as.formula(paste("surv_obj ~", group_var)),
  data = data
)
lr_p <- 1 - pchisq(lr_result$chisq, df = length(lr_result$n) - 1)
```

### Step 3 — Cox model (with x=TRUE for cox.zph efficiency)

```r
all_covars <- c(group_var, covar_vars)
cox_formula <- as.formula(paste("surv_obj ~", paste(all_covars, collapse = " + ")))

cox_fit <- survival::coxph(
  cox_formula,
  data  = data,
  x     = TRUE,     # required for cox.zph
  model = TRUE      # required if survfit called inside functions
)
```

### Step 4 — PH assumption check (AC-005)

```r
ph_test <- survival::cox.zph(cox_fit, transform = "km")
ph_passed <- all(ph_test$table[, "p"] > 0.05)

# If PH violated: suggest stratification
if (!ph_passed) {
  violated_vars <- rownames(ph_test$table)[ph_test$table[, "p"] <= 0.05]
  ph_recommendation <- paste("Consider strata() for:", paste(violated_vars, collapse=", "))
} else {
  ph_recommendation <- NULL
}
```

### Step 5 — Extract results

```r
cox_summary <- summary(cox_fit)
hr_table    <- cbind(
  HR       = cox_summary$conf.int[, "exp(coef)"],
  CI_lower = cox_summary$conf.int[, "lower .95"],
  CI_upper = cox_summary$conf.int[, "upper .95"],
  p_value  = cox_summary$coefficients[, "Pr(>|z|)"]
)

skill_result <- list(
  skill_id    = "statistics/survival",
  time_var    = time_var,
  event_var   = event_var,
  n_total     = cox_fit$n,
  n_events    = cox_fit$nevent,

  kaplan_meier = list(
    logrank_chisq = lr_result$chisq,
    logrank_df    = length(lr_result$n) - 1,
    logrank_p     = lr_p,
    median_survival = km_summary$table[, "median"]
  ),

  cox_model = list(
    hr_table   = hr_table,
    c_index    = cox_summary$concordance["C"],
    aic        = AIC(cox_fit)
  ),

  assumption_checks = list(
    proportional_hazards = list(
      table   = ph_test$table,
      passed  = ph_passed,
      recommendation = ph_recommendation
    )
  )
)
```

---

## Validation Rules
- `time_var` values must all be > 0
- `event_var` values must be 0 or 1 only
- All HR values must be > 0
- If `logrank_p < 0.05`: HR CI for group_var must not include 1.0
- `c_index` must be in [0.5, 1.0] for a valid model
- `cox.zph` must be run before reporting Cox results

---

## Examples

### Intent Object
```json
{
  "intent_object": {
    "objective": "survival_analysis",
    "outcome_type": "survival",
    "outcome_variables": [
      {"var_n": "var_1", "role": "time_to_event"},
      {"var_n": "var_2", "role": "event_indicator"}
    ],
    "predictor_variables": [
      {"var_n": "var_3", "role": "grouping_variable"},
      {"var_n": "var_4", "role": "covariate"}
    ]
  }
}
```

### Expected Output
```json
{
  "kaplan_meier": {"logrank_p": 0.023, "median_survival": {"A": 24.5, "B": 18.2}},
  "cox_model": {"hr_table": {"var_3": {"HR": 1.84, "CI_lower": 1.09, "CI_upper": 3.11, "p_value": 0.022}},
                "c_index": 0.68}
}
```

---

## Tests

### TEST-S01: PH assumption check always runs
```r
stopifnot(!is.null(result$assumption_checks$proportional_hazards))
stopifnot(!is.null(result$assumption_checks$proportional_hazards$table))
```

### TEST-S02: HR CI excludes 1 when p < 0.05
```r
hr_tab <- result$cox_model$hr_table
for (var in rownames(hr_tab)) {
  if (hr_tab[var, "p_value"] < 0.05) {
    stopifnot(hr_tab[var, "CI_lower"] > 1 || hr_tab[var, "CI_upper"] < 1)
  }
}
```

### TEST-S03: ERR-D03 triggered for time ≤ 0
```r
data_bad <- data; data_bad[[time_var]][1] <- -1
result <- tryCatch(run_survival_skill(data=data_bad, ...), error=function(e) conditionMessage(e))
stopifnot(grepl("ERR-D03", result))
```

### TEST-S04: c_index in valid range
```r
stopifnot(result$cox_model$c_index >= 0.5 && result$cox_model$c_index <= 1.0)
```
