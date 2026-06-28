# SKILL: Manuscript Section Generation
# Skill ID: reporting/manuscript-section
# Version: 1.0.0
# Consumers: reporting agent
# Knowledge references:
#   - knowledge/official/reporting/manuscript_structure_guide.md
#   - knowledge/official/reporting/reporting_checklists.md
#   - knowledge/official/statistics/result_interpretation_guide.md (Templates R-001 to R-004)

## Overview

Generates structured manuscript section drafts (Methods and Results)
from validated statistical results. Every numeric value is sourced from
execution_result — no fabrication permitted (rule RP-001).

Applies to: Methods statistical subsection, Results primary outcome section.

---

## Procedure

### Step 1 — Validate traceability

```r
# Every value used in manuscript must be traceable to execution_result
required_fields <- c("method_used", "primary_result", "effect_size", "n_per_group")
for (f in required_fields) {
  if (is.null(statistical_results[[f]])) {
    stop(paste("RESULT_TRACEABILITY_FAILED: missing field", f,
               "in statistical_results"))
  }
}
```

### Step 2 — Generate Methods statistical subsection

```r
method_used  <- statistical_results$method_used
n_per_group  <- statistical_results$n_per_group
outcome_var  <- statistical_results$outcome_var
group_var    <- statistical_results$group_var

# Map method_used → human-readable description
method_description <- switch(method_used,
  welch_t_test    = "Welch's two-sample t-test",
  mann_whitney_u  = "Mann-Whitney U test (Wilcoxon rank-sum test)",
  one_way_anova   = "one-way analysis of variance (ANOVA)",
  welch_anova     = "Welch's one-way ANOVA",
  kruskal_wallis  = "Kruskal-Wallis test",
  logistic_regression = "multivariable logistic regression",
  cox_regression  = "Cox proportional hazards regression",
  pearson         = "Pearson's correlation coefficient",
  spearman        = "Spearman's rank correlation coefficient",
  method_used     # fallback: use method_used string directly
)

# Assumption check description
assumption_note <- if (!is.null(statistical_results$assumption_checks$normality)) {
  norm_passed <- isTRUE(statistical_results$assumption_checks$normality$both_passed) ||
                 all(sapply(statistical_results$assumption_checks$normality,
                            function(r) isTRUE(r$passed)))
  if (norm_passed) "Normality was assessed using the Shapiro-Wilk test and confirmed."
  else "Normality was assessed using the Shapiro-Wilk test; non-parametric alternatives were applied where assumptions were violated."
} else ""

methods_text <- paste0(
  "All statistical analyses were performed using R version ",
  paste(R.version$major, R.version$minor, sep = "."),
  ". The primary outcome was compared between groups using ",
  method_description, ". ",
  assumption_note, " ",
  "Effect sizes are reported as ",
  statistical_results$effect_size$measure,
  " with 95% confidence intervals. ",
  "A two-tailed p-value < 0.05 was considered statistically significant."
)
```

### Step 3 — Generate Results primary outcome paragraph

```r
# Select template based on method
p_val    <- statistical_results$primary_result$p_value
ci_l     <- statistical_results$primary_result$ci_lower
ci_u     <- statistical_results$primary_result$ci_upper
es_val   <- statistical_results$effect_size$value
es_msr   <- statistical_results$effect_size$measure
es_interp <- statistical_results$effect_size$interpretation

sig_word <- if (p_val < 0.05) "statistically significant" else "not statistically significant"

# Template R-001 (continuous, two groups)
if (method_used %in% c("welch_t_test", "mann_whitney_u")) {
  grp_names  <- names(n_per_group)
  estimates  <- statistical_results$primary_result$estimate

  if (method_used == "welch_t_test") {
    direction  <- if (estimates[1] > estimates[2]) "higher" else "lower"
    results_text <- paste0(
      "The ", outcome_var, " was ", sig_word, " ",
      direction, " in ", grp_names[1],
      " compared with ", grp_names[2],
      " (mean difference: ", round(statistical_results$primary_result$mean_diff, 2),
      ", 95% CI: [", round(ci_l, 2), ", ", round(ci_u, 2), "]",
      ", p=", format(p_val, digits=3), "; ",
      es_msr, "=", round(es_val, 2),
      " [", es_interp, " effect])."
    )
  } else {
    results_text <- paste0(
      "The difference in ", outcome_var,
      " between groups was ", sig_word,
      " (Hodges-Lehmann estimate: ", round(statistical_results$primary_result$estimate, 2),
      ", 95% CI: [", round(ci_l, 2), ", ", round(ci_u, 2), "]",
      ", p=", format(p_val, digits=3), "; ",
      es_msr, "=", round(es_val, 2),
      " [", es_interp, " effect])."
    )
  }

# Template for logistic regression — Template R-002
} else if (method_used == "logistic_regression") {
  primary_coef <- statistical_results$coefficients[[1]][[1]]
  results_text <- paste0(
    "On multivariable logistic regression, ",
    outcome_var, " was ",
    if (p_val < 0.05) paste0(
      "significantly associated with ", group_var,
      " (OR: ", round(primary_coef$or, 2),
      ", 95% CI: [", round(primary_coef$ci_lower, 2), ", ",
      round(primary_coef$ci_upper, 2), "]",
      ", p=", format(p_val, digits=3), ")."
    ) else paste0(
      "not significantly associated with ", group_var,
      " (OR: ", round(primary_coef$or, 2),
      ", 95% CI: [", round(primary_coef$ci_lower, 2), ", ",
      round(primary_coef$ci_upper, 2), "]",
      ", p=", format(p_val, digits=3), ")."
    )
  )

# Template for survival — Template R-003
} else if (method_used %in% c("kaplan_meier", "cox_regression")) {
  med_surv <- statistical_results$kaplan_meier$median_survival
  grp_names <- names(med_surv)
  results_text <- paste0(
    "Median survival was ",
    round(med_surv[[1]], 1), " in ", grp_names[1],
    " vs. ", round(med_surv[[2]], 1), " in ", grp_names[2],
    " (log-rank p=", format(statistical_results$kaplan_meier$logrank_p, digits=3), ")."
  )

} else {
  # Generic fallback — Template R-004 (non-significant) or general
  results_text <- paste0(
    "The analysis of ", outcome_var,
    " was ", sig_word,
    " (p=", format(p_val, digits=3), ")."
  )
}
```

