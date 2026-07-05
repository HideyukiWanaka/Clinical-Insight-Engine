# SKILL: Two-Group Comparison (Continuous Outcome)
# Skill ID: statistics/t-test
# Version: 2.0.0
# Consumers: statistics agent
# Knowledge references:
#   - knowledge/official/statistics/method_selection_guide.md (Step 0, Rules MS-005, MS-006)
#   - knowledge/official/statistics/assumption_checklist.md (AC-001, AC-002)
#   - knowledge/official/R/comparison_correlation_reference.md
#   - knowledge/official/R/r_error_handling.md (ERR-F02, ERR-D01, ERR-D02)

## Overview

Reusable procedure for comparing a continuous outcome between two groups.
Handles BOTH independent and paired designs via the `paired` flag in intent_object.
Covers: assumption checking → method selection → execution → effect size → output.

Applies when:
- `intent_object.objective ∈ {"between_group_comparison", "paired_comparison"}`
- `intent_object.outcome_type = "continuous"`
- `intent_object.predictor_type = "categorical_binary"`  (n_groups = 2)

---

## Design Branch: Independent vs Paired

```
intent_object.paired
    │
    ├─ false (or null+confirmed) → INDEPENDENT branch
    │     → Welch t-test (normality passes)
    │     → Mann-Whitney U (normality fails)
    │
    └─ true → PAIRED branch
          → Paired t-test (normality of differences passes)
          → Wilcoxon signed-rank (normality of differences fails)
```

**Rule MS-005 / MS-006:** If `paired = null`, do NOT assume false.
Return `requires_human_clarification = true` to Orchestrator.
If `paired = true` but `subject_id_var` is null, also return clarification request.

---

## Procedure

### Step 1 — Validate inputs and determine design

```r
outcome_var    <- "var_1"    # continuous outcome
group_var      <- "var_2"    # binary grouping / time point
subject_id_var <- "var_3"    # required only when paired=TRUE; from intent_object.subject_id_var
paired         <- TRUE       # from intent_object.paired

# Guard: paired=TRUE requires subject_id_var
if (paired && is.null(subject_id_var)) {
  stop("MS-006: paired=TRUE requires subject_id_var to be specified in intent_object")
}

stopifnot(outcome_var %in% names(data))
stopifnot(group_var   %in% names(data))

data[[group_var]] <- factor(data[[group_var]])
n_levels <- nlevels(data[[group_var]])
if (n_levels != 2) stop(paste("ERR-D02: group variable has", n_levels, "levels, expected 2"))

groups       <- levels(data[[group_var]])
n_per_group  <- table(data[[group_var]])
```

### Step 2 — Assumption checks (differ by design)

```r
if (!paired) {
  # INDEPENDENT: normality per group (AC-001)
  normality_results <- lapply(groups, function(g) {
    x  <- data[[outcome_var]][data[[group_var]] == g]
    x  <- x[!is.na(x)]
    if (length(x) < 3)  return(list(group=g, passed=NA, p=NA, note="n<3"))
    sw <- if (length(x) < 50) shapiro.test(x) else ks.test(scale(x), "pnorm")
    list(group=g, passed=sw$p.value > 0.05, p=sw$p.value)
  })
  normality_passed <- all(sapply(normality_results, function(r) isTRUE(r$passed)))

  # Homoscedasticity (AC-002) — informational for Welch
  levene_result   <- car::leveneTest(data[[outcome_var]] ~ data[[group_var]])
  homosced_passed <- levene_result[1, "Pr(>F)"] > 0.05

} else {
  # PAIRED: normality of DIFFERENCES (AC-001 adapted)
  # Requires wide-format: one row per subject with pre/post columns
  # OR long-format with subject_id_var to pivot
  grp_vals <- split(data[[outcome_var]], data[[group_var]])

  # Sort both vectors by subject_id to ensure correct pairing
  subj_ids <- split(data[[subject_id_var]], data[[group_var]])
  grp1_sorted <- grp_vals[[1]][order(subj_ids[[1]])]
  grp2_sorted <- grp_vals[[2]][order(subj_ids[[2]])]
  differences <- grp1_sorted - grp2_sorted

  n_pairs <- sum(!is.na(differences))
  sw_diff <- if (n_pairs >= 3 && n_pairs < 50) shapiro.test(differences[!is.na(differences)])
             else ks.test(scale(differences[!is.na(differences)]), "pnorm")

  normality_results <- list(list(
    variable = "differences",
    passed   = sw_diff$p.value > 0.05,
    p        = sw_diff$p.value,
    note     = "Normality of pairwise differences (paired design)"
  ))
  normality_passed <- sw_diff$p.value > 0.05

  # Levene not applicable for paired design
  levene_result   <- NULL
  homosced_passed <- NA
}
```

### Step 3 — Select and run test

```r
if (!paired) {
  # --- INDEPENDENT branch ---
  if (normality_passed) {
    result      <- t.test(as.formula(paste(outcome_var, "~", group_var)),
                          data = data, var.equal = FALSE, conf.level = 0.95)
    method_used <- "welch_t_test"
  } else {
    result      <- wilcox.test(as.formula(paste(outcome_var, "~", group_var)),
                               data = data, conf.int = TRUE,
                               conf.level = 0.95, exact = FALSE)
    method_used <- "mann_whitney_u"
  }

} else {
  # --- PAIRED branch ---
  if (normality_passed) {
    # Paired t-test: pass pre and post vectors directly (not formula)
    result      <- t.test(grp1_sorted, grp2_sorted,
                          paired = TRUE, conf.level = 0.95)
    method_used <- "paired_t_test"
  } else {
    # Wilcoxon signed-rank test
    result      <- wilcox.test(grp1_sorted, grp2_sorted,
                               paired = TRUE, conf.int = TRUE,
                               conf.level = 0.95, exact = FALSE)
    method_used <- "wilcoxon_signed_rank"
  }
}
```

