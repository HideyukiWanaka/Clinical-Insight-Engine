"""CIE Platform — Workflow package.

Workflows are declarative first-class objects (PROJECT_RULES.md Section 10).
Agents execute workflows; agents never modify workflow definitions.

Registered workflows (spec/system.yaml):
    - clinical_analysis_standard
    - clinical_analysis_survival
    - clinical_analysis_meta
    - clinical_analysis_prediction

ADR-0001: Orchestrator selects workflow_id via deterministic rules.
          Planner Agent produces intent_object only.
          DAG nodes are immutable at runtime.
"""
