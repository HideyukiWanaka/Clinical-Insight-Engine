# Reporting Checklists
# Domain: reporting
# Version: 2.0.0
# Status: Stable
# Consumers: reporting, reviewer
# Immutable during execution (AP-014)
#
# Sources (official):
#   CONSORT 2010 — PMC2844940 (Schulz et al., BMJ 2010;340:c332)
#   STROBE 2007  — strobe-statement.org / Lancet 2007;370:1453-57
#   TRIPOD+AI    — PMC11019967 (Collins et al., BMJ 2024) — supersedes TRIPOD 2015
#   PRISMA 2020  — PMC8005924 (Page et al., BMJ 2021;372:n71)
#
# CRITICAL VERSION NOTE:
#   TRIPOD 2015 has been superseded by TRIPOD+AI (2024, 27 items).
#   The original TRIPOD 2015 checklist should NO LONGER be used.
#   Reference: "The new checklist supersedes the TRIPOD 2015 checklist,
#   which should no longer be used." (Collins et al., BMJ 2024)

## Purpose

Provides the Reporting Agent with mandatory item lists for each reporting
standard, sourced directly from official publications. Enables the Reviewer
Agent to verify checklist completeness with item-level accuracy.
Each item is marked as auto-completable by the agent or requiring human input.

---

## CONSORT 2010 — Randomized Controlled Trials
## 25 items total | Source: Schulz et al. BMJ 2010;340:c332 (PMC2844940)

**Apply when:** `intent_object.study_design = randomized_controlled_trial`

### Title and Abstract
| Item | Official description (verbatim) | Auto-completable |
|------|--------------------------------|-----------------|
| 1a | Identification as a randomised trial in the title | Partial |
| 1b | Structured summary of trial design, methods, results, and conclusions | Yes |

### Introduction
| Item | Official description (verbatim) | Auto-completable |
|------|--------------------------------|-----------------|
| 2a | Scientific background and explanation of rationale | Partial |
| 2b | Specific objectives or hypotheses | Yes |

### Methods
| Item | Official description (verbatim) | Auto-completable |
|------|--------------------------------|-----------------|
| 3a | Description of trial design (such as parallel, factorial) including allocation ratio | Partial |
| 3b | Important changes to methods after trial commencement (such as eligibility criteria), with reasons | No — human |
| 4a | Eligibility criteria for participants | No — human |
| 4b | Settings and locations where the data were collected | No — human |
| 5 | The interventions for each group with sufficient details to allow replication, including how and when they were actually administered | No — human |
| 6a | Completely defined pre-specified primary and secondary outcome measures, including how and when they were assessed | Yes |
| 6b | Any changes to trial outcomes after the trial commenced, with reasons | No — human |
| 7a | How sample size was determined | Partial |
| 7b | When applicable, explanation of any interim analyses and stopping guidelines | No — human |
| 8a | Method used to generate the random allocation sequence | No — human |
| 8b | Type of randomisation; details of any restriction (such as blocking and block size) | No — human |
| 9 | Mechanism used to implement the random allocation sequence (such as sequentially numbered containers), describing any steps taken to conceal the sequence until interventions were assigned | No — human |
| 10 | Who generated the random allocation sequence, who enrolled participants, and who assigned participants to interventions | No — human |
| 11a | If done, who was blinded after assignment to interventions (for example, participants, care providers, those assessing outcomes) and how | No — human |
| 11b | If relevant, description of the similarity of interventions | No — human |
| 12a | Statistical methods used to compare groups for primary and secondary outcomes | Yes |
| 12b | Methods for additional analyses, such as subgroup analyses and adjusted analyses | Yes |

