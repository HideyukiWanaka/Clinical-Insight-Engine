# R Two-Group Comparison & Correlation Reference
# Domain: R
# Version: 1.0.0
# Status: Stable
# Package versions: base R ≥ 4.3.0, rstatix (2025-10-18)
# Consumers: statistics
# Source: R base documentation, rstatix CRAN (2025), stat.ethz.ch/R-manual
# Immutable during execution (AP-014)

## Purpose

Provides the Statistics Agent with accurate, argument-level implementation
patterns for two-group comparisons and correlation analyses, including
correct result extraction and effect size computation.

---

## PART 1 — Continuous Outcome, Two Groups

### t.test() — Independent Samples (Welch, default)

```r
result <- t.test(
  formula     = var_1 ~ group_var,
  data        = data,
  var.equal   = FALSE,        # FALSE = Welch t-test (DEFAULT, recommended)
  alternative = "two.sided",  # "two.sided", "less", "greater"
  conf.level  = 0.95
)
```

### Critical: var.equal behavior
- `var.equal = FALSE` (default) → **Welch t-test** — does NOT assume equal variances. Always use this.
- `var.equal = TRUE` → Student t-test — only use when `leveneTest()` confirms homoscedasticity.

### Extracting results from t.test()
```r
# All key values
t_stat      <- result$statistic          # t-value
df          <- result$parameter          # Degrees of freedom (non-integer for Welch)
p_value     <- result$p.value
mean_group1 <- result$estimate[1]        # Mean of group 1
mean_group2 <- result$estimate[2]        # Mean of group 2
mean_diff   <- diff(result$estimate)     # Mean difference (group1 - group2)
ci_lower    <- result$conf.int[1]        # Lower 95% CI of mean difference
ci_upper    <- result$conf.int[2]        # Upper 95% CI of mean difference
```

### Effect size — Cohen's d
```r
# Compute Cohen's d manually (no additional package required)
n1   <- sum(data$group_var == levels(data$group_var)[1], na.rm = TRUE)
n2   <- sum(data$group_var == levels(data$group_var)[2], na.rm = TRUE)
sd1  <- sd(data$var_1[data$group_var == levels(data$group_var)[1]], na.rm = TRUE)
sd2  <- sd(data$var_1[data$group_var == levels(data$group_var)[2]], na.rm = TRUE)
pooled_sd <- sqrt(((n1 - 1) * sd1^2 + (n2 - 1) * sd2^2) / (n1 + n2 - 2))
cohens_d  <- abs(mean_diff) / pooled_sd
# Interpretation: Small < 0.2, Medium 0.2–0.5, Large ≥ 0.8
```

---

### wilcox.test() — Mann-Whitney U (Non-parametric)

```r
result_mw <- wilcox.test(
  formula     = var_1 ~ group_var,
  data        = data,
  paired      = FALSE,        # FALSE = Mann-Whitney U; TRUE = Wilcoxon signed-rank
  exact       = NULL,         # NULL = auto (use exact when n < 50, no ties)
  correct     = TRUE,         # Continuity correction
  conf.int    = TRUE,         # Compute Hodges-Lehmann CI of location shift
  conf.level  = 0.95,
  alternative = "two.sided"
)
```

### Extracting results from wilcox.test()
```r
w_stat   <- result_mw$statistic      # W statistic
p_value  <- result_mw$p.value
# Hodges-Lehmann location shift estimate and CI (only when conf.int=TRUE)
hl_est   <- result_mw$estimate       # Location shift estimate
ci_lower <- result_mw$conf.int[1]
ci_upper <- result_mw$conf.int[2]
```

### Effect size — Rank-biserial correlation r
```r
# r = Z / sqrt(N), where N = total sample size
# Compute Z from W statistic
n1 <- sum(data$group_var == levels(data$group_var)[1], na.rm = TRUE)
n2 <- sum(data$group_var == levels(data$group_var)[2], na.rm = TRUE)
N  <- n1 + n2
# Mean and SD of W under H0
mu_W  <- n1 * n2 / 2
sd_W  <- sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
Z     <- (result_mw$statistic - mu_W) / sd_W
r_rb  <- abs(Z) / sqrt(N)
# Interpretation: Small < 0.1, Medium 0.3–0.5, Large ≥ 0.5
```

---

### Paired comparisons

```r
# Paired t-test
result_paired <- t.test(data$var_pre, data$var_post,
                        paired = TRUE, conf.level = 0.95)

# Wilcoxon signed-rank (paired non-parametric)
result_sr <- wilcox.test(data$var_pre, data$var_post,
                          paired = TRUE, conf.int = TRUE)
```

---

## PART 2 — Categorical Outcome, Two Groups

### chisq.test() — Chi-square Test

```r
ct <- table(data$group_var, data$outcome_var)  # Always create table first
result_chi <- chisq.test(ct, correct = FALSE)  # correct=FALSE for 2×2 without Yates
```

