# Statistical Result Interpretation Guide
# Domain: statistics
# Version: 1.0.0
# Status: Stable
# Consumers: statistics, reporting, reviewer
# Immutable during execution (AP-014)

## Purpose

Provides structured interpretation rules for statistical outputs, enabling the
Statistics Agent to produce interpretation_guidelines, the Reporting Agent to
translate results into accurate manuscript text, and the Reviewer Agent to
validate that reported interpretations are consistent with numerical outputs.

---

## P-Value Interpretation Rules

### Rule INT-001 — p-value is NOT the probability that H0 is true
**Correct statement:** "There was a statistically significant difference (p = 0.023)."
**Incorrect statement:** "There is a 97.7% probability that the groups differ."

### Rule INT-002 — Report exact p-values
- Report exact p-values to 3 decimal places: `p = 0.023`
- Exception: `p < 0.001` when value is extremely small
- Never report `p = 0.000` — use `p < 0.001`
- Never report `p = NS` — report the actual value

### Rule INT-003 — Statistical vs clinical significance
- Statistical significance (p < 0.05) does not imply clinical importance.
- Always accompany p-values with effect size and confidence interval.
- Manuscripts must address clinical significance separately from statistical significance.

### Rule INT-004 — Borderline significance
- p-values between 0.05 and 0.10 must not be described as "significant" or "trend toward significance."
- Acceptable: "did not reach statistical significance (p = 0.07)"

---

## Effect Size Interpretation

### Continuous Outcomes — Cohen's d

| d value | Interpretation |
|---------|---------------|
| < 0.2 | Negligible |
| 0.2 – 0.49 | Small |
| 0.5 – 0.79 | Medium |
| ≥ 0.8 | Large |

**Manuscript template:**
`"The mean difference was X (95% CI: [lower, upper]), representing a [small/medium/large] effect (d = Y)."`

### Categorical Outcomes — Odds Ratio

| OR value | Interpretation direction |
|----------|------------------------|
| OR = 1.0 | No association |
| OR > 1.0 | Increased odds in exposed group |
| OR < 1.0 | Decreased odds in exposed group |

**Reviewer check:** If p < 0.05, the 95% CI must NOT include 1.0. Flag as critical if violated.

### Survival Outcomes — Hazard Ratio

| HR value | Interpretation |
|----------|---------------|
| HR = 1.0 | Equal hazard in both groups |
| HR > 1.0 | Higher hazard (shorter survival) in exposed |
| HR < 1.0 | Lower hazard (longer survival) in exposed |

**Reviewer check:** If p < 0.05, the 95% CI must NOT include 1.0.

### Correlation Coefficients

| |r| value | Interpretation |
|-----------|---------------|
| < 0.1 | Negligible |
| 0.1 – 0.29 | Weak |
| 0.3 – 0.49 | Moderate |
| ≥ 0.5 | Strong |

---

## Confidence Interval Interpretation Rules

### Rule CI-001 — Width indicates precision
- Narrow CI → high precision (large sample or low variability)
- Wide CI → low precision; note as limitation

### Rule CI-002 — Direction of CI
- If entire CI is on one side of null → consistent direction of effect
- If CI crosses null → inconclusive; do not overinterpret point estimate

### Rule CI-003 — CI consistency check (Reviewer Agent use)
- If p < 0.05 AND CI includes null value → critical finding (numerical inconsistency)
- If p > 0.05 AND CI excludes null value → critical finding (numerical inconsistency)

---

## Manuscript Result Reporting Templates

### Template R-001 — Continuous outcome, two groups
```
"[Outcome] was significantly [higher/lower] in [Group A] than [Group B]
(mean ± SD: X ± Y vs. A ± B; mean difference: D, 95% CI: [L, U]; p = 0.XXX; Cohen's d = Z)."
```

### Template R-002 — Categorical outcome, two groups
```
"The proportion of [outcome event] was [higher/lower] in [Group A] than [Group B]
(X% vs. Y%; OR: Z, 95% CI: [L, U]; p = 0.XXX)."
```

### Template R-003 — Survival analysis
```
"[Group A] demonstrated [longer/shorter] [outcome] compared with [Group B]
(median [outcome]: X months vs. Y months; HR: Z, 95% CI: [L, U]; log-rank p = 0.XXX)."
```

### Template R-004 — Non-significant result
```
"No statistically significant difference was observed in [outcome] between
[Group A] and [Group B] (mean difference: D, 95% CI: [L, U]; p = 0.XXX)."
```

**Reporting Agent must select the appropriate template based on `selected_methods`
in the analysis_plan and populate with values from execution_result.**

---

## Reviewer Agent Consistency Checks

Cross-reference against reviewer.yaml consistency_checks:

| Check | Verification rule |
|-------|------------------|
| CC-001 | p-value in manuscript ± 0.001 of execution_result value |
| CC-002 | Effect size in manuscript ± tolerance of execution_result value |
| CC-003 | n per group in manuscript matches dataset row counts |
| CC-006 | CI direction consistent with p-value (Rule CI-003 above) |

Any violation must be classified as `critical_finding` in the review_report.
