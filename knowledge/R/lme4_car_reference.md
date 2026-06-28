# R lme4 & car Package Function Reference
# Domain: R
# Version: 1.0.0
# Status: Stable
# Package versions: lme4 ≥ 1.1-37 (2025-03-26), car 3.1-5 (2026-01-05)
# Consumers: statistics
# Source: CRAN lme4/car documentation, lme4 NEWS, RDocumentation (2025-2026)
# Immutable during execution (AP-014)

## Purpose

Provides the Statistics Agent with accurate, argument-level reference for
mixed-effects models (lme4) and regression diagnostics (car). Covers
deprecated patterns and breaking changes critical for correct code generation.

---

## PART 1 — lme4 Package

---

## lmer() — Linear Mixed-Effects Models

```r
lmer(
  formula = outcome ~ fixed_pred + (1 | subject_id),
  data    = data,
  REML    = TRUE,     # Use REML (default) for variance estimates; FALSE for model comparison
  control = lmerControl(optimizer = "bobyqa")
)
```

### Random effects formula syntax

| Formula | Meaning |
|---------|---------|
| `(1 \| id)` | Random intercept per subject |
| `(1 + time \| id)` | Random intercept + random slope for time per subject |
| `(0 + time \| id)` | Random slope only (no random intercept) |
| `(1 \| clinic/subject)` | Nested: subject within clinic |
| `(1 \| clinic) + (1 \| subject)` | Crossed random effects |

### REML vs ML — critical distinction

| Use case | REML argument | Reason |
|---------|--------------|--------|
| Estimating variance components | `REML = TRUE` (default) | Unbiased variance estimates |
| Comparing models with different **fixed** effects | `REML = FALSE` | LRT requires ML |
| Comparing models with different **random** effects | `REML = TRUE` | LRT valid with REML |

```r
# Model comparison — must use REML=FALSE for different fixed effects
m_full    <- lmer(outcome ~ pred1 + pred2 + (1|id), data = data, REML = FALSE)
m_reduced <- lmer(outcome ~ pred1 + (1|id),          data = data, REML = FALSE)
anova(m_reduced, m_full)  # Likelihood ratio test
```

### Deprecated patterns in lme4

```r
# DEPRECATED — do not use
lmer(outcome ~ pred + (1|id), data = data, method = "ML")
# Fix: use REML = FALSE instead of method argument

# DEPRECATED — do not use
glmer(outcome ~ pred + (1|id), data = data, family = "gaussian")
# Fix: use lmer() directly for Gaussian outcomes

# CORRECT
lmer(outcome ~ pred + (1|id), data = data, REML = FALSE)
```

### Extracting results from lmer()

```r
fit <- lmer(outcome ~ predictor + (1|id), data = data)

# Fixed effects with confidence intervals
fixef(fit)                           # Point estimates
confint(fit, method = "Wald")        # Wald CIs (fast)
confint(fit, method = "profile")     # Profile CIs (accurate, slower)
confint(fit, method = "boot", nsim = 1000)  # Bootstrap CIs

# Random effects
ranef(fit)                           # BLUP estimates per subject
VarCorr(fit)                         # Variance components

# Model fit indices
AIC(fit)
BIC(fit)
logLik(fit)
```

### Checking convergence warnings

```r
# lme4 ≥ 1.1 produces convergence warnings — always check
fit <- lmer(outcome ~ predictor + (1 + time | id), data = data)

# If convergence warning appears:
# Option 1 — Try bobyqa optimizer
fit <- lmer(outcome ~ predictor + (1 + time | id), data = data,
            control = lmerControl(optimizer = "bobyqa"))

# Option 2 — Try Nelder_Mead
fit <- lmer(outcome ~ predictor + (1 + time | id), data = data,
            control = lmerControl(optimizer = "Nelder_Mead"))

# Option 3 — Simplify random effects structure
fit <- lmer(outcome ~ predictor + (1 | id), data = data)  # Drop random slope
```

---

## glmer() — Generalized Linear Mixed-Effects Models

```r
glmer(
  formula = outcome ~ fixed_pred + (1 | subject_id),
  data    = data,
  family  = binomial(link = "logit"),  # For binary outcomes
  control = glmerControl(optimizer = "bobyqa")
)
```

### Supported families

| Outcome type | family argument |
|-------------|----------------|
| Binary (0/1) | `binomial(link = "logit")` |
| Count (Poisson) | `poisson(link = "log")` |
| Ordered categorical | Use `ordinal::clmm()` instead |

### Critical: do NOT use glmer for Gaussian outcomes

```r
# WRONG — generates deprecation warning in lme4 ≥ 1.0
glmer(outcome ~ pred + (1|id), family = "gaussian", data = data)

# CORRECT — use lmer() directly
lmer(outcome ~ pred + (1|id), data = data)
```

### Extracting OR from glmer (binary outcome)

```r
fit_glmer <- glmer(event ~ pred + (1|id), data = data, family = binomial)

# Odds ratios and 95% CI
or_table <- exp(cbind(
  OR       = fixef(fit_glmer),
  CI_lower = confint(fit_glmer, method = "Wald")[names(fixef(fit_glmer)), 1],
  CI_upper = confint(fit_glmer, method = "Wald")[names(fixef(fit_glmer)), 2]
))
```

---

## PART 2 — car Package (Companion to Applied Regression)

