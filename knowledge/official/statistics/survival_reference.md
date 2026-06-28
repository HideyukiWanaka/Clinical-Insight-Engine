# R survival Package Function Reference
# Domain: R
# Version: 1.0.0
# Status: Stable
# Package version: survival ≥ 3.5.0 (verified against May 2026 CRAN release)
# Consumers: statistics, visualization
# Source: CRAN survival package documentation, rdrr.io, UCLA OARC (2025)
# Immutable during execution (AP-014)

## Purpose

Provides the Statistics Agent with accurate, argument-level reference for the
survival package functions used in CIE clinical analysis workflows. Covers
critical behaviors that are not obvious from function names alone.

---

## Surv() — Create a Survival Object

```r
Surv(time, event)                          # Right-censored (most common)
Surv(time, time2, event, type="interval")  # Interval censoring
Surv(time, event, type="counting")         # Start-stop format for time-varying covariates
```

### Arguments
| Argument | Type | Description |
|---------|------|-------------|
| `time` | numeric | Follow-up duration. Must be ≥ 0. |
| `event` | numeric/logical | Event indicator. **0 = censored, 1 = event.** Logical TRUE/FALSE also accepted. |
| `time2` | numeric | End of interval (interval censoring only) |
| `type` | character | `"right"` (default), `"left"`, `"interval"`, `"counting"` |

### Critical rules
- Event coding must be 0/1 or TRUE/FALSE. Never use 1/2 coding directly (recode first).
- `Surv()` appears on the **left-hand side** of the formula: `Surv(time, status) ~ predictors`

```r
# CORRECT
lung$status_recoded <- lung$status - 1  # Recode 1=censored,2=dead → 0=censored,1=dead
Surv(lung$time, lung$status_recoded)

# INCORRECT — never pass status=2 directly as event indicator
Surv(lung$time, lung$status)  # status=1 means censored in lung dataset!
```

---

## survfit() — Kaplan-Meier and Predicted Survival Curves

### From formula (Kaplan-Meier)
```r
survfit(formula = Surv(time, status) ~ group, data = data)
survfit(Surv(time, status) ~ 1, data = data)  # Overall survival, no groups
```

### From coxph object (predicted curves)
```r
# S3 method for coxph — ALWAYS use newdata argument
survfit(formula = cox_model, newdata = new_data_frame)
```

### Critical rule — newdata is mandatory for interpretable Cox curves
When called on a `coxph` object **without** `newdata`, survfit computes a curve
for a pseudo-subject with covariate values equal to the **column means** of the
original data. This rarely has clinical meaning.

```r
# CORRECT — specify the patient profiles you want
new_data <- data.frame(
  group = c("A", "B"),
  age   = c(mean(data$age), mean(data$age))
)
surv_curves <- survfit(cox_model, newdata = new_data)

# INCORRECT — produces a meaningless average-patient curve
surv_curves <- survfit(cox_model)  # Avoid unless intentional
```

### Critical rule — model=TRUE required inside functions
```r
# If survfit(cox_model) is called inside another function:
cox_model <- coxph(Surv(time, status) ~ age, data = data, model = TRUE)
survfit(cox_model)  # model=TRUE prevents model.frame() evaluation error
```

### Key arguments
| Argument | Default | Description |
|---------|---------|-------------|
| `conf.int` | 0.95 | Confidence interval level |
| `conf.type` | `"log"` | CI transformation: `"log"`, `"log-log"`, `"plain"`, `"none"` |
| `se.fit` | TRUE | Whether to compute standard errors |

---

## survdiff() — Log-Rank Test

```r
survdiff(formula = Surv(time, status) ~ group, data = data)
survdiff(Surv(time, status) ~ group, data = data, rho = 1)  # Peto-Peto test
```

### Arguments
| Argument | Default | Description |
|---------|---------|-------------|
| `rho` | 0 | 0 = log-rank (default), 1 = Wilcoxon/Peto-Peto (weights early events more) |

### Extracting p-value
```r
diff_result <- survdiff(Surv(time, status) ~ group, data = data)
p_value <- 1 - pchisq(diff_result$chisq, df = length(diff_result$n) - 1)
```

---

## coxph() — Cox Proportional Hazards Model

```r
coxph(formula = Surv(time, status) ~ predictor1 + predictor2,
      data    = data,
      ties    = "efron",   # Tie handling
      x       = FALSE,     # Set TRUE if cox.zph() will be called (saves computation)
      model   = FALSE)     # Set TRUE if survfit() called inside a function
```

### Arguments
| Argument | Default | Description |
|---------|---------|-------------|
| `ties` | `"efron"` | Tie-handling: `"efron"` (default, recommended), `"breslow"`, `"exact"` |
| `x` | FALSE | Store the model matrix (required for `cox.zph()` efficiency) |
| `model` | FALSE | Store the model frame (required when `survfit()` called inside a function) |

