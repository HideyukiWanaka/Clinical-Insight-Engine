# R Multivariate Analysis Reference
# Domain: R
# Version: 1.0.0
# Status: Stable
# Package versions: base R ≥ 4.3.0, broom ≥ 1.0, gtsummary ≥ 1.7
# Consumers: statistics
# Source: R base documentation, bookdown.org/pdr_higgins, stat.ethz.ch/R-manual (2025)
# Immutable during execution (AP-014)

## Purpose

Provides the Statistics Agent with accurate implementation patterns for
multiple linear regression, logistic regression, model comparison, and
result extraction — including correct OR/CI computation and assumption checking.

---

## PART 1 — Multiple Linear Regression (lm)

### Model fitting

```r
model_lm <- lm(
  formula = outcome_var ~ predictor1 + predictor2 + covariate1,
  data    = data,
  na.action = na.omit    # Default: listwise deletion
)
```

### Extracting results

```r
lm_summary <- summary(model_lm)

# Coefficients table: estimate, SE, t, p
coef_table <- lm_summary$coefficients

# Individual values
beta_pred1  <- coef(model_lm)["predictor1"]
se_pred1    <- lm_summary$coefficients["predictor1", "Std. Error"]
p_pred1     <- lm_summary$coefficients["predictor1", "Pr(>|t|)"]

# Model fit
r_squared   <- lm_summary$r.squared
adj_r_sq    <- lm_summary$adj.r.squared
f_stat      <- lm_summary$fstatistic[1]
f_p_value   <- pf(lm_summary$fstatistic[1],
                  lm_summary$fstatistic[2],
                  lm_summary$fstatistic[3],
                  lower.tail = FALSE)

# 95% Confidence intervals for all coefficients
ci_lm <- confint(model_lm, level = 0.95)
# ci_lm["predictor1", "2.5 %"]  — lower bound
# ci_lm["predictor1", "97.5 %"] — upper bound
```

### Using broom for tidy output (recommended)
```r
library(broom)

# Tidy coefficient table
tidy_lm <- tidy(model_lm, conf.int = TRUE, conf.level = 0.95)
# Columns: term, estimate, std.error, statistic, p.value, conf.low, conf.high

# Model-level statistics
glance_lm <- glance(model_lm)
# Columns: r.squared, adj.r.squared, sigma, statistic, p.value, df, AIC, BIC, ...
```

### Post-hoc: Checking assumptions after fitting
```r
library(car)

# 1. Normality of residuals
shapiro.test(residuals(model_lm))

# 2. Homoscedasticity (Breusch-Pagan via car)
car::ncvTest(model_lm)  # p < 0.05 → heteroscedasticity

# 3. Multicollinearity
car::vif(model_lm)

# 4. Influential observations
cooks_d <- cooks.distance(model_lm)
n_influential <- sum(cooks_d > 4 / nrow(data))

# 5. Linearity — component-plus-residual plots
car::crPlots(model_lm)
```

---

## PART 2 — Logistic Regression (glm, binary outcome)

### Model fitting

```r
model_glm <- glm(
  formula  = outcome_var ~ predictor1 + predictor2 + covariate1,
  data     = data,
  family   = binomial(link = "logit"),
  na.action = na.omit
)
```

### Extracting Odds Ratios and 95% CI

```r
# METHOD 1 — Base R (profile likelihood CI — preferred)
# confint() for glm uses profile likelihood (not Wald) — more accurate
or_table <- exp(cbind(
  OR       = coef(model_glm),
  CI_lower = confint(model_glm)[, "2.5 %"],   # Profile likelihood
  CI_upper = confint(model_glm)[, "97.5 %"]
))
# Note: confint() for glm requires MASS to be loadable (it is in base R ≥ 4.3)

# METHOD 2 — Wald CI (faster but less accurate)
or_wald <- exp(cbind(
  OR       = coef(model_glm),
  CI_lower = coef(model_glm) - 1.96 * sqrt(diag(vcov(model_glm))),
  CI_upper = coef(model_glm) + 1.96 * sqrt(diag(vcov(model_glm)))
))
```

### Critical: Always use profile likelihood CI for glm
Profile likelihood CI is preferred to Wald CI based on asymptotic normality,
since the coefficient's standard error is sensitive to small deviations from
model assumptions. Use `confint(model_glm)` not `confint.default()`.

### Using broom for tidy OR extraction
```r
library(broom)

# Tidy with exponentiation for OR directly
tidy_glm <- tidy(model_glm,
                  exponentiate = TRUE,   # exp(estimate) = OR
                  conf.int     = TRUE,   # Profile likelihood CI by default
                  conf.level   = 0.95)
# Columns: term, estimate(=OR), std.error, statistic, p.value, conf.low, conf.high
```