### Step 4 — Effect size

```r
if (method_used == "welch_t_test") {
  # Cohen's d (independent)
  grp_data  <- split(data[[outcome_var]], data[[group_var]])
  n1 <- sum(!is.na(grp_data[[1]])); n2 <- sum(!is.na(grp_data[[2]]))
  sd1 <- sd(grp_data[[1]], na.rm=TRUE); sd2 <- sd(grp_data[[2]], na.rm=TRUE)
  pooled_sd <- sqrt(((n1-1)*sd1^2 + (n2-1)*sd2^2) / (n1+n2-2))
  mean_diff <- diff(result$estimate)
  es_value  <- abs(mean_diff) / pooled_sd
  es_measure <- "cohens_d"

} else if (method_used == "paired_t_test") {
  # Cohen's d for paired (based on SD of differences)
  sd_diff   <- sd(differences, na.rm = TRUE)
  mean_diff <- mean(differences, na.rm = TRUE)
  es_value  <- abs(mean_diff) / sd_diff
  es_measure <- "cohens_d_paired"

} else if (method_used == "mann_whitney_u") {
  # Rank-biserial correlation r (independent)
  n_total <- sum(!is.na(data[[outcome_var]]))
  mu_W    <- prod(n_per_group) / 2
  sd_W    <- sqrt(prod(n_per_group) * (sum(n_per_group) + 1) / 12)
  Z       <- (result$statistic - mu_W) / sd_W
  es_value  <- abs(Z) / sqrt(n_total)
  es_measure <- "rank_biserial_r"
  mean_diff  <- NULL

} else {
  # Wilcoxon signed-rank: r = Z / sqrt(N_pairs)
  n_pairs_used <- n_pairs  # non-missing pairs
  # Approximate Z from W statistic
  mu_W  <- n_pairs_used * (n_pairs_used + 1) / 4
  sd_W  <- sqrt(n_pairs_used * (n_pairs_used + 1) * (2 * n_pairs_used + 1) / 24)
  Z     <- (result$statistic - mu_W) / sd_W
  es_value  <- abs(Z) / sqrt(n_pairs_used)
  es_measure <- "rank_biserial_r_paired"
  mean_diff  <- mean(differences, na.rm = TRUE)
}

es_interp <- dplyr::case_when(
  es_value < 0.2 ~ "negligible",
  es_value < 0.5 ~ "small",
  es_value < 0.8 ~ "medium",
  TRUE           ~ "large"
)
```

### Step 5 — Structure output

```r
skill_result <- list(
  skill_id    = "statistics/t-test",
  method_used = method_used,
  design      = if (paired) "paired" else "independent",
  outcome_var = outcome_var,
  group_var   = group_var,
  subject_id_var = if (paired) subject_id_var else NULL,
  n_per_group = as.list(n_per_group),
  n_pairs     = if (paired) n_pairs else NULL,

  primary_result = list(
    test_statistic = as.numeric(result$statistic),
    df             = as.numeric(result$parameter),
    p_value        = result$p.value,
    estimate       = as.numeric(result$estimate),
    mean_diff      = if (!is.null(mean_diff)) as.numeric(mean_diff) else NULL,
    ci_lower       = if (!is.null(result$conf.int) && length(result$conf.int) >= 1)
                       as.numeric(result$conf.int[1]) else NA_real_,
    ci_upper       = if (!is.null(result$conf.int) && length(result$conf.int) >= 2)
                       as.numeric(result$conf.int[2]) else NA_real_,
    ci_note        = if (is.null(result$conf.int))
                       "CI could not be computed (e.g. ties in Wilcoxon test)" else NULL
  ),

  effect_size = list(
    measure        = es_measure,
    value          = es_value,
    interpretation = es_interp
  ),

  assumption_checks = list(
    normality       = normality_results,
    homoscedasticity = if (!paired) list(
      f_value = levene_result[1, "F value"],
      p_value = levene_result[1, "Pr(>F)"],
      passed  = homosced_passed,
      note    = "Levene's test (informational; Welch correction applied regardless)"
    ) else list(note = "Not applicable for paired design")
  ),

  method_justification = paste0(
    "objective=between_group_comparison, outcome_type=continuous, ",
    "paired=", paired, ", normality_passed=", normality_passed,
    " → ", method_used
  )
)
```

---

## Validation Rules

- `design` must be `"paired"` or `"independent"` — never inferred silently
- If `design = "paired"`: `subject_id_var` must not be NULL
- If `design = "paired"`: `n_pairs` must equal `min(n_per_group)` when no missing data
- `p_value` must be in (0, 1)
- `ci_lower` / `ci_upper` may be `NA_real_` when `result$conf.int` is NULL (e.g. Wilcoxon with ties); in that case `ci_note` must be set
- If `p_value < 0.05` and CI is available (not NA): CI must not include 0
- `effect_size.value` must be ≥ 0
- Paired tests (`paired_t_test`, `wilcoxon_signed_rank`) must use vector syntax, not formula
- `method_justification` must state `paired=` value explicitly
