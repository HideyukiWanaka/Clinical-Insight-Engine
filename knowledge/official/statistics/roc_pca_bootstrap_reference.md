# R Advanced Methods Reference: ROC, PCA, Bootstrap
# Domain: R
# Version: 1.0.0
# Status: Stable
# Package versions: pROC ≥ 1.18, base R ≥ 4.3.0, boot ≥ 1.3
# Consumers: statistics, visualization
# Source: pROC CRAN documentation, PMC3068975 (Robin et al. 2011),
#         R base documentation, arxiv.org/pdf/2209.01885 (direction warning)
# Immutable during execution (AP-014)

## Purpose

Provides the Statistics Agent with accurate, argument-level implementation
patterns for: ROC curve analysis and AUC (pROC), principal component analysis
(base R prcomp), and bootstrap resampling (boot package).
Covers note.com category 6 advanced methods excluding machine learning.

---

## PART 1 — ROC Curve Analysis (pROC)

### roc() — Build ROC curve

```r
library(pROC)

roc_obj <- roc(
  response  = data$outcome_binary,   # True binary outcome (0/1 or factor)
  predictor = data$biomarker_var,    # Continuous predictor / score
  levels    = c(0, 1),              # MUST specify: c(control_level, case_level)
  direction = "<",                  # MUST specify: "<" = higher score = case (most common)
  ci        = TRUE,                 # Compute 95% CI for AUC
  ci.method = "delong",             # "delong" (default, fast) or "bootstrap"
  percent   = FALSE                 # FALSE = proportions; TRUE = percentages
)
```

### CRITICAL: direction argument

```r
# direction="<" means: higher predictor value → higher probability of being a case
# direction=">" means: lower predictor value → higher probability of being a case

# WRONG — never leave direction=NULL (auto)
roc_bad <- roc(data$outcome, data$predictor)
# Auto-detection biases AUC toward higher values if direction is wrong
# Can produce AUC = 1 - correct_AUC (i.e., upside-down ROC curve)

# CORRECT — always specify explicitly
roc_obj <- roc(data$outcome, data$predictor,
               levels = c(0, 1), direction = "<")
```

### Extracting AUC and CI

```r
auc_value  <- as.numeric(auc(roc_obj))     # Point estimate
ci_auc     <- ci.auc(roc_obj, conf.level = 0.95, method = "delong")
ci_lower   <- ci_auc[1]
ci_upper   <- ci_auc[3]
# ci_auc[2] = point estimate

cat("AUC =", round(auc_value, 3),
    "(95% CI:", round(ci_lower, 3), "–", round(ci_upper, 3), ")\n")
```

### AUC interpretation
| AUC | Discrimination |
|-----|---------------|
| 0.5 | No better than random |
| 0.6 – 0.7 | Poor |
| 0.7 – 0.8 | Acceptable |
| 0.8 – 0.9 | Excellent |
| > 0.9 | Outstanding |

### Optimal cutoff — Youden index

```r
# coords() — extract sensitivity, specificity, threshold at optimal cut
best_cut <- coords(
  roc_obj,
  x        = "best",            # "best" = Youden index maximizing sens+spec
  ret      = c("threshold", "sensitivity", "specificity",
               "ppv", "npv", "accuracy"),
  best.method = "youden"        # "youden" or "closest.topleft"
)
print(best_cut)
```

### Sensitivity and Specificity at specific thresholds

```r
# At a specific threshold value
coords(roc_obj, x = 0.5,
       ret = c("sensitivity", "specificity", "ppv", "npv"),
       transpose = FALSE)

# At fixed sensitivity (e.g., 95% sensitivity)
coords(roc_obj, x = 0.95, input = "sensitivity",
       ret = c("threshold", "specificity"))
```

### Comparing two ROC curves