### Extracting p-values and model fit
```r
glm_summary <- summary(model_glm)

# Individual p-values (on log-odds scale)
p_pred1 <- glm_summary$coefficients["predictor1", "Pr(>|z|)"]

# Model fit
aic_val    <- AIC(model_glm)
bic_val    <- BIC(model_glm)
null_dev   <- glm_summary$null.deviance
resid_dev  <- glm_summary$deviance
deviance_df <- glm_summary$df.residual

# Pseudo R² (McFadden)
mcfadden_r2 <- 1 - (model_glm$deviance / model_glm$null.deviance)
```

### Firth penalized logistic regression (rare events)
```r
library(logistf)
# Use when: outcome prevalence < 10%, or any cell in 2×2 table = 0

model_firth <- logistf(
  formula = outcome_var ~ predictor1 + predictor2,
  data    = data,
  flic    = FALSE    # FALSE = standard Firth; TRUE = FLIC (for interactions)
)

# Extract results
or_firth <- exp(coef(model_firth))
ci_firth <- exp(confint(model_firth))
p_firth  <- model_firth$prob   # p-values
```

---

## PART 3 — Model Comparison

### Likelihood Ratio Test (nested models)
```r
# Both models must use the same data and same na.action
model_full    <- glm(outcome ~ pred1 + pred2 + pred3, family = binomial, data = data)
model_reduced <- glm(outcome ~ pred1 + pred2,          family = binomial, data = data)

lrt <- anova(model_reduced, model_full, test = "LRT")
# LRT chi-square statistic and p-value
lrt_chisq <- lrt$Deviance[2]
lrt_df    <- lrt$Df[2]
lrt_p     <- lrt$`Pr(>Chi)`[2]
```

### AIC / BIC comparison (non-nested models)
```r
AIC(model_a, model_b)   # Lower AIC = better fit with fewer parameters
BIC(model_a, model_b)   # Lower BIC = better; penalizes complexity more than AIC
```

### stepAIC for variable selection (use cautiously)
```r
library(MASS)
# Forward, backward, or both directions
model_step <- MASS::stepAIC(model_full, direction = "both", trace = FALSE)
# NOTE: Stepwise selection produces optimistic p-values — always validate
```

---

## PART 4 — gtsummary Regression Tables

```r
library(gtsummary)

# Linear regression table
tbl_lm <- model_lm |>
  tbl_regression(
    label       = list(predictor1 ~ "Predictor 1 Label"),
    conf.level  = 0.95,
    intercept   = FALSE  # Omit intercept row (typical for clinical papers)
  )

# Logistic regression table (auto-exponentiates to OR)
tbl_glm <- model_glm |>
  tbl_regression(
    exponentiate = TRUE,  # Show OR instead of log-odds
    conf.level   = 0.95
  ) |>
  add_global_p()  # Add global p-value per variable

# Cox regression table
library(survival)
tbl_cox <- coxph(Surv(time, status) ~ predictor1 + predictor2, data = data) |>
  tbl_regression(
    exponentiate = TRUE  # Show HR instead of log-HR
  )
```

---

## PART 5 — Complete Multivariate Analysis Pipeline

```r
library(broom)
library(gtsummary)
library(car)

# 1. Fit model
model <- glm(outcome_var ~ predictor1 + predictor2 + covariate1,
             family = binomial(link = "logit"), data = data)

# 2. Assumption checks
vif_result <- car::vif(model)
assumption_passed <- all(vif_result < 5)

# 3. Extract tidy results
results_tidy <- tidy(model, exponentiate = TRUE, conf.int = TRUE)

# 4. Model-level stats
results_model <- glance(model)
results_model$mcfadden_r2 <- 1 - (model$deviance / model$null.deviance)

# 5. Structure output
multivariate_results <- list(
  execution_id    = Sys.getenv("CIE_EXECUTION_ID"),
  method          = "logistic_regression",
  n_observations  = nrow(model$model),
  n_events        = sum(model$y),
  coefficients    = results_tidy,          # OR, CI, p-value per predictor
  model_fit       = results_model,         # AIC, BIC, McFadden R²
  vif             = vif_result,
  assumption_vif_passed = assumption_passed,
  session_info    = sessionInfo(),
  dataset_hash    = digest::digest(data, algo = "sha256")
)

saveRDS(multivariate_results,
        file.path(Sys.getenv("OUTPUT_DIR"), "multivariate_results.rds"))
```

---

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| OR = exp(coef) without CI | Forgetting to exponentiate CI separately | Use `exp(confint(model))` or `tidy(..., exponentiate=TRUE, conf.int=TRUE)` |
| Wald CI for glm | Using `confint.default()` | Use `confint()` for profile likelihood CI |
| p-value from summary on log scale | Interpreting log-odds p-value as OR p-value | p-values do not change with exponentiation — use as-is |
| Model comparison on different n | `na.omit` default differs per model | Explicitly filter `data` before fitting all models |
| Stepwise p-values trusted | Optimistic due to selection | Report as exploratory only; validate on holdout data |
| `family="gaussian"` in glm | Unnecessary but not wrong | Use `lm()` directly instead |
