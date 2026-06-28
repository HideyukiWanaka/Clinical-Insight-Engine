# SKILL: Table 1 Generation (Baseline Characteristics)
# Skill ID: reporting/table-one
# Version: 1.0.0
# Consumers: reporting agent
# Knowledge references:
#   - knowledge/reporting/manuscript_structure_guide.md (Results — Baseline data)
#   - knowledge/R/descriptive_statistics_reference.md
#   - knowledge/R/statistical_packages.md (var_n alias system)

## Overview

Generates a publication-ready Table 1 (baseline characteristics) from
validated dataset metadata and execution results.
Handles continuous/categorical variable display, non-normal variable flagging,
and SMD calculation for propensity-matched studies.

Applies when:
- `intent_object.objective` requires baseline characteristics reporting
- CONSORT item 15, STROBE item 14, TRIPOD+AI item 13a

---

## Procedure

### Step 1 — Classify variables for display

```r
# From dataset_structural_metadata and analysis_plan
all_vars       <- c("var_1", "var_2", "var_3", "var_4", "var_5")
group_var      <- "var_6"    # stratification variable (NULL for overall only)
nonnormal_vars <- c("var_3", "var_5")   # flagged by assumption checks or Data Quality
exact_vars     <- c("var_2")            # low expected cell count → Fisher's exact
factor_vars    <- c("var_2", "var_4")   # categorical variables

# Apply factor conversion
data[factor_vars] <- lapply(data[factor_vars], factor)
```

### Step 2 — Create Table 1 with tableone

```r
library(tableone)

table1 <- CreateTableOne(
  vars       = all_vars,
  strata     = group_var,    # NULL if overall only
  data       = data,
  factorVars = factor_vars,
  addOverall = !is.null(group_var)
)

# Print to capture matrix
table1_matrix <- print(
  table1,
  nonnormal     = nonnormal_vars,
  exact         = exact_vars,
  smd           = !is.null(group_var),   # SMD only for stratified tables
  printToggle   = FALSE,
  noSpaces      = TRUE,
  quote         = FALSE
)
```

### Step 3 — Extract SMD (for propensity-matched studies)

```r
smd_values <- if (!is.null(group_var)) ExtractSmd(table1) else NULL
# Flag variables with SMD > 0.1 as potentially imbalanced
if (!is.null(smd_values)) {
  imbalanced_vars <- rownames(smd_values)[smd_values[, 1] > 0.1]
}
```

### Step 4 — Build footnotes

```r
footnotes <- c(
  "Data are presented as mean ± SD or median [IQR] for continuous variables, and n (%) for categorical variables.",
  if (length(nonnormal_vars) > 0)
    paste("Non-normally distributed variables shown as median [IQR]:", paste(nonnormal_vars, collapse=", ")),
  if (length(exact_vars) > 0)
    paste("Fisher's exact test used for:", paste(exact_vars, collapse=", ")),
  if (!is.null(group_var))
    "P-values from t-test or Mann-Whitney U for continuous variables and chi-square or Fisher's exact test for categorical variables.",
  if (!is.null(smd_values) && length(imbalanced_vars) > 0)
    paste("SMD > 0.1 (potential imbalance):", paste(imbalanced_vars, collapse=", "))
)
```

### Step 5 — Structure output

```r
# Save table matrix to OUTPUT_DIR
output_path <- file.path(Sys.getenv("OUTPUT_DIR"), "table1_matrix.rds")
saveRDS(table1_matrix, output_path)

table_spec <- list(
  table_id   = "T1",
  title      = "Baseline characteristics of study participants",
  source_var = all_vars,
  group_var  = group_var,
  footnotes  = footnotes,
  smd_values = smd_values,
  imbalanced_vars = if (exists("imbalanced_vars")) imbalanced_vars else NULL,
  matrix_path = output_path,
  checklist_items = list(
    CONSORT = "15",
    STROBE  = "14a",
    TRIPOD  = "13a"
  )
)
```

---

## Validation Rules
- All `all_vars` must be present in data
- `nonnormal_vars` must be a subset of `all_vars`
- `exact_vars` must be a subset of `factor_vars`
- Footnotes must include display format description
- If `group_var` is not NULL: SMD must be calculated
- Output matrix must be written to OUTPUT_DIR

---

## Examples

```json
{
  "table_id": "T1",
  "title": "Baseline characteristics of study participants",
  "footnotes": [
    "Data are presented as mean ± SD or median [IQR] for continuous variables, and n (%) for categorical variables.",
    "Non-normally distributed variables shown as median [IQR]: var_3, var_5"
  ]
}
```

---

## Tests

### TEST-T1-01: All vars present in matrix
```r
for (v in all_vars) {
  stopifnot(any(grepl(v, rownames(table1_matrix))))
}
```

### TEST-T1-02: SMD calculated when group_var not NULL
```r
if (!is.null(group_var)) {
  stopifnot(!is.null(result$smd_values))
}
```

### TEST-T1-03: Footnotes contain format description
```r
has_format_note <- any(grepl("mean.*SD|median.*IQR", result$footnotes))
stopifnot(has_format_note)
```

### TEST-T1-04: output file in OUTPUT_DIR
```r
stopifnot(startsWith(result$matrix_path, Sys.getenv("OUTPUT_DIR")))
```