```r
roc1 <- roc(data$outcome, data$marker1, levels = c(0,1), direction = "<")
roc2 <- roc(data$outcome, data$marker2, levels = c(0,1), direction = "<")

# DeLong's method (paired — same subjects)
roc_test <- roc.test(roc1, roc2, method = "delong", paired = TRUE)
cat("DeLong test: Z =", round(roc_test$statistic, 3),
    ", p =", round(roc_test$p.value, 3))

# AUC difference
auc_diff <- as.numeric(auc(roc1)) - as.numeric(auc(roc2))
```

### Plotting ROC curve (base R)

```r
plot(
  roc_obj,
  print.auc    = TRUE,           # Print AUC on plot
  print.auc.x  = 0.4,
  auc.polygon  = TRUE,           # Fill AUC area
  grid         = TRUE,
  main         = "ROC Curve",
  col          = "#0072B2",      # Okabe-Ito blue
  lwd          = 2,
  legacy.axes  = TRUE            # TRUE = x-axis as 1-specificity (0→1)
)
abline(a = 0, b = 1, lty = 2, col = "grey50")  # Diagonal reference line
```

### Saving ROC plot

```r
pdf(file.path(Sys.getenv("OUTPUT_DIR"), "roc_curve.pdf"),
    width = 6, height = 6)
plot(roc_obj, print.auc = TRUE, col = "#0072B2", lwd = 2,
     main = "ROC Curve", legacy.axes = TRUE)
abline(a = 0, b = 1, lty = 2, col = "grey50")
dev.off()
```

---

## PART 2 — Principal Component Analysis (prcomp)

### prcomp() — PCA (preferred over princomp)

```r
# Prerequisite: use only complete continuous variables
pca_data <- data[, continuous_vars]
pca_data <- na.omit(pca_data)         # PCA requires complete cases

pca_result <- prcomp(
  x      = pca_data,
  center = TRUE,    # Subtract column means (ALWAYS TRUE for clinical data)
  scale. = TRUE     # Divide by SD (ALWAYS TRUE when variables have different units)
)
```

### Extracting PCA results

```r
# Proportion of variance explained per component
var_explained    <- pca_result$sdev^2 / sum(pca_result$sdev^2)
cumvar_explained <- cumsum(var_explained)

# How many components to retain?
# Rule 1 — Elbow in scree plot
# Rule 2 — Components explaining ≥ 80% of variance (cumvar_explained >= 0.80)
# Rule 3 — Kaiser criterion: eigenvalue ≥ 1 (sdev² ≥ 1)
n_components <- sum(pca_result$sdev^2 >= 1)

cat("Components retained (Kaiser):", n_components, "\n")
cat("Variance explained:", round(cumvar_explained[n_components] * 100, 1), "%\n")

# Loadings (variable contributions to each PC)
loadings <- pca_result$rotation      # Matrix: variables × components
# PC scores for each subject
scores   <- pca_result$x             # Matrix: subjects × components
```

### Scree plot

```r
screeplot(pca_result, type = "lines", main = "Scree Plot")
abline(h = 1, lty = 2, col = "red")  # Kaiser criterion line
```

### Biplot (scores + loadings together)

```r
biplot(pca_result, scale = 0, cex = 0.7)
```

### Summary table for reporting

```r
pca_summary <- data.frame(
  Component          = paste0("PC", seq_along(var_explained)),
  Eigenvalue         = round(pca_result$sdev^2, 3),
  Variance_pct       = round(var_explained * 100, 1),
  Cumulative_var_pct = round(cumvar_explained * 100, 1)
)
print(pca_summary)
```

---

## PART 3 — Bootstrap Resampling (boot)

### Purpose in clinical research

| Use case | When |
|---------|------|
| CI for Spearman correlation | `cor.test()` doesn't provide CI for Spearman |
| CI for median difference | No parametric CI available |
| CI for AUC (alternative to DeLong) | Small samples |
| CI for complex statistics (NNT, etc.) | No closed-form CI |
| Model validation (bootstrap internal validation) | Prediction model optimism correction |

### boot() — Basic bootstrap framework

