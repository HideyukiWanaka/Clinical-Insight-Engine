# R Statistical Packages Reference
# Domain: R
# Version: 1.0.0
# Status: Stable
# Consumers: statistics, runtime
# Immutable during execution (AP-014)

## Purpose

Provides the Statistics Agent with the approved R package catalogue,
version constraints, and function-level implementation patterns.
All packages listed are in the approved whitelist (spec/runtime.yaml).

---

## Approved Package Catalogue

### Core Statistical Analysis

| Package | Version (min) | Primary use | Key functions |
|---------|--------------|------------|---------------|
| `base` | R ≥ 4.3.0 | Basic statistics | `t.test()`, `chisq.test()`, `fisher.test()`, `cor.test()`, `lm()`, `glm()`, `aov()` |
| `stats` | R ≥ 4.3.0 | Distributions, tests | `shapiro.test()`, `ks.test()`, `wilcox.test()`, `kruskal.test()`, `p.adjust()` |
| `survival` | ≥ 3.5 | Survival analysis | `Surv()`, `survfit()`, `survdiff()`, `coxph()`, `cox.zph()` |
| `lme4` | ≥ 1.1 | Mixed-effects models | `lmer()`, `glmer()` |
| `car` | ≥ 3.1 | Regression diagnostics | `leveneTest()`, `vif()`, `crPlots()` |
| `lmtest` | ≥ 0.9 | Model testing | `resettest()`, `coeftest()` |
| `pROC` | ≥ 1.18 | ROC / AUC | `roc()`, `auc()`, `ci.auc()`, `plot.roc()` |
| `logistf` | ≥ 1.26 | Firth logistic regression | `logistf()` |

### Data Handling and Tidying

| Package | Version (min) | Primary use | Key functions |
|---------|--------------|------------|---------------|
| `tidyverse` | ≥ 2.0 | Data manipulation | `dplyr`, `tidyr`, `readr`, `purrr` |
| `mice` | ≥ 3.16 | Multiple imputation | `mice()`, `pool()`, `with.mids()` |
| `naniar` | ≥ 1.0 | Missing data analysis | `mcar_test()`, `miss_var_summary()`, `gg_miss_var()` |
| `zoo` | ≥ 1.8 | Time series / LOCF | `na.locf()` |

### Clinical Research Tables

| Package | Version (min) | Primary use | Key functions |
|---------|--------------|------------|---------------|
| `tableone` | ≥ 0.13 | Table 1 generation | `CreateTableOne()`, `print.TableOne()` |
| `finalfit` | ≥ 1.0 | Regression tables | `finalfit()`, `summary_factorlist()` |
| `gtsummary` | ≥ 1.7 | Publication tables | `tbl_summary()`, `tbl_regression()`, `tbl_uvregression()` |

### Visualization (for stats output only)

| Package | Version (min) | Primary use |
|---------|--------------|------------|
| `ggplot2` | ≥ 3.4 | All figures (via visualization agent spec) |
| `survminer` | ≥ 0.4 | Kaplan-Meier plots |
| `forestplot` | ≥ 3.1 | Forest plots |

### Power Analysis

| Package | Version (min) | Primary use | Key functions |
|---------|--------------|------------|---------------|
| `pwr` | ≥ 1.3 | Power and sample size | `pwr.t.test()`, `pwr.chisq.test()`, `pwr.f2.test()` |

### Propensity Score / Weighting

| Package | Version (min) | Primary use | Key functions |
|---------|--------------|------------|---------------|
| `MatchIt` | ≥ 4.5 | Propensity score matching | `matchit()`, `match.data()` |
| `WeightIt` | ≥ 0.14 | Propensity weighting | `weightit()` |
| `survey` | ≥ 4.2 | Weighted analyses | `svydesign()`, `svyglm()` |

---

## R Script Structure Standard (5-Block Template)

Every generated R script must follow this block structure:

```r
# ============================================================
# Block 1: Environment Setup
# ============================================================
set.seed(42)  # Fixed seed — mandatory for reproducibility

# Load required packages
library(tidyverse)
library(tableone)
# ... additional packages

# Record session info for reproducibility
session_info <- sessionInfo()

# ============================================================
# Block 2: Data Loading
# ============================================================
# Load validated dataset (var_n aliases only at this stage)
data <- readRDS(file.path(Sys.getenv("WORKSPACE_DIR"), "validated_data.rds"))

# ============================================================
# Block 3: Assumption Checks
# ============================================================
# Run all assumption checks declared in analysis_plan
# Results stored in assumption_results list

# ============================================================
# Block 4: Primary Analysis
# ============================================================
# Execute selected statistical methods
# Store all results in structured list

# ============================================================
# Block 5: Output Generation
# ============================================================
# Write results to OUTPUT_DIR in schema-conforming format
saveRDS(results, file.path(Sys.getenv("OUTPUT_DIR"), "execution_result.rds"))
```

---

## Forbidden R Patterns

Per spec/runtime.yaml security_and_isolation:

| Pattern | Reason | Alternative |
|---------|--------|-------------|
| `system("...")` | Shell escape | Not permitted |
| `system2(...)` | Shell escape | Not permitted |
| `shell(...)` | Shell escape | Not permitted |
| `Sys.setenv(...)` | Environment mutation | Not permitted |
| `source("external_file.R")` | Uncontrolled code loading | Embed all code in script |
| Hard-coded absolute paths | Breaks reproducibility | Use `Sys.getenv("WORKSPACE_DIR")` |
| `install.packages(...)` | Unapproved installation | Pre-approved packages only |
| `options(warn=-1)` | Suppresses warnings | Never suppress warnings |

---

## var_n Alias System — Column Name Management

### Overview

