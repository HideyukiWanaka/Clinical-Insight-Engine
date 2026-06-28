# SKILL: Multi-Group Comparison (Continuous Outcome)
# Skill ID: statistics/anova
# Version: 2.0.0
# Consumers: statistics agent
# Knowledge references:
#   - knowledge/statistics/method_selection_guide.md (Step 0, MS-005, MS-006)
#   - knowledge/statistics/assumption_checklist.md (AC-001, AC-002)
#   - knowledge/R/anova_multigroup_reference.md

## Overview

Reusable procedure for comparing a continuous outcome across three or more groups.
Handles BOTH independent and repeated-measures (paired) designs.

Applies when:
- `intent_object.objective = "between_group_comparison"`
- `intent_object.outcome_type = "continuous"`
- Number of groups ≥ 3

---

## Design Branch

```
intent_object.paired
    │
    ├─ false → INDEPENDENT branch
    │     → One-way ANOVA (normality + homoscedasticity pass)
    │     → Welch's ANOVA (normality passes, heteroscedasticity)
    │     → Kruskal-Wallis (normality fails)
    │
    └─ true → REPEATED-MEASURES branch (requires subject_id_var)
          → Repeated-measures ANOVA (normality of residuals passes)
          → Friedman test (normality fails)
```

---

## Procedure

### Step 1 — Validate inputs

```r
outcome_var    <- "var_1"
group_var      <- "var_2"    # time point or condition variable
subject_id_var <- "var_3"    # required when paired=TRUE
paired         <- FALSE      # from intent_object.paired

if (paired && is.null(subject_id_var)) {
  stop("MS-006: paired=TRUE requires subject_id_var")
}

data[[group_var]] <- factor(data[[group_var]])
n_groups     <- nlevels(data[[group_var]])
n_per_group  <- table(data[[group_var]])
stopifnot(n_groups >= 3)
stopifnot(all(n_per_group >= 2))
```

### Step 2 — Assumption checks

```r
if (!paired) {
  # INDEPENDENT: normality per group
  normality_results <- lapply(levels(data[[group_var]]), function(g) {
    x  <- data[[outcome_var]][data[[group_var]] == g & !is.na(data[[outcome_var]])]
    if (length(x) < 3) return(list(group=g, passed=NA, p=NA))
    sw <- shapiro.test(x)
    list(group=g, passed=sw$p.value > 0.05, p=sw$p.value)
  })
  normality_passed <- all(sapply(normality_results, function(r) isTRUE(r$passed)))

  levene_result   <- car::leveneTest(data[[outcome_var]] ~ data[[group_var]])
  homosced_passed <- levene_result[1, "Pr(>F)"] > 0.05

} else {
  # REPEATED-MEASURES: normality of residuals from rm ANOVA
  # Fit preliminary model to get residuals
  rm_formula <- as.formula(paste(outcome_var, "~", group_var,
                                  "+ Error(", subject_id_var, "/", group_var, ")"))
  model_prelim <- aov(rm_formula, data = data)
  resids <- residuals(model_prelim)
  sw_resid <- shapiro.test(resids)

  normality_results <- list(list(
    variable = "rm_anova_residuals",
    passed   = sw_resid$p.value > 0.05,
    p        = sw_resid$p.value
  ))
  normality_passed <- sw_resid$p.value > 0.05
  levene_result    <- NULL
  homosced_passed  <- NA
}
```

### Step 3 — Omnibus test selection

