# R Meta-Analysis Reference (metafor)
# Domain: R
# Version: 1.0.0
# Status: Stable
# Package version: metafor 4.9-17 (2025-09-18, verified against wviechtb.github.io)
# Consumers: statistics, visualization
# Source: wviechtb.github.io/metafor, JSS 36(3) Viechtbauer (2010)
# Immutable during execution (AP-014)

## Purpose

Provides the Statistics Agent with accurate, argument-level implementation
patterns for systematic review and meta-analysis using metafor.
Covers the full pipeline: effect size calculation → model fitting →
heterogeneity assessment → publication bias → forest and funnel plots.

---

## Core Workflow

```
Raw study data (2×2 tables, means, correlations...)
        ↓
  escalc()        → Compute effect sizes (yi) and variances (vi)
        ↓
  rma()           → Fit fixed- or random-effects model
        ↓
  summary(res)    → Pooled estimate, τ², I², Q-test
        ↓
  forest(res)     → Forest plot
  funnel(res)     → Funnel plot
  regtest(res)    → Egger's regression test (publication bias)
  ranktest(res)   → Begg's rank correlation test
```

---

## PART 1 — Effect Size Calculation: escalc()

```r
library(metafor)

# Binary outcome (2×2 table data)
dat <- escalc(
  measure = "OR",      # Effect size measure (see table below)
  ai = n_events_treat, bi = n_noevent_treat,   # Treated group: events, non-events
  ci = n_events_ctrl,  di = n_noevent_ctrl,     # Control group: events, non-events
  data    = study_df,
  slab    = paste(author, year, sep = ", ")     # Study labels for plots
)
# Result: adds yi (log OR) and vi (variance) columns to dat

# Continuous outcome (mean difference)
dat <- escalc(
  measure = "MD",      # Raw mean difference
  m1i = mean_treat,  sd1i = sd_treat,  n1i = n_treat,
  m2i = mean_ctrl,   sd2i = sd_ctrl,   n2i = n_ctrl,
  data = study_df,
  slab = paste(author, year, sep = ", ")
)

# Correlation
dat <- escalc(
  measure = "ZCOR",    # Fisher's r-to-z transformed correlation
  ri = r_values,
  ni = n_values,
  data = study_df
)
```

### measure argument — common clinical options

