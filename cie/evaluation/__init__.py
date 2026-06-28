"""CIE Platform — Evaluation package.

Every generated artifact is evaluated before it is accepted
(PROJECT_RULES.md Section 3.6).  Generated outputs are never trusted
by default.

Mandatory evaluation dimensions (spec/system.yaml):
    - correctness
    - schema_validation
    - statistical_validity
    - security
    - reproducibility
    - workflow_integrity

ADR-0002: skill_performance_monitoring is enabled via feature flag.
"""