### Results
| Item | Official description (verbatim) | Auto-completable |
|------|--------------------------------|-----------------|
| 13a | For each group, the numbers of participants who were randomly assigned, received intended treatment, and were analysed for the primary outcome | Partial |
| 13b | For each group, losses and exclusions after randomisation, together with reasons | No — human |
| 14a | Dates defining the periods of recruitment and follow-up | No — human |
| 14b | Why the trial ended or was stopped | No — human |
| 15 | A table showing baseline demographic and clinical characteristics for each group | Yes |
| 16 | For each group, number of participants (denominator) included in each analysis and whether the analysis was by original assigned groups | Yes |
| 17a | For each primary and secondary outcome, results for each group, and the estimated effect size and its precision (such as 95% confidence interval) | Yes |
| 17b | For binary outcomes, presentation of both absolute and relative effect sizes is recommended | Yes |
| 18 | Results of any other analyses performed, including subgroup analyses and adjusted analyses, distinguishing pre-specified from exploratory | Yes |
| 19 | All important harms or unintended effects in each group | No — human |

### Discussion
| Item | Official description (verbatim) | Auto-completable |
|------|--------------------------------|-----------------|
| 20 | Trial limitations, addressing sources of potential bias, imprecision, and, if relevant, multiplicity of analyses | Partial |
| 21 | Generalisability (external validity) of the trial findings | No — human |
| 22 | Interpretation consistent with results, balancing benefits and harms, and considering other relevant evidence | Yes |

### Other Information
| Item | Official description (verbatim) | Auto-completable |
|------|--------------------------------|-----------------|
| 23 | Registration number and name of trial registry | No — human |
| 24 | Where the full trial protocol can be accessed, if available | No — human |
| 25 | Sources of funding and other support (such as supply of drugs); role of funders | No — human |

---

## STROBE 2007 — Observational Studies
## 22 items total | Source: von Elm et al. Lancet 2007;370:1453-57 / Epidemiology 2007;18:800-4

**Apply when:** `intent_object.study_design` ∈ {cohort, case_control, cross_sectional, observational}

**Note on design-specific items:** Items 6, 12, 14, and 15 have design-specific variants.
Items marked with * require information given separately for cases/controls (case-control)
or exposed/unexposed (cohort and cross-sectional).

### Title and Abstract
| Item | Official description | Cohort | Case-Control | Cross-Sectional | Auto-completable |
|------|---------------------|--------|-------------|-----------------|-----------------|
| 1 | (a) Indicate study design in title or abstract; (b) provide informative summary of what was done and found | ✓ | ✓ | ✓ | Partial |

### Introduction
| Item | Official description | Auto-completable |
|------|---------------------|-----------------|
| 2 | Explain scientific background and rationale for the investigation | Partial |
| 3 | State specific objectives, including any prespecified hypotheses | Yes |

### Methods
| Item | Official description | Notes | Auto-completable |
|------|---------------------|-------|-----------------|
| 4 | Present key elements of study design early in the paper | | Yes |
| 5 | Describe setting, locations, and relevant dates including periods of recruitment, exposure, follow-up, and data collection | | No — human |
| 6 | **Design-specific** — Eligibility criteria, sources and methods of selection | Cohort: eligible subjects and methods of follow-up. Case-control: cases and controls, sources, selection rationale. Cross-sectional: eligible subjects and methods | No — human |
| 7 | Clearly define all outcomes, exposures, predictors, potential confounders, and effect modifiers; give diagnostic criteria | | No — human |
| 8* | For each variable of interest, give sources of data and details of methods of assessment | | No — human |
| 9 | Describe any efforts to address potential sources of bias | | No — human |
| 10 | Explain how the study size was arrived at | | Partial |
| 11 | Explain how quantitative variables were handled in the analyses | | Yes |
| 12 | **Design-specific** — Statistical methods, including methods for confounding control; methods for subgroup analyses; how missing data were addressed; design-specific methods (e.g. matching) | Cohort: add loss to follow-up handling. Case-control: add matching. Cross-sectional: add sampling strategy | Yes |

