# CIE Platform — Test Execution Plan

## Overview
This document defines 6 comprehensive test scenarios to validate that the CIE platform meets MVP requirements and performs as designed. Each scenario uses the `health_screening_japan.csv` test dataset (190 records, 150 unique subjects with 40 two-year follow-ups).

---

## Test Dataset Summary
- **File**: `test_data/health_screening_japan.csv`
- **Records**: 190 (150 baseline + 40 follow-up)
- **Subjects**: 150 unique (患者ID: PID00001-PID00150)
- **Years**: 2024 (baseline), 2025 (follow-up subset)
- **Variables**: 25 columns including demographics, vital signs, lab values
- **PII Content**: Patient names (患者氏名) for Layer 2 NLP detection testing
- **Data Quality**: Realistic missing values (2-5%), outliers, clinically implausible values

**Key Variables for Testing**:
- Demographics: 患者ID, 患者氏名, 施設コード, 検査年, 年齢, 性別
- Vitals: 身長_cm, 体重_kg, BMI, 収縮期血圧_mmHg, 拡張期血圧_mmHg
- Glucose: 空腹時血糖_mg_dl, HbA1c_percent
- Lipids: 総コレステロール_mg_dl, HDLコレステロール_mg_dl, LDLコレステロール_mg_dl, 中性脂肪_mg_dl
- Liver: AST_U_L, ALT_U_L, γ-GTP_U_L
- Kidney: クレアチニン_mg_dl, eGFR_ml_min, 尿酸_mg_dl
- Urinalysis: 尿蛋白, 尿糖

---

## Scenario 1: Basic Group Comparison (Two-Group T-Test)

**Clinical Question**: 
"Is systolic blood pressure different between male and female subjects?"

**Intent**:
```
Dataset: health_screening_japan.csv
Outcome: 収縮期血圧_mmHg (numeric)
Grouping variable: 性別 (categorical: 男性, 女性)
Analysis type: Comparison of means
Expected method: Independent samples t-test
```

**Expected Planner Behavior** (PL-001: Basic Intent Recognition):
- Identify outcome variable: 収縮期血圧_mmHg
- Identify grouping variable: 性別
- Recognize 2 groups → t-test (not ANOVA)
- Infer pairing: None (baseline only)

**Expected Statistics Agent Behavior**:
- Detect missing values in 収縮期血圧_mmHg (should be 0 - no missing)
- Check normality assumption
- Apply appropriate t-test (parametric or Mann-Whitney)
- Generate descriptive statistics by group

**Expected Results**:
- Descriptive stats: Mean SBP by gender
- Test statistic: t-value, p-value
- Confidence interval for difference
- Effect size: Cohen's d

