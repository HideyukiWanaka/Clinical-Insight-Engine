# Manuscript Structure Guide
# Domain: reporting
# Version: 1.0.0
# Status: Stable
# Consumers: reporting, reviewer
# Immutable during execution (AP-014)

## Purpose

Provides the Reporting Agent with the standard structure, content requirements,
and section-by-section generation rules for clinical research manuscripts.
Ensures outputs conform to international journal standards.

---

## Standard Manuscript Structure

### Section Order

1. Title
2. Abstract (Structured)
3. Introduction
4. Methods
5. Results
6. Discussion
7. Conclusions
8. Acknowledgements *(human-authored — unresolved_item)*
9. Conflicts of Interest *(human-authored — unresolved_item)*
10. Funding *(human-authored — unresolved_item)*
11. References *(placeholder — human-completed)*
12. Tables
13. Figures

---

## Section Generation Rules

### Title
**Agent generates:** One candidate title.
**Format:** Descriptive, includes study design and population.
**Example structure:** `"[Outcome] in [Population]: A [Study Design] Study"`
**Unresolved item:** Final title selection requires human approval.

---

### Abstract (Structured)
**Required subsections:**

| Subsection | Content | Source |
|-----------|---------|--------|
| Background | 1–2 sentences on clinical problem | intent_object.natural_language_summary |
| Objective | 1 sentence stating the research objective | intent_object |
| Methods | Study design, population, key variables, statistical approach | analysis_plan |
| Results | Primary outcome result with effect size, CI, and p-value | execution_result |
| Conclusions | 1–2 sentences; no new information | Results section |

**Word limit:** 250–300 words (check target journal guidelines).
**Agent rule:** Abstract Results must numerically match the Results section exactly.

---

### Introduction
**Structure:**
1. Clinical problem statement (2–3 sentences)
2. Current evidence gap (2–3 sentences)
3. Study objective statement (1 sentence)

**Agent generates:** Paragraphs 1 and 3 from intent_object.
**Unresolved item:** Evidence gap paragraph requires human literature knowledge.

---

### Methods
**Required subsections (auto-generated):**

| Subsection | Source artifact |
|-----------|----------------|
| Study design and setting | intent_object.study_design |
| Participants / Inclusion-exclusion criteria | dataset_structural_metadata + unresolved_item |
| Variables | var_n alias descriptions from intent_object |
| Statistical analysis | analysis_plan.selected_methods |
| Missing data handling | analysis_plan.missing_data_handling |
| Software | R version + package versions from execution_result |
| Ethical approval | unresolved_item |

**Statistical analysis subsection template:**
```
"All statistical analyses were performed using R version [X.X.X]
([packages and versions from execution_result]).
[Describe primary method with justification].
[Describe assumption checks performed].
[Describe multiple comparison correction if applicable].
Effect sizes are reported as [measure] with 95% confidence intervals.
A two-tailed p-value < 0.05 was considered statistically significant.
Missing data were handled by [strategy from analysis_plan]."
```

---

### Results
**Structure:**
1. Participant flow / Sample description
2. Baseline characteristics table (Table 1)
3. Primary outcome result
4. Secondary outcome results
5. Subgroup or sensitivity analyses (if applicable)

**Generation rules:**
- Every numeric value must be sourced from execution_result (rule RP-001).
- Use result_interpretation_guide.md templates R-001 through R-004.
- Table 1 specification must be included in `table_specifications`.
- Each result paragraph ends with: `(Figure X)` or `(Table X)` reference.

---

### Discussion
**Structure:**
1. Summary of principal findings (1 paragraph — agent-generated from Results)
2. Comparison with existing literature — **unresolved_item**
3. Strengths (1 paragraph — agent can draft from study design)
4. Limitations (1 paragraph — agent flags known limitations; human completes)
5. Clinical implications — **unresolved_item**

**Known limitations to auto-flag:**
- Cross-sectional design: cannot establish causality
- Retrospective data: selection and information bias possible
- Single-centre study: generalizability limited
- Missing data ≥ 5%: imputation assumptions may affect results

---

### Conclusions
**Agent generates:** 2–3 sentences summarising the primary finding and its implication.
**Rule:** Must not introduce new information not in Results or Discussion.
**Must not use:** "proves", "confirms causation", "demonstrates that X causes Y"

---

## Table Specification Standard

Every table must include:

```yaml
table_id: "T1"
title: "Baseline characteristics of study participants"
columns:
  - label: "Characteristic"
  - label: "Group A (n=XX)"
  - label: "Group B (n=XX)"
  - label: "p-value"
footnotes:
  - "Data are presented as mean ± SD or n (%) unless otherwise stated."
  - "P-values from [test name] for continuous variables and chi-square test for categorical variables."
source_artifact: "execution_result"
```

---

## Word Count Targets by Section

| Section | Target words |
|---------|-------------|
| Abstract | 250–300 |
| Introduction | 300–500 |
| Methods | 400–700 |
| Results | 400–700 |
| Discussion | 600–1000 |
| Conclusions | 100–150 |
| **Total** | **2050–3350** |

Actual word count must be reported in `word_count_estimate` output field.