### Results
| Item | Official description | Notes | Auto-completable |
|------|---------------------|-------|-----------------|
| 13 | Report numbers of individuals at each stage of study; give reasons for non-participation | | Partial |
| 14 | **Design-specific** — Characteristics of study participants, information on exposure and potential confounders | Cohort & cross-sectional: give characteristics of exposed and unexposed. Case-control: give characteristics of cases and controls | Yes |
| 15 | **Design-specific** — Number of outcome events or summary measures | Cohort: report numbers of outcome events or summary measures over time. Case-control: report numbers in each exposure category. Cross-sectional: report numbers of outcome events or summary measures | Yes |
| 16 | (a) Give unadjusted estimates and, if applicable, confounder-adjusted estimates with precision (CI); (b) report category boundaries when continuous variables were categorized; (c) if relevant, consider translating estimates of relative risk into absolute risk for a meaningful time period | | Yes |
| 17 | Report other analyses done—e.g. subgroup analyses, interaction analyses, sensitivity analyses | | Yes (if performed) |

### Discussion
| Item | Official description | Auto-completable |
|------|---------------------|-----------------|
| 18 | Summarise key results with reference to study objectives | Yes |
| 19 | Discuss limitations of the study, taking into account sources of potential bias or imprecision; discuss both direction and magnitude of any potential bias | Partial |
| 20 | Give a cautious overall interpretation of results considering objectives, limitations, multiplicity of analyses, results from similar studies, and other relevant evidence | Partial |
| 21 | Discuss the generalisability (external validity) of the study results | No — human |

### Other Information
| Item | Official description | Auto-completable |
|------|---------------------|-----------------|
| 22 | Give the source of funding and the role of the funders for the present study and, if applicable, for the original study on which the present article is based | No — human |

---

## TRIPOD+AI 2024 — Prediction Models (Development or Validation)
## 27 items total | Source: Collins et al. BMJ 2024 (PMC11019967)
## ⚠️ SUPERSEDES TRIPOD 2015 — Do NOT use the old 22-item checklist

**Apply when:** `intent_object.study_design = prediction_model`

**Note:** Items marked D apply to development studies only; V to validation only;
D+V to both. All other items apply to all prediction model studies.

### Title and Abstract
| Item | Applies | Official description | Auto-completable |
|------|---------|---------------------|-----------------|
| 1 | D+V | Identify the study as developing and/or validating a multivariable prediction model, the target population, and the outcome to be predicted | Partial |
| 2 | D+V | Provide a structured abstract including study design, methods, results, and conclusions | Yes |

### Introduction
| Item | Applies | Official description | Auto-completable |
|------|---------|---------------------|-----------------|
| 3a | D+V | Explain the medical context (including whether diagnostic or prognostic) and rationale for developing or validating the multivariable prediction model | Partial |
| 3b | D+V | Specify the objectives, including whether the study describes the development or validation of the model or both | Yes |

### Methods
| Item | Applies | Official description | Auto-completable |
|------|---------|---------------------|-----------------|
| 4a | D+V | Describe the study design or source of data (e.g. randomised trial, cohort, or registry data) separately for the development and validation data sets | Yes |
| 4b | V | Specify the key dates for the validation data set | No — human |
| 5a | D+V | Describe the key elements of the setting including number and location of centres | No — human |
| 5b | D+V | Describe the eligibility criteria for participants | No — human |
| 6 | D+V | Clearly define the outcome that is predicted by the prediction model, including how and when assessed | Yes |
| 7a | D+V | Clearly define all predictors used in developing or validating the prediction model, including how and when they were measured | Yes |
| 7b | D | Report the number of participants and outcome events in the development and any validation datasets | Yes |
| 8 | D+V | Describe how missing data were handled | Yes |
| 9 | D | If done, describe how the development data were used for internal validation (e.g. random or non-random splits, bootstrap, cross-validation) | Partial |
| 10a | D | Describe how predictors were handled in the analyses | Yes |
| 10b | D | Specify type of model, all model-building procedures (including any predictor selection), and method for internal validation | Yes |
| 10c | V | Describe the method for validation of the model performance | Partial |
| 10d | D | Specify all measures used to assess model performance and, if relevant, to compare multiple models | Yes |
| 10e | V | Describe any model updating arising from the validation, if done | No — human |
| 11 | D+V | Describe any model updating (e.g. recalibration) arising from the validation, if done | No — human |

