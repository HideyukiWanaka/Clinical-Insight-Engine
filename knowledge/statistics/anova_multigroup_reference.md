# R ANOVA & Multi-Group Comparison Reference
# Domain: R
# Version: 1.0.0
# Status: Stable
# Package versions: base R ≥ 4.3.0, car 3.1-5
# Consumers: statistics
# Source: R base documentation, car CRAN reference (2026)
# Immutable during execution (AP-014)

## Purpose

Provides the Statistics Agent with accurate implementation patterns for
multi-group comparisons (≥3 groups): one-way ANOVA, non-parametric
alternatives, post-hoc tests, and effect sizes. Completes the gap in
comparison_correlation_reference.md (which covers 2-group only).

---

## Decision Framework: Which Multi-Group Test?

```
n groups ≥ 3
    │
    ├─ Continuous outcome
    │       │
    │       ├─ Normality OK + Homoscedasticity OK → one-way ANOVA (aov)
    │       ├─ Normality OK + Heteroscedasticity  → Welch's ANOVA (oneway.test)
    │       ├─ Non-normal (any group)              → Kruskal-Wallis (kruskal.test)
    │       └─ Paired / repeated measures          → Repeated-measures ANOVA or Friedman
    │
    └─ Categorical outcome
            │
            └─ Chi-square / Fisher (already in comparison_correlation_reference.md)
```

---

## PART 1 — One-Way ANOVA

### aov() — Standard ANOVA (assumes normality + homoscedasticity)

```r
# Prerequisite: verify normality (shapiro.test per group) and homoscedasticity
car::leveneTest(outcome_var ~ group_var, data = data)

model_aov <- aov(outcome_var ~ group_var, data = data)
summary(model_aov)
```

### Extracting ANOVA table values
```r
aov_summary <- summary(model_aov)[[1]]

f_stat    <- aov_summary["group_var", "F value"]
df_group  <- aov_summary["group_var", "Df"]
df_resid  <- aov_summary["Residuals", "Df"]
p_value   <- aov_summary["group_var", "Pr(>F)"]
```

### Effect size — η² (eta-squared)
```r
ss_group  <- aov_summary["group_var", "Sum Sq"]
ss_total  <- sum(aov_summary[, "Sum Sq"])
eta_sq    <- ss_group / ss_total
# Interpretation: Small = 0.01, Medium = 0.06, Large = 0.14
```

---

## PART 2 — Welch's ANOVA (heteroscedasticity)

```r
# Use when leveneTest() p < 0.05
result_welch <- oneway.test(
  formula   = outcome_var ~ group_var,
  data      = data,
  var.equal = FALSE    # FALSE = Welch (default); TRUE = standard ANOVA
)

f_stat  <- result_welch$statistic
df1     <- result_welch$parameter[1]
df2     <- result_welch$parameter[2]   # Non-integer (Welch-Satterthwaite)
p_value <- result_welch$p.value
```

---

## PART 3 — Kruskal-Wallis Test (non-parametric)

```r
# Use when normality fails in any group
result_kw <- kruskal.test(outcome_var ~ group_var, data = data)

kw_stat <- result_kw$statistic    # H statistic
df_kw   <- result_kw$parameter    # k-1 degrees of freedom
p_value <- result_kw$p.value
```

### Effect size — η²_H (Kruskal-Wallis)
```r
n_total  <- nrow(data)
eta_sq_H <- (result_kw$statistic - result_kw$parameter + 1) /
            (n_total - result_kw$parameter)
# Alternatively: (H - k + 1) / (N - k), where k = number of groups
# Interpretation: Small = 0.01, Medium = 0.06, Large = 0.14
```

---

## PART 4 — Post-Hoc Tests (pairwise comparisons after significant omnibus)

**Rule:** Always run post-hoc tests ONLY after a significant omnibus test (p < 0.05).

### TukeyHSD() — After ANOVA (equal variances assumed)
```r
tukey_result <- TukeyHSD(model_aov, conf.level = 0.95)
print(tukey_result)

# Extract as data frame
tukey_df <- as.data.frame(tukey_result$group_var)
# Columns: diff, lwr, upr, p adj
```

### Games-Howell — After Welch's ANOVA (unequal variances)
```r
# No base R function — use rstatix
library(rstatix)
gh_result <- games_howell_test(data, outcome_var ~ group_var)
# Returns: .y., group1, group2, estimate, conf.low, conf.high, p.adj
```

### Dunn test — After Kruskal-Wallis (non-parametric post-hoc)
```r
library(rstatix)
dunn_result <- dunn_test(
  data      = data,
  formula   = outcome_var ~ group_var,
  p.adjust.method = "holm"    # "bonferroni", "BH", "holm"
)
# Returns: .y., group1, group2, statistic, p, p.adj, p.adj.signif
```