### car package version: 3.1-5 (2026-01-05)

---

## leveneTest() — Homoscedasticity Test

```r
# Method 1 — Formula interface (recommended)
car::leveneTest(outcome ~ group, data = data)

# Method 2 — Default (vector + group factor)
car::leveneTest(y = data$outcome, group = data$group)

# Method 3 — From lm object
car::leveneTest(lm(outcome ~ group, data = data))
```

### Arguments
| Argument | Default | Description |
|---------|---------|-------------|
| `center` | `median` | `median` = Brown-Forsythe (robust, recommended); `mean` = original Levene's test |
| `data` | — | Required when using formula interface |

### Interpretation
- p > 0.05 → Homoscedasticity assumed (proceed with equal-variance methods)
- p < 0.05 → Heteroscedasticity detected

```r
# Robust version (default, recommended for clinical data)
result <- car::leveneTest(outcome ~ group, data = data, center = median)

# If p < 0.05:
# For t-test: use Welch t-test (default in R: t.test(..., var.equal = FALSE))
# For ANOVA: use Welch's ANOVA: oneway.test(outcome ~ group, var.equal = FALSE)
```

---

## vif() — Variance Inflation Factor

```r
# Basic usage — fit model first, then check VIF
model <- lm(outcome ~ pred1 + pred2 + pred3, data = data)
car::vif(model)
```

### Output interpretation

| VIF value | Interpretation | Action |
|----------|---------------|--------|
| < 3 | Low multicollinearity | None required |
| 3 – 5 | Moderate | Document; consider removal |
| 5 – 10 | High | Advisory finding; investigate |
| ≥ 10 | Critical multicollinearity | Remove or combine predictors |

### Important: GVIF for categorical variables

When any predictor has > 1 degree of freedom (e.g. a factor with ≥ 3 levels),
`vif()` returns **GVIF** (Generalized VIF), not simple VIF:

```r
vif(lm(outcome ~ continuous_pred + factor_pred, data = data))
# Returns: GVIF, Df, GVIF^(1/(2*Df))
# Use GVIF^(1/(2*Df)) for comparison — equivalent to sqrt(VIF) for 1-df terms
# Rule: GVIF^(1/(2*Df)) > sqrt(5) ≈ 2.24 indicates concern
```

### VIF for glmer / lmer models

```r
# car::vif() works on lme4 objects
model_lmer <- lmer(outcome ~ pred1 + pred2 + (1|id), data = data)
car::vif(model_lmer)  # Returns VIF for fixed effects only
```

---

## crPlots() — Component-Plus-Residual Plots (Linearity Check)

```r
model <- lm(outcome ~ pred1 + pred2, data = data)
car::crPlots(model)              # All predictors
car::crPlots(model, var = "pred1")  # Single predictor
```

**Purpose:** Detects non-linearity between each predictor and the outcome.
A curved pattern indicates a non-linear relationship → consider polynomial or spline terms.

---

## outlierTest() — Bonferroni Outlier Test

```r
model <- lm(outcome ~ predictors, data = data)
car::outlierTest(model)
# Returns: largest |studentized residual| with Bonferroni-corrected p-value
# p < 0.05 → statistically significant outlier
```

---

## Complete Assumption Checking Pipeline

```r
library(car)

# Fit primary model
model <- lm(outcome ~ pred1 + pred2 + pred3, data = data)

# 1. Normality of residuals
shapiro.test(residuals(model))

# 2. Homoscedasticity
car::leveneTest(outcome ~ group, data = data)
# Or: plot(model, which = 3)  — Scale-Location plot

# 3. Linearity
car::crPlots(model)

# 4. Multicollinearity
vif_result <- car::vif(model)

# 5. Influential observations
car::outlierTest(model)
cooks_d <- cooks.distance(model)
influential <- which(cooks_d > 4 / nrow(data))

# 6. Independence (visual only)
plot(residuals(model))  # No pattern expected

# Structure output for assumption_checks_required
assumption_results <- list(
  normality          = list(method = "shapiro.test",
                            p_value = shapiro.test(residuals(model))$p.value,
                            passed  = shapiro.test(residuals(model))$p.value > 0.05),
  homoscedasticity   = list(method = "leveneTest",
                            p_value = car::leveneTest(outcome ~ group, data=data)[1,"Pr(>F)"],
                            passed  = car::leveneTest(outcome ~ group, data=data)[1,"Pr(>F)"] > 0.05),
  multicollinearity  = list(method = "vif",
                            values = vif_result,
                            passed = all(vif_result < 5)),
  influential_points = list(method = "cooks_distance",
                            n_influential = length(influential),
                            indices = influential)
)
```

---

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `glmer(..., family="gaussian")` warning | Deprecated since lme4 1.0 | Use `lmer()` |
| `method="ML"` argument in lmer | Deprecated since lme4 1.0 | Use `REML=FALSE` |
| Convergence warning not handled | Complex random structure | Try `bobyqa`, simplify, or increase iterations |
| VIF interpreted incorrectly for factors | GVIF returned, not VIF | Use `GVIF^(1/(2*Df))` column |
| `leveneTest` with character grouping | Group must be factor | `data$group <- as.factor(data$group)` |
| Model comparison with REML=TRUE | Biased LRT for fixed effects | Set `REML=FALSE` for both models |
