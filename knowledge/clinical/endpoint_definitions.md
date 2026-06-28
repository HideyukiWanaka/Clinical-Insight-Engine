# Clinical Endpoint Definitions
# Domain: clinical
# Version: 1.0.0
# Status: Stable
# Consumers: planner, data-quality, statistics
# Immutable during execution (AP-014)

## Purpose

Enables the Planner Agent to correctly map outcome variables to statistical
types, and the Data Quality Agent to apply clinically plausible range
constraints during validation.

---

## Endpoint Classification Framework

### Step 1 — Identify Endpoint Role

| Role | Definition | var_n mapping |
|------|-----------|---------------|
| Primary outcome | The pre-specified main endpoint the study is powered to detect | `role=primary_outcome` |
| Secondary outcome | Additional endpoints of interest, not powering the study | `role=secondary_outcome` |
| Time-to-event | Duration until an event occurs (survival endpoint) | `role=time_to_event` |
| Event indicator | Binary flag indicating whether the event occurred (1=event, 0=censored) | `role=event_indicator` |
| Primary predictor | Main exposure or treatment variable | `role=primary_predictor` |
| Covariate | Adjustment variable included to control confounding | `role=covariate` |
| Grouping variable | Variable defining comparison groups | `role=grouping_variable` |

### Step 2 — Map to Statistical Data Type

| Clinical variable type | Statistical type | outcome_type mapping |
|-----------------------|-----------------|----------------------|
| Continuous measurement (BP, BMI, lab value) | Continuous | `continuous` |
| Binary event (alive/dead, responder/non-responder) | Categorical binary | `categorical_binary` |
| Ordered categories (severity grade 1–4, pain scale) | Categorical ordinal | `categorical_ordinal` |
| Unordered categories (blood type, treatment arm >2) | Categorical nominal | `categorical_nominal` |
| Time until event (days to relapse, OS months) | Survival | `survival` |
| Free text, narrative | Text | not eligible for quantitative analysis |

---

## Clinically Plausible Range Constraints

Used by Data Quality Agent for `clinical_range_violation` flagging.
Values outside these ranges should be flagged as critical issues.

### Vital Signs

| Variable | Plausible Range | Unit | Notes |
|---------|----------------|------|-------|
| Systolic BP | 50 – 300 | mmHg | |
| Diastolic BP | 20 – 200 | mmHg | Must be < Systolic |
| Heart rate | 20 – 300 | bpm | |
| Respiratory rate | 4 – 60 | breaths/min | |
| SpO2 | 50 – 100 | % | |
| Temperature (oral) | 32.0 – 43.0 | °C | |
| Temperature (oral) | 89.6 – 109.4 | °F | |

### Anthropometric

| Variable | Plausible Range | Unit | Notes |
|---------|----------------|------|-------|
| BMI | 10.0 – 80.0 | kg/m² | |
| Body weight (adult) | 20 – 300 | kg | Adjust for pediatric |
| Height (adult) | 100 – 230 | cm | Adjust for pediatric |
| Age | 0 – 130 | years | |

### Common Laboratory Values

| Variable | Plausible Range | Unit | Notes |
|---------|----------------|------|-------|
| Hemoglobin | 3.0 – 25.0 | g/dL | |
| WBC | 0.1 – 100.0 | ×10³/μL | |
| Platelets | 1 – 2000 | ×10³/μL | |
| Serum sodium | 100 – 180 | mEq/L | |
| Serum potassium | 1.5 – 9.0 | mEq/L | |
| Serum creatinine | 0.1 – 30.0 | mg/dL | |
| Blood glucose (fasting) | 30 – 1500 | mg/dL | |
| HbA1c | 3.0 – 20.0 | % | |
| ALT / AST | 1 – 10000 | U/L | |
| Total bilirubin | 0.1 – 60.0 | mg/dL | |

### Survival / Time Variables

| Variable | Plausible Range | Unit | Notes |
|---------|----------------|------|-------|
| Follow-up duration | 0 – 43800 | days | 0–120 years |
| Time to event | 0 – 43800 | days | Must be ≥ 0 |
| Event indicator | 0 or 1 | binary | No other values permitted |

---

## Primary vs Surrogate Endpoints

| Type | Definition | Statistical Consideration |
|------|-----------|--------------------------|
| Primary (clinical) endpoint | Directly meaningful outcome (death, MI, hospitalization) | Powers the study; drives sample size |
| Surrogate endpoint | Biomarker presumed to predict clinical outcome (HbA1c for diabetes complications) | Lower level of evidence; note in limitations |
| Composite endpoint | Combines multiple events (MACE = MI + stroke + death) | Analyze components separately in addition to composite |
| Patient-reported outcome (PRO) | Self-reported symptom burden, QoL scores | Validate instrument; report minimal clinically important difference (MCID) |

---

## Variable Mapping Decision Rules for Planner Agent

### Rule EP-001 — Continuous outcome identification
If the outcome variable description includes any of: "level", "value", "score",
"measurement", "concentration", "rate" → classify as `outcome_type=continuous`.

### Rule EP-002 — Binary outcome identification
If the outcome variable description includes any of: "yes/no", "presence/absence",
"occurred/did not occur", "responder", "event" → classify as `outcome_type=categorical_binary`.

### Rule EP-003 — Survival outcome identification
If the outcome involves both a time variable AND an event indicator variable →
classify as `outcome_type=survival`. Map both variables with appropriate roles.

### Rule EP-004 — Ambiguous ordinal vs continuous
If variable has ordered categories but ≥ 10 levels and approximately continuous
distribution → may be treated as continuous with justification.
If < 10 ordered levels → classify as `outcome_type=categorical_ordinal`.
Set `requires_human_clarification=true` when borderline.

### Rule EP-005 — Multiple outcomes
If multiple outcome variables are present → identify one as `primary_outcome`
based on study context. Assign others as `secondary_outcome`.
If primary outcome cannot be determined → set `requires_human_clarification=true`.
