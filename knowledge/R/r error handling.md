# R Error Handling Reference
# Domain: R
# Version: 1.0.0
# Status: Stable
# Consumers: statistics, runtime
# Immutable during execution (AP-014)

## Purpose

Provides the Statistics Agent and Runtime Agent with a catalogue of
common R runtime errors, their root causes, and resolution strategies.
Enables structured error reporting back to the Orchestrator rather than
opaque execution failures.

---

## Error Classification

| Severity | Definition | Pipeline action |
|---------|-----------|----------------|
| `RECOVERABLE` | Wrong argument or data format — fixable by modifying analysis_plan | Retry with corrected specification |
| `DATA_QUALITY` | Data issue that should have been caught by Data Quality Agent | Return to data-quality stage |
| `ASSUMPTION_VIOLATION` | Statistical assumption not met — method switch required | Update analysis_plan method selection |
| `SECURITY` | Forbidden pattern executed | IMMEDIATE_ABORT |
| `UNRECOVERABLE` | Cannot continue without human intervention | Escalate to human |

---

## PART 1 — Model Formula and Variable Errors

### ERR-F01: `object 'var_X' not found`

```
Error in eval(predvars, data, env) : object 'var_1' not found
```

**Cause:** Column name in formula does not exist in the loaded data frame.
**Severity:** RECOVERABLE
**Resolution:**
```r
# Diagnose
names(data)                        # Check actual column names in data
expected_vars <- c("var_1", "var_2")
missing_vars <- setdiff(expected_vars, names(data))
# → Report missing_vars to Orchestrator
```

---

### ERR-F02: `contrasts can be applied only to factors`

```
Error in model.matrix.default(...) :
  contrasts can be applied only to factors with 2 or more levels
```

**Cause:** A categorical variable is stored as character or numeric, not factor.
**Severity:** RECOVERABLE
**Resolution:**
```r
# Fix: convert to factor before model fitting
data[["var_2"]] <- factor(data[["var_2"]])

# Verify
levels(data[["var_2"]])   # Must show ≥ 2 levels
```

---

### ERR-F03: `variable lengths differ`

```
Error in model.frame.default(...) : variable lengths differ
```

**Cause:** Variables have different numbers of rows (data integrity issue).
**Severity:** DATA_QUALITY
**Resolution:**
```r
# Diagnose row counts
sapply(data[, c("var_1", "var_2", "var_3")], length)
# → Return to Data Quality Agent if lengths differ
```

---

### ERR-F04: `factor has new levels`

```
Error in model.frame.default(...) :
  factor var_2 has new levels B
```

**Cause:** Test/validation data has factor levels not seen in training data
(prediction model validation context).
**Severity:** DATA_QUALITY
**Resolution:**
```r
# Align factor levels between train and test
data_test[["var_2"]] <- factor(data_test[["var_2"]],
                                levels = levels(data_train[["var_2"]]))
# Rows with new levels will become NA — document in missing data handling
```

---

## PART 2 — Convergence and Numerical Errors

### ERR-N01: `system is computationally singular`

```
Error in solve.default(...) : system is computationally singular:
  reciprocal condition number = 1.23e-17
```

**Cause:** Perfect or near-perfect multicollinearity among predictors.
**Severity:** ASSUMPTION_VIOLATION
**Resolution:**
```r
library(car)
model_temp <- lm(var_1 ~ var_2 + var_3 + var_4, data = data)
vif_vals <- car::vif(model_temp)
# Remove predictor(s) with VIF ≥ 10 or perfect correlation (cor = 1.0)
high_vif <- names(vif_vals[vif_vals >= 10])
# → Update analysis_plan to remove high_vif predictors; refit model
```

---

### ERR-N02: `glm.fit: fitted probabilities numerically 0 or 1`

```
Warning: glm.fit: fitted probabilities numerically 0 or 1 occurred
```

**Cause:** Complete separation or near-separation in logistic regression.
Occurs with small samples or predictors that perfectly predict the outcome.
**Severity:** ASSUMPTION_VIOLATION
**Resolution:**
```r
# Option 1: Firth penalized logistic regression (handles separation)
library(logistf)
model_firth <- logistf(var_1 ~ var_2 + var_3, data = data)

# Option 2: Check for separation
table(data[["var_1"]], data[["var_2"]])  # Look for 0-cell combinations
# → Switch to logistf if separation detected; document in analysis_plan
```

---

### ERR-N03: lme4 convergence warning

```
Warning: Model failed to converge with max|grad| = 0.00234
Warning: Model is nearly unidentifiable: very large eigenvalue
```

**Cause:** Random effects structure is too complex for the data.
**Severity:** ASSUMPTION_VIOLATION
**Resolution:**
```r
# Step 1: Try alternative optimizer
library(lme4)
model_bobyqa <- lmer(var_1 ~ var_2 + (1 + var_3 | var_4),
                     data    = data,
                     control = lmerControl(optimizer = "bobyqa"))

# Step 2: If still fails, simplify random effects
model_simple <- lmer(var_1 ~ var_2 + (1 | var_4), data = data)

# Step 3: Check if estimates are stable despite warning
all.equal(fixef(model_original), fixef(model_simple), tolerance = 1e-3)
# → Document in analysis_plan which simplification was applied
```

---

### ERR-N04: `non-integer counts in a binomial glm`

```
Warning: non-integer #successes in a binomial glm!
```

**Cause:** Outcome variable is not coded as 0/1 integer (may be 0.0/1.0 float,
or 1/2 coding, or proportion).
**Severity:** DATA_QUALITY
**Resolution:**
```r
# Diagnose
unique(data[["var_1"]])
class(data[["var_1"]])

# Fix: ensure integer 0/1 coding
data[["var_1"]] <- as.integer(data[["var_1"]])
# If coded as 1/2: recode
data[["var_1"]] <- as.integer(data[["var_1"]]) - 1L
```