### Step 4 — Identify unresolved items

```r
unresolved_items <- c(
  "Clinical interpretation of findings requires domain expertise.",
  "Limitations section requires human authorial input.",
  "Conclusion framing requires human review."
)
```

### Step 5 — Structure output

```r
manuscript_sections <- list(
  methods_statistical = list(
    section = "Methods",
    subsection = "Statistical analysis",
    content = methods_text,
    source_fields = c("method_used", "assumption_checks", "effect_size")
  ),
  results_primary = list(
    section = "Results",
    subsection = "Primary outcome",
    content = results_text,
    source_fields = c("primary_result", "effect_size", "n_per_group"),
    traceability = list(
      p_value    = p_val,
      ci_lower   = ci_l,
      ci_upper   = ci_u,
      effect_size = es_val
    )
  )
)

skill_result <- list(
  skill_id           = "reporting/manuscript-section",
  manuscript_sections = manuscript_sections,
  unresolved_items   = unresolved_items,
  word_count_estimate = list(
    methods = nchar(gsub("\\s+", " ", methods_text)) / 5,  # rough estimate
    results = nchar(gsub("\\s+", " ", results_text)) / 5
  )
)
```

---

## Validation Rules
- `methods_text` must include: method name, p-value threshold, effect size measure
- `results_text` must include: p-value, CI bounds, effect size value (rule RP-001 traceability)
- All numeric values in text must exactly match `statistical_results` (CC-001, CC-002)
- `unresolved_items` must not be empty — always flag authorial decisions
- If `p_value < 0.05`: text must not say "no significant difference"
- If `p_value ≥ 0.05`: text must not say "significant"

---

## Examples

### Methods output
```
All statistical analyses were performed using R version 4.3.2.
The primary outcome was compared between groups using Welch's two-sample t-test.
Normality was assessed using the Shapiro-Wilk test and confirmed.
Effect sizes are reported as cohens_d with 95% confidence intervals.
A two-tailed p-value < 0.05 was considered statistically significant.
```

### Results output
```
The var_1 was statistically significant higher in A compared with B
(mean difference: 8.20, 95% CI: [1.30, 15.10], p=0.021; cohens_d=0.43 [small effect]).
```

---

## Tests

### TEST-MS01: p-value in methods text
```r
stopifnot(grepl("0.05", result$manuscript_sections$methods_statistical$content))
```

### TEST-MS02: CI values traceable to execution_result
```r
ci_in_text_l <- result$manuscript_sections$results_primary$traceability$ci_lower
ci_in_result <- statistical_results$primary_result$ci_lower
stopifnot(abs(ci_in_text_l - ci_in_result) < 1e-6)
```

### TEST-MS03: significance language consistent with p-value
```r
content <- result$manuscript_sections$results_primary$content
p <- statistical_results$primary_result$p_value
if (p < 0.05) {
  stopifnot(!grepl("not statistically significant|no significant", content))
} else {
  stopifnot(!grepl("statistically significant[^ly]", content) ||
            grepl("not statistically significant", content))
}
```

### TEST-MS04: unresolved_items not empty
```r
stopifnot(length(result$unresolved_items) > 0)
```

### TEST-MS05: RESULT_TRACEABILITY_FAILED on missing field
```r
bad_results <- statistical_results
bad_results$primary_result <- NULL
err <- tryCatch(run_manuscript_skill(bad_results), error=function(e) conditionMessage(e))
stopifnot(grepl("RESULT_TRACEABILITY_FAILED", err))
```