### Results
| Item | Applies | Official description | Auto-completable |
|------|---------|---------------------|-----------------|
| 12 | D+V | Report the flow of participants through the study, including the number with and without the outcome and, if applicable, a summary of the follow-up time | Partial |
| 13a | D+V | Describe the characteristics of the participants (basic demographics, clinical features, available predictors), including the number of participants with missing data for predictors and outcome | Yes |
| 13b | V | For validation, show a comparison with the development data of the distribution of important variables (demographics, predictors, and outcome) | Yes |
| 14 | D | Specify the number of participants and outcome events in each analysis | Yes |
| 15a | D | Present the full prediction model to allow predictions for individuals (i.e. all regression coefficients, and model intercept or baseline survival at a given time point) | Yes |
| 15b | D+V | Report performance measures (with CIs) for the prediction model | Yes |
| 16 | D+V | Report results from any model updating (e.g. recalibration) | No — human |

### Discussion
| Item | Applies | Official description | Auto-completable |
|------|---------|---------------------|-----------------|
| 17 | D+V | Summarise the results of the study, including key performance measures, and their implications for clinical use | Partial |
| 18 | D+V | Discuss any limitations of the study (such as non-representative sample, few events per predictor, missing data) | Partial |
| 19a | D | For models with discrimination measures, interpret these in context | Yes |
| 19b | D+V | Discuss the implications for clinical use of the model, including any potential impact on patient outcomes and clinical decision making | No — human |

### Other Information
| Item | Applies | Official description | Auto-completable |
|------|---------|---------------------|-----------------|
| 20 | D+V | Provide information about the availability of supplementary resources, such as study protocol, Web calculator, and data sets | No — human |
| 21 | D+V | Give the source of funding and the role of the funders for the present study | No — human |

---

## PRISMA 2020 — Systematic Reviews and Meta-Analyses
## 27 items total | Source: Page et al. BMJ 2021;372:n71 (PMC8005924)
## Supersedes PRISMA 2009

**Apply when:** `intent_object.study_design = systematic_review_or_meta_analysis`

### Title
| Item | Official description | Auto-completable |
|------|---------------------|-----------------|
| 1 | Identify the report as a systematic review | Partial |

### Abstract
| Item | Official description | Auto-completable |
|------|---------------------|-----------------|
| 2 | See the PRISMA 2020 for Abstracts checklist | Yes |

### Introduction
| Item | Official description | Auto-completable |
|------|---------------------|-----------------|
| 3 | Describe the rationale for the review in the context of existing knowledge | Partial |
| 4 | Provide an explicit statement of the objective(s) or question(s) the review addresses | Yes |

### Methods
| Item | Official description | Auto-completable |
|------|---------------------|-----------------|
| 5 | Specify the inclusion and exclusion criteria for the review and how studies were grouped for the syntheses | No — human |
| 6 | Specify all databases, registers, websites, organisations, reference lists, and other sources searched or consulted to identify studies | No — human |
| 7 | Present the full search strategies for all databases, registers, and websites, including any filters and limits used | No — human |
| 8 | Describe the methods used to decide whether a study met the inclusion criteria of the review, including how many reviewers screened each record and each report retrieved, and whether they worked independently | No — human |
| 9 | Describe the methods used to collect data from reports, including how many reviewers collected data from each report, whether they worked independently, any processes for obtaining or confirming data from study investigators | No — human |
| 10a | List and define all outcomes for which data were sought; specify whether all results that were compatible with each outcome domain in each eligible study were sought | No — human |
| 10b | List and define all other variables for which data were sought (e.g. participant and intervention characteristics, funding sources) | No — human |
| 11 | Describe the methods used to assess risk of bias in the included studies, including details of the tool(s) used, how many reviewers assessed each study, and whether they worked independently | No — human |
| 12 | Specify for each outcome the effect measure(s) (e.g. risk ratio, mean difference) used in the synthesis or presentation of results | Yes |
| 13a | Describe the processes used to decide which studies were eligible for each synthesis (e.g. tabulating the study intervention characteristics and comparing against the planned groups for each synthesis) | No — human |
| 13b | Describe any methods required to prepare the data for presentation or synthesis, such as handling of missing summary statistics, or data conversions | Yes |
| 13c | Describe any methods used to tabulate or visually display results of individual studies and syntheses | Yes |
| 13d | Describe any methods used to synthesize results and provide a rationale for the choice(s); if meta-analysis was performed, describe the model(s), method(s) to identify the presence and extent of statistical heterogeneity, and software package(s) used | Yes |
| 13e | Describe any methods used to explore possible causes of heterogeneity among study results (e.g. subgroup analysis, meta-regression) | Yes (if performed) |
| 13f | Describe any sensitivity analyses conducted to assess robustness of the synthesized results | Yes (if performed) |
| 14 | Describe any methods used to assess risk of bias due to missing results in a synthesis (arising from reporting biases) | Partial |
| 15 | Describe any methods used to assess certainty (or confidence) in the body of evidence for an outcome | No — human |