```r
if (!paired) {
  # --- INDEPENDENT branch ---
  if (normality_passed && homosced_passed) {
    model_aov   <- aov(as.formula(paste(outcome_var, "~", group_var)), data = data)
    aov_sum     <- summary(model_aov)[[1]]
    omnibus_p   <- aov_sum[group_var, "Pr(>F)"]
    omnibus_f   <- aov_sum[group_var, "F value"]
    method_used <- "one_way_anova"
    eta_sq      <- aov_sum[group_var, "Sum Sq"] / sum(aov_sum[, "Sum Sq"])

  } else if (normality_passed && !homosced_passed) {
    res_welch   <- oneway.test(as.formula(paste(outcome_var, "~", group_var)),
                               data = data, var.equal = FALSE)
    omnibus_p   <- res_welch$p.value
    omnibus_f   <- res_welch$statistic
    method_used <- "welch_anova"
    eta_sq      <- NA_real_

  } else {
    res_kw      <- kruskal.test(as.formula(paste(outcome_var, "~", group_var)), data = data)
    omnibus_p   <- res_kw$p.value
    omnibus_f   <- res_kw$statistic
    method_used <- "kruskal_wallis"
    n_total     <- sum(!is.na(data[[outcome_var]]))
    eta_sq      <- (res_kw$statistic - res_kw$parameter + 1) / (n_total - res_kw$parameter)
  }

} else {
  # --- REPEATED-MEASURES branch ---
  if (normality_passed) {
    # Repeated-measures ANOVA
    rm_formula  <- as.formula(paste(outcome_var, "~", group_var,
                                    "+ Error(", subject_id_var, "/", group_var, ")"))
    model_rm    <- aov(rm_formula, data = data)
    rm_sum      <- summary(model_rm)
    # Extract F and p from the within-subject error stratum
    within_sum  <- rm_sum[[paste0("Error: ", subject_id_var, ":", group_var)]][[1]]
    omnibus_p   <- within_sum[group_var, "Pr(>F)"]
    omnibus_f   <- within_sum[group_var, "F value"]
    method_used <- "repeated_measures_anova"

    # Partial η² for within-subject effect
    ss_effect   <- within_sum[group_var, "Sum Sq"]
    ss_error    <- within_sum["Residuals", "Sum Sq"]
    eta_sq      <- ss_effect / (ss_effect + ss_error)

  } else {
    # Friedman test (non-parametric repeated-measures)
    # Requires long-format: outcome_var ~ group_var | subject_id_var
    res_friedman <- friedman.test(
      as.formula(paste(outcome_var, "~", group_var, "|", subject_id_var)),
      data = data
    )
    omnibus_p   <- res_friedman$p.value
    omnibus_f   <- res_friedman$statistic   # χ² statistic
    method_used <- "friedman"

    # Kendall's W (effect size for Friedman)
    k    <- n_groups
    n_subj <- length(unique(data[[subject_id_var]]))
    w_kendall <- res_friedman$statistic / (k * (n_subj - 1))
    eta_sq <- w_kendall   # Report Kendall's W as effect size
  }
}
```

### Step 4 — Post-hoc (only if omnibus p < 0.05)

```r
posthoc_result <- NULL
posthoc_method <- NULL

if (omnibus_p < 0.05) {
  if (method_used == "one_way_anova") {
    ph            <- TukeyHSD(model_aov)
    posthoc_result <- as.data.frame(ph[[group_var]])
    posthoc_method <- "tukey_hsd"

  } else if (method_used == "welch_anova") {
    posthoc_result <- rstatix::games_howell_test(
      data, as.formula(paste(outcome_var, "~", group_var)))
    posthoc_method <- "games_howell"

  } else if (method_used == "kruskal_wallis") {
    posthoc_result <- rstatix::dunn_test(
      data, as.formula(paste(outcome_var, "~", group_var)),
      p.adjust.method = "holm")
    posthoc_method <- "dunn_holm"

  } else if (method_used == "repeated_measures_anova") {
    # Pairwise paired t-tests with Holm correction
    posthoc_result <- pairwise.t.test(
      x               = data[[outcome_var]],
      g               = data[[group_var]],
      paired          = TRUE,
      p.adjust.method = "holm"
    )$p.value
    posthoc_method <- "pairwise_paired_t_holm"

  } else if (method_used == "friedman") {
    # Wilcoxon signed-rank pairwise with Holm correction
    posthoc_result <- pairwise.wilcox.test(
      x               = data[[outcome_var]],
      g               = data[[group_var]],
      paired          = TRUE,
      p.adjust.method = "holm",
      exact           = FALSE
    )$p.value
    posthoc_method <- "pairwise_wilcoxon_signed_rank_holm"
  }
}
```

### Step 5 — Structure output

```r
skill_result <- list(
  skill_id       = "statistics/anova",
  method_used    = method_used,
  design         = if (paired) "repeated_measures" else "independent",
  n_groups       = n_groups,
  n_per_group    = as.list(n_per_group),
  subject_id_var = if (paired) subject_id_var else NULL,

  primary_result = list(
    test_statistic = as.numeric(omnibus_f),
    p_value        = omnibus_p
  ),

  effect_size = list(
    measure = if (method_used == "friedman") "kendalls_W" else "eta_squared",
    value   = eta_sq
  ),

  posthoc = if (omnibus_p < 0.05)
    list(method=posthoc_method, table=posthoc_result) else NULL,

  assumption_checks = list(
    normality = normality_results,
    homoscedasticity = if (!paired)
      list(p_value=levene_result[1,"Pr(>F)"], passed=homosced_passed)
    else
      list(note="Not applicable for repeated-measures design")
  ),

  method_justification = paste0(
    "n_groups=", n_groups, ", paired=", paired,
    ", normality_passed=", normality_passed,
    if (!paired) paste0(", homosced_passed=", homosced_passed) else "",
    " → ", method_used
  )
)
```

---

## Validation Rules
- `design` must be `"independent"` or `"repeated_measures"` — never inferred
- If `design = "repeated_measures"`: `subject_id_var` must not be NULL
- `omnibus_p` must be in (0, 1)
- `posthoc` must be NULL when `omnibus_p ≥ 0.05`
- Repeated-measures post-hoc must use `paired=TRUE` (not independent tests)
- Friedman effect size reported as Kendall's W (not η²)
- `method_justification` must state `paired=` value explicitly