---

## PART 3 — Data and Missing Value Errors

### ERR-D01: `NA/NaN/Inf in 'x'`

```
Error in cor.test.default(x, y) : NA/NaN/Inf in 'x'
```

**Cause:** Missing or infinite values not handled before analysis.
**Severity:** RECOVERABLE
**Resolution:**
```r
# Diagnose
sum(is.na(data[["var_1"]]))
sum(is.infinite(data[["var_1"]]))

# Fix for complete-case analysis
data_cc <- data[complete.cases(data[, c("var_1", "var_2")]), ]

# Fix for infinite values (replace with NA then handle as missing)
data[["var_1"]][is.infinite(data[["var_1"]])] <- NA
# → Then apply missing data strategy per missing_data_taxonomy.md
```

---

### ERR-D02: `grouping factor must have exactly 2 levels`

```
Error in t.test.formula(var_1 ~ var_2, data = data) :
  grouping factor must have exactly 2 levels
```

**Cause:** Group variable has ≠ 2 levels but t-test was selected.
**Severity:** ASSUMPTION_VIOLATION
**Resolution:**
```r
nlevels(factor(data[["var_2"]]))   # Check actual level count
# If 3+ levels → switch to ANOVA or Kruskal-Wallis
# Update analysis_plan method selection accordingly
```

---

### ERR-D03: `Surv: stop time must be > start time`

```
Error in Surv(var_1, var_2) : stop time must be > start time
```

**Cause:** Time-to-event variable contains 0 or negative values.
**Severity:** DATA_QUALITY
**Resolution:**
```r
# Diagnose
sum(data[["var_1"]] <= 0, na.rm = TRUE)
min(data[["var_1"]], na.rm = TRUE)
# → Flag as DATA_QUALITY issue; return to Data Quality Agent
# Clinical range check for time variables: must be > 0
```

---

### ERR-D04: `all observations have the same value`

```
Error in shapiro.test(x) : all 'x' values are equal
```

**Cause:** No variance in a variable (constant column).
**Severity:** DATA_QUALITY
**Resolution:**
```r
# Diagnose all variables
zero_var <- sapply(data, function(x) length(unique(na.omit(x))) <= 1)
names(zero_var[zero_var])
# → Remove constant variables from analysis; flag in Data Quality report
```

---

## PART 4 — Package and Environment Errors

### ERR-E01: `there is no package called 'X'`

```
Error in library(logistf) : there is no package called 'logistf'
```

**Cause:** Package not installed in the runtime environment.
**Severity:** RECOVERABLE (requires approval)
**Resolution:**
Per spec/runtime.yaml and security.yaml, package installation requires:
1. Security Agent `exec.package_install` permission token
2. Human approval confirmation
Only packages on the approved whitelist in spec/runtime.yaml may be installed.
```r
# Check if package is on approved whitelist before requesting installation
# approved_packages <- c("logistf", "rstatix", ...)
# Do NOT attempt install.packages() — triggers SECURITY error
```

---

### ERR-E02: `could not find function "X"`

```
Error in tbl_summary(...) : could not find function "tbl_summary"
```

**Cause:** Package loaded but function not found — wrong package version
or namespace conflict.
**Resolution:**
```r
# Use explicit namespace to avoid conflicts
gtsummary::tbl_summary(data)      # instead of tbl_summary(data)
survival::coxph(...)              # instead of coxph(...)
car::vif(model)                   # instead of vif(model)
```

---

## PART 5 — Structured Error Output Schema

When an error occurs, Runtime Agent must return a structured error payload:

```r
# Capture error in R script
tryCatch({
  result <- lm(var_1 ~ var_2 + var_3, data = data)
}, error = function(e) {
  error_result <- list(
    execution_id    = Sys.getenv("CIE_EXECUTION_ID"),
    status          = "failed",
    error_code      = "SCRIPT_EXECUTION_FAILED",
    error_message   = conditionMessage(e),
    error_class     = class(e)[1],
    error_call      = deparse(conditionCall(e)),
    severity        = "RECOVERABLE",    # classify per table above
    suggested_fix   = "Check var_n column presence and factor coding",
    session_info    = sessionInfo()
  )
  saveRDS(error_result,
          file.path(Sys.getenv("OUTPUT_DIR"), "execution_error.rds"))
  stop(e)   # Re-raise so Runtime Agent captures non-zero exit code
})
```

---

## Error Resolution Decision Tree

```
R script exits with non-zero code
    │
    ├─ stderr contains "object 'var_N' not found"
    │       → ERR-F01: verify column names in data
    │
    ├─ stderr contains "contrasts can be applied only to factors"
    │       → ERR-F02: convert variable to factor
    │
    ├─ stderr contains "computationally singular"
    │       → ERR-N01: multicollinearity — run VIF, remove predictors
    │
    ├─ stderr contains "fitted probabilities numerically 0 or 1"
    │       → ERR-N02: separation — switch to logistf
    │
    ├─ stderr contains "failed to converge"
    │       → ERR-N03: lme4 convergence — try bobyqa or simplify
    │
    ├─ stderr contains "non-integer counts in a binomial glm"
    │       → ERR-D04: recode outcome to integer 0/1
    │
    ├─ stderr contains "grouping factor must have exactly 2 levels"
    │       → ERR-D02: wrong test for n-group data — switch method
    │
    ├─ stderr contains "there is no package called"
    │       → ERR-E01: request package installation with human approval
    │
    └─ Unknown error
            → Capture full stderr, classify as UNRECOVERABLE
            → Escalate to human via Orchestrator
```