### Decision rule: chi-square vs Fisher's exact
```r
# Check expected cell counts
result_chi$expected
# If ANY expected cell < 5 → use Fisher's exact test instead
any(result_chi$expected < 5)  # TRUE → switch to fisher.test()
```

### fisher.test() — Fisher's Exact Test
```r
result_fisher <- fisher.test(
  ct,
  alternative = "two.sided",
  conf.int    = TRUE,
  conf.level  = 0.95
)
# For tables larger than 2×2:
result_fisher <- fisher.test(ct, simulate.p.value = TRUE, B = 10000)
```

### Extracting results
```r
# Chi-square
chi_stat  <- result_chi$statistic
df_chi    <- result_chi$parameter
p_chi     <- result_chi$p.value

# Fisher
or_fisher <- result_fisher$estimate    # Odds ratio (2×2 only)
ci_lower  <- result_fisher$conf.int[1]
ci_upper  <- result_fisher$conf.int[2]
p_fisher  <- result_fisher$p.value
```

### Effect size — Cramér's V
```r
# Cramér's V for chi-square
n_total  <- sum(ct)
k        <- min(nrow(ct), ncol(ct))   # min(rows, cols)
cramers_v <- sqrt(result_chi$statistic / (n_total * (k - 1)))
# Interpretation: Small < 0.1, Medium 0.3, Large ≥ 0.5
```

---

## PART 3 — Correlation Analysis

### cor.test() — Pearson and Spearman

```r
# Pearson (parametric — requires normality)
result_pearson <- cor.test(
  x           = data$var_1,
  y           = data$var_2,
  method      = "pearson",
  alternative = "two.sided",
  conf.level  = 0.95
)

# Spearman (non-parametric — use when normality fails)
result_spearman <- cor.test(
  x      = data$var_1,
  y      = data$var_2,
  method = "spearman",
  exact  = FALSE  # Set FALSE to avoid exact p-value computation with ties
)
```

### Decision rule: Pearson vs Spearman
```r
# Step 1 — Test normality of both variables
sw_x <- shapiro.test(data$var_1)
sw_y <- shapiro.test(data$var_2)

# Step 2 — Select method
method <- if (sw_x$p.value > 0.05 && sw_y$p.value > 0.05) "pearson" else "spearman"
result_cor <- cor.test(data$var_1, data$var_2, method = method)
```

### Extracting results from cor.test()
```r
r_value  <- result_cor$estimate       # Correlation coefficient
p_value  <- result_cor$p.value
# 95% CI (available for Pearson only — not Spearman)
ci_lower <- result_cor$conf.int[1]    # NA for Spearman
ci_upper <- result_cor$conf.int[2]    # NA for Spearman
t_stat   <- result_cor$statistic      # t-statistic (Pearson) or S (Spearman)
df       <- result_cor$parameter      # df (Pearson) or NA (Spearman)
```

### Critical: Spearman confidence interval workaround
```r
# cor.test() does NOT provide CI for Spearman — use bootstrap
boot_cor <- function(data, indices) {
  cor(data[indices, 1], data[indices, 2], method = "spearman")
}
library(boot)
set.seed(42)
boot_result <- boot(data.frame(data$var_1, data$var_2), boot_cor, R = 1000)
spearman_ci <- boot.ci(boot_result, type = "perc")$percent[4:5]
```

---

## PART 4 — Multiple Comparison Correction

Always apply when running ≥ 2 hypothesis tests:

```r
# Collect all p-values
p_values <- c(
  comparison_1 = result_t$p.value,
  comparison_2 = result_mw$p.value,
  comparison_3 = result_chi$p.value
)

# Apply correction
p_adjusted_bonferroni <- p.adjust(p_values, method = "bonferroni")
p_adjusted_bh         <- p.adjust(p_values, method = "BH")    # FDR
p_adjusted_holm       <- p.adjust(p_values, method = "holm")   # Recommended default
```

---

## Standard Output Schema

```r
comparison_results <- list(
  execution_id = Sys.getenv("CIE_EXECUTION_ID"),

  # Two-group comparison
  group_comparison = list(
    method         = "welch_t_test",        # or "mann_whitney_u"
    test_statistic = result$statistic,
    df             = result$parameter,
    p_value        = result$p.value,
    mean_diff      = mean_diff,             # or HL estimate for Mann-Whitney
    ci_lower       = result$conf.int[1],
    ci_upper       = result$conf.int[2],
    effect_size    = list(measure = "cohens_d", value = cohens_d)
  ),

  # Multiple comparison correction (if applicable)
  p_adjusted = list(
    method   = "holm",
    p_values = p_adjusted_holm
  ),

  session_info = sessionInfo()
)
saveRDS(comparison_results,
        file.path(Sys.getenv("OUTPUT_DIR"), "comparison_results.rds"))
```