```r
library(boot)
set.seed(42)  # MANDATORY for reproducibility (STAT-005-A)

# Define statistic function — must accept (data, indices)
stat_function <- function(data, indices) {
  d <- data[indices, ]              # Resample rows
  cor(d$var_1, d$var_2, method = "spearman")
}

# Run bootstrap
boot_result <- boot(
  data      = data[, c("var_1", "var_2")],
  statistic = stat_function,
  R         = 1000,                 # Number of bootstrap resamples (≥1000 for CI)
  sim       = "ordinary"            # "ordinary" = random sampling with replacement
)

# Extract CI
boot_ci <- boot.ci(
  boot_result,
  conf  = 0.95,
  type  = "perc"    # "perc" = percentile; "bca" = bias-corrected (preferred for small n)
)
ci_lower <- boot_ci$percent[4]
ci_upper <- boot_ci$percent[5]
```

### Bootstrap for median difference

```r
set.seed(42)
median_diff_fn <- function(data, indices) {
  d <- data[indices, ]
  median(d$var_1[d$group == "A"]) - median(d$var_1[d$group == "B"])
}

boot_med <- boot(data, median_diff_fn, R = 1000)
boot.ci(boot_med, type = "bca")   # BCa preferred for asymmetric distributions
```

### Bootstrap internal validation (for prediction models)

```r
set.seed(42)
model_stat <- function(data, indices) {
  d     <- data[indices, ]
  model <- glm(outcome ~ pred1 + pred2, data = d, family = binomial)
  pred  <- predict(model, type = "response")
  as.numeric(pROC::auc(pROC::roc(d$outcome, pred,
                                   levels = c(0,1), direction = "<")))
}

boot_auc <- boot(data, model_stat, R = 200)
# Apparent AUC (no bootstrap correction)
apparent_auc <- boot_auc$t0
# Bootstrap-corrected AUC (optimism-corrected)
mean_boot_auc <- mean(boot_auc$t)
optimism      <- mean_boot_auc - apparent_auc
corrected_auc <- apparent_auc - optimism
```

---

## PART 4 — Complete Advanced Analysis Pipeline

```r
library(pROC)
library(boot)

# ROC Analysis
roc_obj  <- roc(data$outcome, data$biomarker,
                 levels = c(0, 1), direction = "<", ci = TRUE)
auc_val  <- as.numeric(auc(roc_obj))
ci_auc   <- ci.auc(roc_obj)
best_cut <- coords(roc_obj, "best", ret = c("threshold", "sensitivity",
                                             "specificity", "ppv", "npv"))

# PCA
pca_result <- prcomp(data[, continuous_vars], center = TRUE, scale. = TRUE)
var_exp    <- pca_result$sdev^2 / sum(pca_result$sdev^2)

# Structure output
advanced_results <- list(
  execution_id = Sys.getenv("CIE_EXECUTION_ID"),

  roc = list(
    auc          = auc_val,
    ci_lower     = ci_auc[1],
    ci_upper     = ci_auc[3],
    optimal_cut  = best_cut,
    direction    = "<"          # Always record direction used
  ),

  pca = list(
    n_components     = sum(pca_result$sdev^2 >= 1),
    variance_explained = var_exp,
    cumulative_var   = cumsum(var_exp),
    loadings         = pca_result$rotation
  ),

  session_info = sessionInfo()
)

saveRDS(advanced_results,
        file.path(Sys.getenv("OUTPUT_DIR"), "advanced_results.rds"))
```

---

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| AUC = 1 - correct_AUC | `direction` auto-detected incorrectly | Always set `direction="<"` or `">"` explicitly |
| Biased AUC from `direction=NULL` | pROC auto-selects based on medians | Specify `direction` and verify with `plot(roc_obj)` |
| PCA not scaled | Variables on different units | Always set `scale.=TRUE` |
| PCA on non-numeric columns | Character/factor columns in matrix | Subset to continuous variables only |
| `boot()` non-reproducible | No seed set | Always `set.seed(42)` before `boot()` |
| Too few bootstrap resamples | R < 200 | Use R ≥ 1000 for CI, R ≥ 200 for internal validation |
| BCa CI fails | Extreme statistics | Fall back to `type="perc"` and report |
