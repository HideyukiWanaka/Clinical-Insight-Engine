# Clinical Study Designs
# Domain: clinical
# Version: 1.0.0
# Status: Stable
# Consumers: planner, statistics, reporting
# Immutable during execution (AP-014)

## Purpose

This document enables the Planner Agent to correctly classify clinical study
designs from natural language descriptions, and guides the Statistics and
Reporting Agents in applying appropriate methods and reporting checklists.

---

## Study Design Classification Guide

### Step 1 — Determine Assignment Mechanism

| Signal in prompt | Design class |
|-----------------|-------------|
| "randomly assigned", "randomized", "RCT" | Randomized Controlled Trial |
| "exposed vs unexposed", "risk factor", no randomization | Observational |
| "cases and controls", "case-control" | Case-Control |
| "followed over time", "incidence", "prospective" | Cohort |
| "at one point in time", "prevalence", "cross-sectional" | Cross-Sectional |
| "predict", "model", "score", "risk prediction" | Prediction Model |
| "systematic review", "meta-analysis", "pooled" | Systematic Review / Meta-Analysis |
| "sensitivity", "specificity", "AUC", "diagnostic" | Diagnostic Accuracy |

### Step 2 — Confirm Temporal Direction

| Direction | Implication |
|-----------|-------------|
| Exposure → Outcome (forward in time) | Cohort or RCT |
| Outcome → Exposure (backward in time) | Case-Control |
| Both measured simultaneously | Cross-Sectional |
| Multiple time points per subject | Longitudinal / Repeated Measures |

### Step 3 — Assign Reporting Checklist

| Study Design | Reporting Checklist | Key Reference |
|-------------|---------------------|---------------|
| RCT | CONSORT 2010 | Schulz et al., BMJ 2010 |
| Observational (cohort, case-control, cross-sectional) | STROBE 2007 | von Elm et al., Ann Intern Med 2007 |
| Prediction Model (development or validation) | TRIPOD 2015 | Collins et al., Ann Intern Med 2015 |
| Systematic Review / Meta-Analysis | PRISMA 2020 | Page et al., BMJ 2021 |
| Diagnostic Accuracy | STARD 2015 | Bossuyt et al., BMJ 2015 |

---

## Study Design Definitions

### Randomized Controlled Trial (RCT)
- Participants are randomly allocated to intervention or control groups.
- Gold standard for causal inference.
- Key elements: randomization, allocation concealment, blinding, intention-to-treat analysis.
- Intent object mapping: `objective=between_group_comparison`, `study_design=randomized_controlled_trial`

### Cohort Study
- A defined group is followed over time to observe outcomes.
- Can be prospective (exposure defined before outcome) or retrospective.
- Suitable for incidence rates, relative risk, and hazard ratios.
- Intent object mapping: `study_design=cohort`

### Case-Control Study
- Cases (with outcome) and controls (without outcome) are identified, then past exposures compared.
- Efficient for rare outcomes. Produces odds ratios, not relative risks.
- Intent object mapping: `study_design=case_control`

### Cross-Sectional Study
- Exposure and outcome measured at the same time.
- Suitable for prevalence estimates and association analysis.
- Cannot establish temporality or causation.
- Intent object mapping: `study_design=cross_sectional`

### Prediction Model Study
- Develops or validates a statistical model to predict an outcome in new individuals.
- Requires discrimination (AUC/C-statistic) and calibration assessment.
- Intent object mapping: `objective=prediction_model`, `study_design=prediction_model`

### Diagnostic Accuracy Study
- Evaluates a test against a reference standard.
- Key metrics: sensitivity, specificity, PPV, NPV, LR+, LR−, AUC.
- Intent object mapping: `objective=diagnostic_accuracy`, `study_design=diagnostic_accuracy_study`

---

## Common Ambiguities and Resolution Rules

### Ambiguity 1 — "Compare outcomes between groups" without randomization
- If no mention of randomization → classify as `observational`
- Set `requires_human_clarification=false` only if cohort vs case-control can be determined from temporal cues
- If temporal direction unclear → set `requires_human_clarification=true`

### Ambiguity 2 — "Analyze survival" or "time to event"
- Map to `objective=survival_analysis`, `outcome_type=survival`
- Study design may still be RCT or cohort — determine separately

### Ambiguity 3 — "Predict" vs "Compare"
- "Predict which patients will..." → `objective=prediction_model`
- "Compare outcomes between patients who received X vs Y" → `objective=between_group_comparison`
- If both objectives appear → set `requires_human_clarification=true` with two mutually exclusive clarification_options

### Ambiguity 4 — Retrospective chart review
- Common in clinical research; maps to `study_design=observational` (cohort or cross-sectional)
- Apply STROBE checklist
- Flag lack of prospective data collection as a limitation in unresolved_items

---

## Confounding and Bias — Key Concepts for Planner and Statistics Agents

| Concept | Definition | Statistical Implication |
|---------|-----------|------------------------|
| Confounding | Third variable associated with both exposure and outcome | Consider multivariable adjustment, matching, or propensity scoring |
| Selection bias | Non-representative sample | Limit claims; note in limitations |
| Information bias | Measurement error or misclassification | Note in limitations |
| Intention-to-treat (ITT) | Analyze participants as randomized regardless of adherence | Required for RCTs; document if per-protocol analysis also performed |
| Per-protocol analysis | Analyze only adherent participants | Supplementary to ITT in RCTs |

---

## References
- CONSORT: http://www.consort-statement.org
- STROBE: https://www.strobe-statement.org
- TRIPOD: https://www.tripod-statement.org
- PRISMA: http://www.prisma-statement.org
- STARD: https://www.equator-network.org/reporting-guidelines/stard