CIE uses a two-layer column name system to enforce patient privacy
(permissions.yaml: `r_code.restore_variables` required for restoration).

```
Original column name  →  var_n alias  →  R script execution  →  restore  →  output labels
"収縮期血圧"              var_1          lm(var_1 ~ var_2)      Security    "収縮期血圧"
"治療群"                  var_2                                  Agent
```

**Critical rules:**
- Statistics Agent operates on `var_n` aliases ONLY (`r_code.generate_template` permission)
- Security Agent alone holds the alias map and restores original names (`r_code.restore_variables` permission)
- R scripts must use `var_n` throughout execution — never original names
- Output column labels are restored AFTER execution by Security Agent

---

### Stage 1 — Loading data with var_n aliases (Block 2 of 5-block template)

```r
# Block 2: Data Loading
# The RDS file contains var_n column names only — original names are NOT present
data <- readRDS(file.path(Sys.getenv("WORKSPACE_DIR"), "validated_data.rds"))

# Verify expected var_n columns are present
expected_vars <- c("var_1", "var_2", "var_3")   # from analysis_plan
stopifnot(all(expected_vars %in% names(data)))

# NEVER do this — original names must not appear in the script
# data <- rename(data, "収縮期血圧" = var_1)   # FORBIDDEN at this stage
```

---

### Stage 2 — Using var_n in analysis (Block 4 of 5-block template)

All statistical operations reference `var_n` names directly:

```r
# Continuous outcome (var_1) ~ group (var_2)
result_t <- t.test(var_1 ~ var_2, data = data, var.equal = FALSE)

# Logistic regression
model_glm <- glm(var_1 ~ var_2 + var_3 + var_4,
                 data   = data,
                 family = binomial(link = "logit"))

# Survival analysis
cox_fit <- survival::coxph(
  survival::Surv(var_1, var_2) ~ var_3 + var_4,
  data = data, x = TRUE
)

# Accessing a specific column — always by var_n string
col_data <- data[["var_1"]]          # CORRECT
# col_data <- data[["収縮期血圧"]]   # FORBIDDEN
```

---

### Stage 3 — Output with var_n labels (Block 5 of 5-block template)

Results are saved with `var_n` labels. Security Agent restores names after execution.

```r
# Save results with var_n keys — Security Agent will rename after
results <- list(
  execution_id  = Sys.getenv("CIE_EXECUTION_ID"),
  method        = "logistic_regression",
  coefficients  = list(
    var_2 = list(or = exp(coef(model_glm)["var_2"]),
                 ci_lower = exp(confint(model_glm)["var_2", "2.5 %"]),
                 ci_upper = exp(confint(model_glm)["var_2", "97.5 %"]),
                 p_value  = summary(model_glm)$coefficients["var_2", "Pr(>|z|)"]),
    var_3 = list(or = exp(coef(model_glm)["var_3"]),
                 ci_lower = exp(confint(model_glm)["var_3", "2.5 %"]),
                 ci_upper = exp(confint(model_glm)["var_3", "97.5 %"]),
                 p_value  = summary(model_glm)$coefficients["var_3", "Pr(>|z|)"])
  ),
  # var_n_used records which aliases were involved — for Security Agent restoration
  var_n_used    = list(
    outcome   = "var_1",
    predictor = "var_2",
    covariates = c("var_3", "var_4")
  ),
  session_info  = sessionInfo(),
  dataset_hash  = digest::digest(data, algo = "sha256")
)

saveRDS(results, file.path(Sys.getenv("OUTPUT_DIR"), "execution_result.rds"))
```

---

### Stage 4 — Security Agent restoration (post-execution, outside R script)

This stage is performed by the Security Agent in Python, NOT in R:

```python
# Security Agent — r_code.restore_variables permission required
# var_n_alias_map is held exclusively by Security Agent
# Example: {"var_1": "収縮期血圧", "var_2": "治療群", "var_3": "年齢"}

def restore_var_n_labels(results: dict, var_n_alias_map: dict) -> dict:
    """
    Replaces var_n keys with original column names in execution results.
    Called by Security Agent after R script execution completes.
    """
    import copy
    restored = copy.deepcopy(results)

    if "coefficients" in restored:
        restored["coefficients"] = {
            var_n_alias_map.get(k, k): v
            for k, v in restored["coefficients"].items()
        }

    if "var_n_used" in restored:
        var_n_used = restored["var_n_used"]
        restored["var_n_used_restored"] = {
            role: (var_n_alias_map.get(v, v) if isinstance(v, str)
                   else [var_n_alias_map.get(x, x) for x in v])
            for role, v in var_n_used.items()
        }

    return restored
```

---

### Common var_n Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `object 'var_1' not found` | Column not in loaded data | Check `names(data)` and `expected_vars` |
| Original column name in formula | Security breach attempt | Use var_n alias throughout |
| var_n mismatch between intent_object and data | Metadata extraction error | Re-verify dataset_structural_metadata |
| Restoration applied before execution | Security Agent called too early | Restore only after `execution_result.rds` is written |

---

## Output Format Standard

All R script outputs must be saved as structured RDS files conforming to
the expected_output_schema declared by the Statistics Agent:

```r
results <- list(
  execution_id = Sys.getenv("CIE_EXECUTION_ID"),
  method = "independent_samples_t_test",
  primary_result = list(
    test_statistic = t_result$statistic,
    df = t_result$parameter,
    p_value = t_result$p.value,
    mean_difference = diff(t_result$estimate),
    ci_lower = t_result$conf.int[1],
    ci_upper = t_result$conf.int[2],
    effect_size_d = cohen_d_value
  ),
  session_info = sessionInfo(),
  dataset_hash = digest::digest(data, algo="sha256")
)
```
