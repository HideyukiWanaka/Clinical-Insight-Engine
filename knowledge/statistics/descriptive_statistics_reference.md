# R Descriptive Statistics Reference
# Domain: R
# Version: 1.0.0
# Status: Stable
# Package versions: tableone ≥ 0.13, gtsummary ≥ 1.7 (verified against CRAN 2025-2026)
# Consumers: statistics, reporting
# Source: RDocumentation tableone, danieldsjoberg.com/gtsummary (2025)
# Immutable during execution (AP-014)

## Purpose

Provides the Statistics Agent with accurate implementation patterns for
descriptive statistics and Table 1 generation using tableone and gtsummary.
Covers argument-level details, variable type handling, and result extraction.

---

## Variable Type Classification (Pre-processing Rule)

Before any descriptive analysis, classify all variables:

```r
# Convert all categorical variables to factor BEFORE analysis
# tableone and gtsummary both depend on R type for auto-detection

vars_categorical <- c("var_2", "var_5", "var_8")  # from intent_object
vars_continuous  <- c("var_1", "var_3", "var_4")

data[vars_categorical] <- lapply(data[vars_categorical], factor)
# Continuous variables: leave as numeric — never convert to character
```

---

## PART 1 — tableone Package

### CreateTableOne() — Table 1 Generation

```r
library(tableone)

table1 <- CreateTableOne(
  vars      = c("var_1", "var_2", "var_3", "var_4"),  # Variables to include
  strata    = "group_var",    # Grouping variable (omit for overall summary)
  data      = data,
  factorVars = vars_categorical,  # Explicit categorical declaration (belt-and-suspenders)
  addOverall = TRUE           # Add overall column when strata is specified
)
```

### print.TableOne() — Controlling output format

```r
# Standard print with test selection
print(table1,
  nonnormal = c("var_1", "var_3"),  # Variables to show as median [IQR]
  exact     = c("var_2"),           # Variables to use Fisher's exact test
  smd       = TRUE,                 # Show standardized mean differences
  showAllLevels = FALSE,            # Show all factor levels (TRUE for binary vars)
  cramVars  = "var_2",              # Show both levels for a 2-level factor
  quote     = FALSE,
  noSpaces  = TRUE                  # Remove spaces (for Word compatibility)
)
```

### Key argument rules
- Variables NOT listed in `nonnormal` → shown as Mean ± SD with t-test/ANOVA p-value
- Variables listed in `nonnormal` → shown as Median [IQR] with Wilcoxon/Kruskal p-value
- Variables listed in `exact` → Fisher's exact test instead of chi-square
- `smd = TRUE` → Standardized Mean Difference (useful for propensity score assessment)

### Extracting SMD values programmatically
```r
smd_values <- ExtractSmd(table1)
```

### Converting to data frame for output schema
```r
table1_df <- print(table1,
  nonnormal     = vars_nonnormal,
  exact         = vars_exact,
  smd           = TRUE,
  printToggle   = FALSE,   # Suppress console print, return matrix
  noSpaces      = TRUE
)
# table1_df is a character matrix — convert to data frame
table1_output <- as.data.frame(table1_df)
```

---

## PART 2 — gtsummary Package

### tbl_summary() — Flexible Summary Table

```r
library(gtsummary)

# Basic overall summary
tbl <- data |>
  tbl_summary(
    include  = c(var_1, var_2, var_3),     # Variables to include
    by       = group_var,                   # Grouping variable (omit for overall)
    missing  = "ifany",                     # "no", "ifany" (default), "always"
    digits   = list(all_continuous() ~ 1,   # Decimal places
                    all_categorical() ~ 0),
    statistic = list(
      all_continuous()  ~ "{mean} ({sd})",          # Parametric default
      all_categorical() ~ "{n} ({p}%)"
    )
  ) |>
  add_p(
    test = list(
      all_continuous()  ~ "t.test",      # or "wilcox.test" for non-normal
      all_categorical() ~ "chisq.test"   # or "fisher.test"
    ),
    pvalue_fun = label_style_pvalue(digits = 3)
  ) |>
  add_overall() |>
  add_n() |>
  bold_labels()
```

### Statistic options for statistic= argument

| Variable type | Statistic string | Output |
|-------------|-----------------|--------|
| Continuous (parametric) | `"{mean} ({sd})"` | Mean (SD) |
| Continuous (non-parametric) | `"{median} ({p25}, {p75})"` | Median (Q1, Q3) |
| Continuous (range) | `"{min}, {max}"` | Min, Max |
| Categorical | `"{n} ({p}%)"` | n (%) |
| Dichotomous | `"{n} ({p}%)"` | n (%) — shown on single row |

### Selecting variables by type in gtsummary
```r
# Use tidyselect helpers within gtsummary
all_continuous()       # All numeric variables
all_categorical()      # All factor/character variables
all_dichotomous()      # All 2-level factors
starts_with("var_")    # Variables starting with "var_"
```

### Saving gtsummary table to file
```r
# Save as Word document (for manuscript)
tbl |>
  as_flex_table() |>
  flextable::save_as_docx(
    path = file.path(Sys.getenv("OUTPUT_DIR"), "table1.docx")
  )

# Save as RDS for CIE output schema
saveRDS(tbl, file.path(Sys.getenv("OUTPUT_DIR"), "table1_gtsummary.rds"))
```

---

## PART 3 — Base R Descriptive Statistics

### Summary statistics by group

```r
# Continuous variables — by group
by(data$var_1, data$group_var, function(x) {
  c(n      = sum(!is.na(x)),
    mean   = mean(x, na.rm = TRUE),
    sd     = sd(x, na.rm = TRUE),
    median = median(x, na.rm = TRUE),
    q1     = quantile(x, 0.25, na.rm = TRUE),
    q3     = quantile(x, 0.75, na.rm = TRUE),
    min    = min(x, na.rm = TRUE),
    max    = max(x, na.rm = TRUE))
})

# Categorical variables — frequency table
table(data$var_2, data$group_var)
prop.table(table(data$var_2, data$group_var), margin = 2) * 100  # Column %
```

### Missing data summary
```r
library(naniar)

# Per-variable missing summary
miss_var_summary(data)

# Missing data pattern
md.pattern(data)  # requires mice

# Test MCAR (Little's test)
mcar_test_result <- naniar::mcar_test(data)
# p < 0.05 → reject MCAR (data is MAR or MNAR)
```

---

## Standard Output Schema for Descriptive Results

```r
descriptive_results <- list(
  execution_id    = Sys.getenv("CIE_EXECUTION_ID"),
  method          = "descriptive_statistics",
  n_total         = nrow(data),
  n_per_group     = table(data$group_var),
  table1_matrix   = table1_output,       # From tableone
  missing_summary = miss_var_summary(data),
  session_info    = sessionInfo()
)
saveRDS(descriptive_results,
        file.path(Sys.getenv("OUTPUT_DIR"), "descriptive_results.rds"))
```
