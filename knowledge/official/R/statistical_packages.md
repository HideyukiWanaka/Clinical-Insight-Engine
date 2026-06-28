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