### Results
| Item | Official description | Auto-completable |
|------|---------------------|-----------------|
| 16a | Describe the results of the search and selection process, from the number of records identified in the search to the number of studies included in the review, ideally using a flow diagram | Partial |
| 16b | Cite studies that might appear to meet the inclusion criteria, but which were excluded, and explain why they were excluded | No — human |
| 17 | Cite each included study and present its characteristics | Yes |
| 18 | Present assessments of risk of bias for each included study | No — human |
| 19 | For all outcomes, present, for each study: (a) summary statistics for each group (where appropriate) and (b) an effect estimate and its precision (e.g. confidence/credible interval), ideally using structured tables or plots | Yes |
| 20a | For each synthesis, briefly summarise the characteristics and risk of bias among contributing studies | Partial |
| 20b | Present results of all statistical syntheses conducted; if meta-analysis was done, present for each the summary estimate and its precision, and measures of statistical heterogeneity; if comparing groups, describe the direction of the effect | Yes |
| 20c | Present results of all investigations of possible causes of heterogeneity among study results | Yes (if performed) |
| 20d | Present results of all sensitivity analyses conducted to assess the robustness of the synthesized results | Yes (if performed) |
| 21 | Present assessments of risk of bias due to missing results (arising from reporting biases) for each synthesis assessed | Partial |
| 22 | Present assessments of certainty (or confidence) in the body of evidence for each outcome assessed | No — human |

### Discussion
| Item | Official description | Auto-completable |
|------|---------------------|-----------------|
| 23 | Provide a general interpretation of the results in the context of other evidence | Partial |
| 24 | Discuss any limitations of the evidence included in the review | Partial |
| 25 | Discuss any limitations of the review processes used | Partial |
| 26 | Provide an overall interpretation of the results and implications for practice, policy, and future research | No — human |

### Other Information
| Item | Official description | Auto-completable |
|------|---------------------|-----------------|
| 27 | Provide information about the following, if applicable: (a) registrations or protocols; (b) related reviews; (c) how to access data and materials; (d) funding and conflicts of interest | No — human |

---

## Checklist Compliance Output Format

For each checklist item, the Reporting Agent must produce:

```yaml
checklist_id: "CONSORT"       # CONSORT | STROBE | TRIPOD+AI | PRISMA
checklist_version: "2010"     # 2010 | 2007 | 2024 | 2020
item_id: "12a"
official_description: "Statistical methods used to compare groups for primary and secondary outcomes"
status: "complete"            # complete | incomplete | not_applicable | human_required
auto_completed: true
content_reference: "manuscript_sections[methods][statistical_analysis]"
```

Items with `status: human_required` must appear in `unresolved_items`.
The Reviewer Agent verifies that no mandatory item has `status: incomplete`.

---

## Version History

| Checklist | Version in this file | Key changes from previous |
|-----------|---------------------|--------------------------|
| CONSORT | 2010 (25 items) | Current. Supersedes 2001 version. |
| STROBE | 2007 (22 items) | Current. No major updates since 2007. |
| TRIPOD+AI | 2024 (27 items) | **Supersedes TRIPOD 2015 (22 items).** New items for ML/AI methods. |
| PRISMA | 2020 (27 items) | Supersedes PRISMA 2009. New items for synthesis methods and risk of bias. |