### Extracting results
```r
cox_fit    <- coxph(Surv(time, status) ~ age + sex, data = data)
cox_summary <- summary(cox_fit)

# Hazard ratios and 95% CI
hr_table <- cbind(
  HR       = round(cox_summary$coefficients[, "exp(coef)"],   3),
  CI_lower = round(cox_summary$conf.int[, "lower .95"],       3),
  CI_upper = round(cox_summary$conf.int[, "upper .95"],       3),
  p_value  = round(cox_summary$coefficients[, "Pr(>|z|)"],    4)
)

# C-index (concordance)
concordance_value <- cox_summary$concordance["C"]
```

### Stratified Cox model (when PH assumption fails for a variable)
```r
coxph(Surv(time, status) ~ age + strata(sex), data = data)
```

---

## cox.zph() — Test Proportional Hazards Assumption

```r
cox.zph(fit,
        transform = "km",    # Time transformation
        terms     = TRUE,    # Test by term (not individual coefficient)
        global    = TRUE)    # Include global test
```

### Arguments
| Argument | Default | Options | Description |
|---------|---------|---------|-------------|
| `transform` | `"km"` | `"km"`, `"rank"`, `"identity"` | Time scale transformation for Schoenfeld residuals |
| `terms` | TRUE | TRUE/FALSE | TRUE = test per model term; FALSE = test per coefficient |
| `global` | TRUE | TRUE/FALSE | Whether to include global chi-square test |

### Interpreting output
```r
ph_test <- cox.zph(cox_fit)
print(ph_test)
# Output: chisq, df, p per variable + GLOBAL
# H0: covariate effect is constant over time (proportional)
# p < 0.05 → PH assumption VIOLATED for that variable
```

### Critical note on `terms` argument
When a categorical variable has multiple dummy coefficients, `terms=TRUE` (default)
gives a single omnibus test per variable. Use `terms=FALSE` only when individual
coefficient-level tests are needed.

```r
# Plot Schoenfeld residuals to visually inspect PH assumption
plot(ph_test)                    # All variables
plot(ph_test, var = "age")       # Specific variable — horizontal line = PH holds
```

### Decision cascade when PH violated
```r
# Option 1 — Stratify by violating variable
coxph(Surv(time, status) ~ age + strata(sex), data = data)

# Option 2 — Time-varying coefficient (tt() term)
coxph(Surv(time, status) ~ age + tt(sex), data = data,
      tt = function(x, t, ...) x * log(t))

# Option 3 — Restrict analysis to time window where PH holds
data_restricted <- data[data$time <= cutoff, ]
```

---

## Complete Survival Analysis Pipeline

```r
library(survival)
library(survminer)

# 1. Create survival object
surv_obj <- Surv(data$time_var, data$event_var)

# 2. Kaplan-Meier
km_fit <- survfit(Surv(time_var, event_var) ~ group_var, data = data)

# 3. Log-rank test
diff_result <- survdiff(Surv(time_var, event_var) ~ group_var, data = data)
logrank_p   <- 1 - pchisq(diff_result$chisq, df = length(diff_result$n) - 1)

# 4. Cox model — set x=TRUE for cox.zph efficiency
cox_fit <- coxph(Surv(time_var, event_var) ~ group_var + covariate,
                 data = data, x = TRUE)

# 5. PH assumption check
ph_test <- cox.zph(cox_fit)

# 6. Predicted survival curves by group (ALWAYS use newdata)
new_data    <- data.frame(group_var = levels(data$group_var),
                           covariate = mean(data$covariate))
surv_curves <- survfit(cox_fit, newdata = new_data)

# 7. Extract results for output schema
cox_summary <- summary(cox_fit)
results <- list(
  hr         = cox_summary$conf.int[, c("exp(coef)", "lower .95", "upper .95")],
  p_values   = cox_summary$coefficients[, "Pr(>|z|)"],
  logrank_p  = logrank_p,
  c_index    = cox_summary$concordance["C"],
  ph_test    = ph_test$table,
  n_events   = cox_fit$nevent
)
```

---

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| Wrong event coding | `status=1` meaning censored in some datasets | Always recode to 0=censored, 1=event before `Surv()` |
| Meaningless Cox curve | `survfit(cox_model)` without `newdata` | Always provide `newdata` |
| `survfit()` inside function fails | `model.frame()` non-standard evaluation | Add `model=TRUE` to `coxph()` call |
| `cox.zph()` slow | `x=FALSE` (default) | Set `x=TRUE` in `coxph()` |
| PH assumption not checked | Omitting `cox.zph()` | Always run before interpreting Cox results |