### p.adjust for manual pairwise comparisons
```r
# If using pairwise.t.test() or pairwise.wilcox.test()
pairwise_t <- pairwise.t.test(
  x             = data$outcome_var,
  g             = data$group_var,
  p.adjust.method = "holm",
  pool.sd       = FALSE    # FALSE = Welch (unequal variances)
)

pairwise_w <- pairwise.wilcox.test(
  x             = data$outcome_var,
  g             = data$group_var,
  p.adjust.method = "holm",
  exact         = FALSE
)
```

---

## PART 5 — Repeated Measures ANOVA

```r
# One within-subject factor (time)
model_rm <- aov(outcome_var ~ time_var + Error(subject_id / time_var),
                data = data_long)
summary(model_rm)
```

### Friedman test — Non-parametric repeated measures
```r
result_friedman <- friedman.test(
  y      = data_wide_matrix,   # Matrix: rows = subjects, cols = time points
  groups = time_factor,
  blocks = subject_factor
)
# Or using formula for long-format data:
result_friedman <- friedman.test(outcome_var ~ time_var | subject_id,
                                  data = data_long)

friedman_stat <- result_friedman$statistic   # χ² statistic
df_friedman   <- result_friedman$parameter
p_friedman    <- result_friedman$p.value
```

---

## PART 6 — Complete Multi-Group Pipeline

```r
library(car)
library(rstatix)

# 1. Assumption checks
normality_by_group <- data |>
  group_by(group_var) |>
  summarise(
    shapiro_W = shapiro.test(outcome_var)$statistic,
    shapiro_p = shapiro.test(outcome_var)$p.value,
    .groups   = "drop"
  )
normality_passed <- all(normality_by_group$shapiro_p > 0.05)

levene_result    <- car::leveneTest(outcome_var ~ group_var, data = data)
homosced_passed  <- levene_result[1, "Pr(>F)"] > 0.05

# 2. Select and run omnibus test
if (normality_passed && homosced_passed) {
  model_aov    <- aov(outcome_var ~ group_var, data = data)
  aov_sum      <- summary(model_aov)[[1]]
  omnibus_p    <- aov_sum["group_var", "Pr(>F)"]
  omnibus_method <- "one_way_anova"
  # Effect size
  eta_sq <- aov_sum["group_var", "Sum Sq"] / sum(aov_sum[, "Sum Sq"])

} else if (normality_passed && !homosced_passed) {
  result_welch   <- oneway.test(outcome_var ~ group_var, data = data, var.equal = FALSE)
  omnibus_p      <- result_welch$p.value
  omnibus_method <- "welch_anova"
  eta_sq         <- NA  # Compute separately if needed

} else {
  result_kw      <- kruskal.test(outcome_var ~ group_var, data = data)
  omnibus_p      <- result_kw$p.value
  omnibus_method <- "kruskal_wallis"
  eta_sq_H       <- (result_kw$statistic - result_kw$parameter + 1) /
                    (nrow(data) - result_kw$parameter)
}

# 3. Post-hoc (only if omnibus p < 0.05)
posthoc_result <- NULL
if (omnibus_p < 0.05) {
  if (omnibus_method == "one_way_anova") {
    posthoc_result <- TukeyHSD(model_aov)
  } else if (omnibus_method == "welch_anova") {
    posthoc_result <- games_howell_test(data, outcome_var ~ group_var)
  } else {
    posthoc_result <- dunn_test(data, outcome_var ~ group_var,
                                p.adjust.method = "holm")
  }
}

# 4. Structure output
multigroup_results <- list(
  execution_id    = Sys.getenv("CIE_EXECUTION_ID"),
  omnibus_method  = omnibus_method,
  omnibus_p       = omnibus_p,
  effect_size     = list(measure = "eta_squared", value = eta_sq),
  posthoc         = posthoc_result,
  assumption_checks = list(
    normality_by_group = normality_by_group,
    levene_p           = levene_result[1, "Pr(>F)"]
  ),
  session_info    = sessionInfo()
)
saveRDS(multigroup_results,
        file.path(Sys.getenv("OUTPUT_DIR"), "multigroup_results.rds"))
```

---

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `aov()` on non-normal data | Assumption violated | Use `kruskal.test()` |
| `TukeyHSD()` after Welch ANOVA | Assumes equal variances | Use `games_howell_test()` |
| Post-hoc without omnibus | Multiple testing inflation | Always test omnibus first |
| `friedman.test()` on wide data | Format mismatch | Convert to long or use matrix form |
| No effect size reported | ST-004 violation | Always compute η² or η²_H |