| measure | Effect size | Use case |
|---------|------------|----------|
| `"OR"` | Log odds ratio | Binary outcome, case-control or RCT |
| `"RR"` | Log risk ratio | Binary outcome, cohort or RCT |
| `"RD"` | Risk difference | Binary outcome, absolute risk |
| `"MD"` | Raw mean difference | Continuous outcome, same scale |
| `"SMD"` | Standardized mean difference (Hedges' g) | Continuous, different scales |
| `"ZCOR"` | Fisher's r-to-z correlation | Correlation meta-analysis |
| `"HR"` | Log hazard ratio | Survival outcome |

---

## PART 2 — Model Fitting: rma()

```r
# Random-effects model (default, recommended for clinical meta-analyses)
res <- rma(
  yi     = yi,          # Effect sizes from escalc()
  vi     = vi,          # Sampling variances from escalc()
  data   = dat,
  method = "REML",      # Tau² estimator: "REML" (default), "DL", "HE", "HS", "SJ", "ML", "EB"
  slab   = dat$slab     # Study labels (use if not already in dat)
)

# Fixed-effects model (EE = equal-effects)
res_fe <- rma(yi, vi, data = dat, method = "EE")
```

### method argument — τ² estimators

| method | Full name | When to use |
|--------|-----------|-------------|
| `"REML"` | Restricted ML | Default — best general choice |
| `"DL"` | DerSimonian-Laird | Legacy; often used in older literature |
| `"EE"` | Equal-effects (fixed) | When assuming one true effect |
| `"ML"` | Maximum likelihood | For meta-regression (less biased) |

### Critical: Fixed vs Random effects model

| Model | Assumption | Inference scope |
|-------|-----------|----------------|
| Fixed (EE) | One true effect; studies differ only by sampling error | Only the k included studies |
| Random (REML) | True effects vary across studies (τ² > 0) | Population of all similar studies |

**For clinical meta-analyses: use random-effects (REML) by default.**
Fixed-effects is only appropriate when studies are very homogeneous and
inference is limited to the exact studies included.

---

## PART 3 — Extracting Results

```r
res_summary <- summary(res)

# Pooled estimate (on log scale for OR, RR, HR)
pooled_log  <- res$b[1]          # Log OR / log RR / log HR
pooled_se   <- res$se[1]
pooled_z    <- res$zval[1]
pooled_p    <- res$pval[1]
pooled_ci_l <- res$ci.lb[1]
pooled_ci_u <- res$ci.ub[1]

# Back-transform to original scale (for OR, RR, HR)
pooled_OR   <- exp(pooled_log)
ci_lower_OR <- exp(pooled_ci_l)
ci_upper_OR <- exp(pooled_ci_u)

# Prediction interval (range of true effects in population — report for random-effects)
pred_int_l  <- res$pi.lb         # Lower bound of 95% prediction interval
pred_int_u  <- res$pi.ub         # Upper bound
```

### Heterogeneity statistics

```r
# Q-test for heterogeneity
Q_stat  <- res$QE               # Cochran's Q statistic
Q_df    <- res$k - 1            # Degrees of freedom (k = number of studies)
Q_p     <- res$QEp              # p-value (p < 0.05 → significant heterogeneity)

# I² — proportion of variance due to heterogeneity
I_sq    <- res$I2               # 0–100%; 25% low, 50% moderate, 75% high
tau_sq  <- res$tau2             # Between-study variance (τ²)
tau     <- sqrt(tau_sq)         # Between-study SD (τ)
H_sq    <- res$H2               # H² = total variance / sampling variance

# Print all heterogeneity at once
cat("Q =", round(Q_stat, 2), "(df =", Q_df, ", p =", round(Q_p, 3), ")\n")
cat("I² =", round(I_sq, 1), "%\n")
cat("τ² =", round(tau_sq, 4), ", τ =", round(tau, 4), "\n")
```

---

## PART 4 — Publication Bias Assessment

### Egger's regression test (continuous predictor: standard error)
```r
egger_result <- regtest(res, model = "rma", predictor = "sei")
# t-statistic and p-value: p < 0.05 → funnel plot asymmetry
cat("Egger's test: t =", round(egger_result$zval, 3),
    ", df =", egger_result$ddf, ", p =", round(egger_result$pval, 3))
```

### Begg's rank correlation test
```r
begg_result <- ranktest(res)
# Kendall's tau and p-value
cat("Begg's test: tau =", round(begg_result$tau, 3),
    ", p =", round(begg_result$pval, 3))
```

### Trim-and-fill method
```r
res_tf <- trimfill(res)
summary(res_tf)
# Estimates number of missing studies and adjusted pooled estimate
funnel(res_tf, atransf = exp)    # Funnel plot with filled studies shown
```

---

## PART 5 — Plots

### Forest plot
```r
forest(
  res,
  atransf    = exp,              # Back-transform log scale → OR/RR/HR
  header     = "Study",
  xlab       = "Odds Ratio",
  refline    = 1,                # Null line at OR=1 (or 0 for MD)
  showweights = TRUE,            # Show % weight per study
  order      = "obs"             # Order by effect size; or "prec" for precision
)
```

### Funnel plot (publication bias)
```r
funnel(
  res,
  atransf = exp,                 # Back-transform x-axis
  xlab    = "Odds Ratio",
  yaxis   = "sei",               # y-axis: standard error (default)
  level   = c(90, 95, 99),       # Pseudo-CI regions (contour-enhanced)
  shade   = c("white", "gray55", "gray75")
)
```

---

## PART 6 — Meta-Regression (moderator analysis)

```r
# Continuous moderator
res_mod <- rma(yi, vi, mods = ~ year, data = dat, method = "REML")
summary(res_mod)
# Tests whether 'year' explains heterogeneity

# Categorical moderator (subgroup analysis)
res_sub <- rma(yi, vi, mods = ~ factor(study_design), data = dat, method = "REML")
# R² analogue: how much heterogeneity is explained by the moderator
res_mod$R2
```

---

## PART 7 — Complete Pipeline

```r
library(metafor)

# 1. Compute effect sizes
dat <- escalc(measure = "OR",
              ai = events_t, bi = nonevents_t,
              ci = events_c, di = nonevents_c,
              data = study_df,
              slab = paste(author, year))

# 2. Fit random-effects model
res <- rma(yi, vi, data = dat, method = "REML")

# 3. Extract pooled results
pooled <- list(
  or        = exp(res$b[1]),
  ci_lower  = exp(res$ci.lb[1]),
  ci_upper  = exp(res$ci.ub[1]),
  z         = res$zval[1],
  p         = res$pval[1],
  pred_lb   = exp(res$pi.lb),
  pred_ub   = exp(res$pi.ub)
)

# 4. Heterogeneity
heterogeneity <- list(
  Q     = res$QE,
  Q_df  = res$k - 1,
  Q_p   = res$QEp,
  I2    = res$I2,
  tau2  = res$tau2
)

# 5. Publication bias
egger <- regtest(res, predictor = "sei")
begg  <- ranktest(res)

# 6. Save output
meta_results <- list(
  execution_id  = Sys.getenv("CIE_EXECUTION_ID"),
  method        = "random_effects_meta_analysis",
  measure       = "OR",
  k_studies     = res$k,
  pooled        = pooled,
  heterogeneity = heterogeneity,
  publication_bias = list(
    egger_p = egger$pval,
    begg_p  = begg$pval
  ),
  session_info  = sessionInfo()
)
saveRDS(meta_results,
        file.path(Sys.getenv("OUTPUT_DIR"), "meta_results.rds"))

# 7. Save plots to OUTPUT_DIR
pdf(file.path(Sys.getenv("OUTPUT_DIR"), "forest_plot.pdf"),
    width = 10, height = 0.4 * res$k + 3)
forest(res, atransf = exp, header = "Study", xlab = "Odds Ratio")
dev.off()

pdf(file.path(Sys.getenv("OUTPUT_DIR"), "funnel_plot.pdf"),
    width = 7, height = 6)
funnel(res, atransf = exp)
dev.off()
```

---

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| Pooled OR not back-transformed | Forgetting `exp()` | Always `exp(res$b)` and `exp(res$ci.lb/ub)` |
| Fixed-effects misapplied | Heterogeneity I² > 50% | Use random-effects (`method="REML"`) |
| Prediction interval omitted | Only reporting CI | Always report PI for random-effects |
| `slab` not set | Forest plot shows row numbers | Set `slab` in `escalc()` or `rma()` |
| `png()`/`pdf()` to wrong path | Security violation | Use `Sys.getenv("OUTPUT_DIR")` |
| Egger's test not run | Publication bias unchecked | Run `regtest()` for all meta-analyses |