**Validation Criteria**:
- ✓ Analysis completes without error
- ✓ P-value is 2-tailed
- ✓ Descriptive statistics match manual calculation
- ✓ Effect size (Cohen's d) calculated
- ✓ Audit log records: intent, data profile, method selection

**Execution Time Budget**: 30 seconds

---

## Scenario 2: Correlation Analysis (Continuous Variables)

**Clinical Question**:
"What is the correlation between BMI and HbA1c?"

**Intent**:
```
Dataset: health_screening_japan.csv
Variable 1: BMI (numeric)
Variable 2: HbA1c_percent (numeric)
Analysis type: Correlation
Expected method: Pearson correlation (if normal), Spearman (if skewed)
```

**Expected Planner Behavior** (PL-001: Intent Recognition):
- Identify 2 numeric variables
- Recognize correlation analysis request
- No grouping specified → single correlation

**Expected Statistics Agent Behavior**:
- Detect missing values in HbA1c_percent (~5% expected)
- Handle missing data: List-wise deletion or imputation
- Check normality (both variables)
- Select Pearson vs Spearman
- Calculate correlation coefficient and p-value
- Generate scatter plot (Visualization Agent)

**Expected Results**:
- Correlation coefficient (r or ρ)
- P-value
- 95% CI for correlation
- Scatter plot with regression line
- Residual diagnostics

**Validation Criteria**:
- ✓ Handles missing data in HbA1c_percent correctly
- ✓ Produces both Pearson and Spearman results
- ✓ P-value interpretation is correct
- ✓ Visualization is generated
- ✓ Quality review flags any correlations near 1.0 (data integrity check)

**Execution Time Budget**: 40 seconds

---

## Scenario 3: Paired Design / Repeated Measures (Critical for PL-004, PL-005)

**Clinical Question**:
"Did HbA1c change significantly from 2024 to 2025 in subjects with follow-up data?"

**Intent**:
```
Dataset: health_screening_japan.csv
Outcome: HbA1c_percent
Grouping: 検査年 (2024 vs 2025)
Pairing: 患者ID (same subject measured twice)
Expected method: Paired t-test
```

**Expected Planner Behavior** (PL-004: Paired Design Detection):
- Detect repeated 患者ID values → paired design
- Recognize within-subject structure
- Identify subject_id_var = 患者ID (PL-005)
- Identify time_var = 検査年
- Select paired analysis

**Expected Statistics Agent Behavior**:
- Validate pairing: Each subject has exactly 2 measurements
- Create wide-format data (baseline vs follow-up)
- Calculate within-subject differences
- Test normality of differences
- Apply paired t-test (or Wilcoxon if non-normal)
- Calculate effect size (Cohen's d for paired)

**Expected Results**:
- Descriptive stats: Baseline, Follow-up, Change
- Paired t-test results: t, df, p-value
- Mean change ± SD
- 95% CI for change
- Effect size

**Validation Criteria**:
- ✓ Correctly identifies paired structure (PL-004 verified)
- ✓ Correctly identifies subject_id_var = 患者ID (PL-005 verified)
- ✓ Excludes subjects with only 1 measurement
- ✓ Reports n for paired analysis (should be 40, not 150)
- ✓ Paired-specific statistics (not independent t-test)
- ✓ Audit log documents pairing detection

**Execution Time Budget**: 35 seconds

---

## Scenario 4: Multivariate Analysis (Multiple Regression with Continuous Predictors)

**Clinical Question**:
"What factors predict HbA1c? Model: HbA1c ~ BMI + 年齢 + 空腹時血糖_mg_dl"

**Intent**:
```
Dataset: health_screening_japan.csv
Outcome: HbA1c_percent (numeric)
Predictors: BMI, 年齢, 空腹時血糖_mg_dl (all numeric)
Analysis type: Multiple linear regression
```

**Expected Planner Behavior** (PL-001: Complex Intent):
- Parse multiple predictors
- Identify continuous outcome and predictors
- Select multiple regression
- No grouping → single regression model

**Expected Statistics Agent Behavior**:
- Detect multicollinearity (check VIF for age/glucose)
- Handle missing values in any predictor
- Fit linear model
- Generate model diagnostics:
  - Coefficients + CI + p-values
  - R² and adjusted R²
  - Residual plots
  - Influence diagnostics

**Expected Correction Application** (from Scenario 4 in evaluation):
- If multiple comparisons detected elsewhere → apply Bonferroni
- Document correction rationale

**Expected Results**:
- Regression table: β, SE, t, p-value for each predictor
- Model summary: R², adjusted R², F-test
- Residual plots: Q-Q, scale-location, residuals vs fitted
- Predictions on new data (if requested)

**Validation Criteria**:
- ✓ Correctly identifies 3 predictors
- ✓ VIF values calculated and checked (<5 typically acceptable)
- ✓ Handles missing values in glucose column
- ✓ R² interpretation is correct
- ✓ Residual diagnostics assessed
- ✓ Audit log documents model formula and assumptions checked

**Execution Time Budget**: 45 seconds

---

## Scenario 5: Quality Gate Blocking (Critical for MVP)

**Clinical Question**:
"Analyze cholesterol differences, but with data quality flagged."

**Setup**:
- Use health_screening_japan.csv as-is (contains outliers: extreme BP at indices 5, 10; extreme creatinine at index 10)
- Analysis: Total cholesterol by gender
- Data quality issues expected:
  - Clinically implausible creatinine (2.8 mg/dL at index 10)
  - Extreme HbA1c (15.2% at index 5) 
  - Missing values in multiple columns

**Expected Data Quality Agent Behavior**:
- Flag HbA1c > 12% as critical outlier
- Flag creatinine > 2.5 as critical (severe kidney disease)
- Flag missing HbA1c (5%) as warning
- Flag missing γ-GTP (5%) as warning
- Flag missing eGFR (5%) as warning
- Flag missing 尿蛋白 (5%) as warning
- Generate quality report

**Expected Quality Review Screen**:
- Display flagged records and issues
- Render visualization of outliers
- Provide options to:
  - Accept and proceed (document decision)
  - Exclude outlier records
  - Proceed with caveats

**Expected Reviewer Agent Behavior** (if proceeding to analysis):
- Flag in reporting: "Analysis includes clinically implausible values"
- Document rationale for inclusion
- Recommend additional clinical review

**Validation Criteria**:
- ✓ Data Quality Agent identifies all critical issues
- ✓ Quality Review screen is navigable and user can make decision
- ✓ If user proceeds: Reviewer adds quality caveat to results
- ✓ If user excludes outliers: Analysis runs on filtered data
- ✓ Audit log records quality decisions
- ✓ Results clearly document data quality status

**Execution Time Budget**: 50 seconds (includes user interaction)

---

## Scenario 6: PII Detection and Redaction (Security Critical)

**Clinical Question**:
"Analyze data, but with PII detection active."

**Setup**:
- Use health_screening_japan.csv (contains 患者氏名 with realistic Japanese names)
- Enable PII detection in Planner or Data Quality Agent
- Expected PII in dataset:
  - Layer 1 (Regex): 患者ID pattern (PID followed by 5 digits)
  - Layer 2 (NLP): 患者氏名 (Japanese person names: 田中太郎, 鈴木花子, etc.)

**Expected Security Agent / Data Quality Agent Behavior**:
- Layer 1 detection: Identify all 患者ID values (should be 150 unique)
- Layer 2 detection: Identify 患者氏名 column as containing person names
  - Use NLP-based semantic detection
  - Compare against Japanese name dictionary
  - Flag with confidence score
- Generate PII report:
  - Column: 患者氏名
  - Risk level: HIGH (personally identifiable name)
  - Records affected: 150 (all)
  - Recommendation: Redact or use pseudonym

**Expected Redaction Options**:
- Replace 患者氏名 with hash or pseudonym
- Remove 患者氏名 column entirely
- Keep but flag in audit log

**Expected Results**:
- Analysis proceeds without transmitting real names in outputs
- Audit log records: PII detection, redaction method, by whom, when
- Reporting includes PII caveat: "Identifiable patient names removed"

**Validation Criteria**:
- ✓ Layer 1 detects 患者ID (all 150 records)
- ✓ Layer 2 detects 患者氏名 (all 150 records, high confidence)
- ✓ User can choose redaction method
- ✓ Redacted data used in analysis (not original names)
- ✓ Audit log documents PII handling
- ✓ Output reports do not contain real patient names
- ✓ Capability Token lifecycle: issued → used → revoked (audit log proof)

**Execution Time Budget**: 60 seconds

---

## Performance Metrics to Collect

For each scenario, measure:

1. **Planner LLM Response Time**:
   - Time to recognize intent and generate IntentObject
   - Token usage (input + output)

2. **Data Quality Agent Time**:
   - Time to validate dataset
   - Missing value detection time
   - Outlier detection time
   - PII detection time (especially Layer 2 NLP)

3. **Statistics Agent Time**:
   - Time to select method
   - Time to execute R code
   - Time for calculations

4. **Visualization Agent Time**:
   - Time to generate plots

5. **End-to-End Pipeline Time**:
   - Total time from intent input to results

6. **Accuracy Metrics**:
   - Statistical results matches hand-calculated values
   - Effect sizes correct
   - P-values appropriate

7. **Error Rate**:
   - Number of scenarios that complete without error
   - Nature of any errors

---

## Execution Checklist

### Pre-Execution
- [ ] Dependencies installed (pip install -e ".[ui]")
- [ ] Test data exists at test_data/health_screening_japan.csv
- [ ] Test data validated (190 rows, correct columns)
- [ ] Streamlit app launches without error: `streamlit run cie/ui/app.py`
- [ ] UI screens render correctly

### During Execution (Per Scenario)
- [ ] Scenario intent entered into app (natural language or form)
- [ ] Planner recognizes intent correctly
- [ ] Data Quality review screen shows findings
- [ ] User approves or modifies analysis
- [ ] Statistics analysis completes
- [ ] Results rendered in UI
- [ ] Audit log entry created
- [ ] Performance metrics recorded

### Post-Execution
- [ ] All 6 scenarios completed
- [ ] No critical errors
- [ ] Performance benchmarks meet expectations (<2 min per scenario)
- [ ] Audit log contains all 6 analysis records
- [ ] PII detection confirmed in Scenario 6
- [ ] Quality gate blocking confirmed in Scenario 5
- [ ] Paired design detection confirmed in Scenario 3

---

## Expected Outcomes

**Success Criteria** (MVP Validation):
1. ✓ All 6 scenarios execute without critical errors
2. ✓ Planner correctly recognizes intent in each scenario
3. ✓ Statistics methods selected appropriately
4. ✓ Results are scientifically correct (match hand calculations)
5. ✓ Quality gate blocks on data quality issues (Scenario 5)
6. ✓ PII detection works on realistic data (Scenario 6)
7. ✓ Audit log records all workflow steps
8. ✓ Performance is acceptable (<90 seconds per scenario)

**Success Probability**:
- If all 6 criteria met: MVP validated ✓
- If 5-6 criteria met: MVP mostly validated, minor fixes needed
- If <5 criteria met: MVP not validated, significant work required

---

## Notes

- Use `test_data/health_screening_japan.csv` for all scenarios (no data preprocessing)
- Do not modify the test dataset
- Record screenshots/logs for each scenario for documentation
- If error occurs, capture full error message and stack trace
- Performance measurements should use wall-clock time (not CPU time)
- Scenarios 1-4 test functional correctness; Scenarios 5-6 test safety and governance
