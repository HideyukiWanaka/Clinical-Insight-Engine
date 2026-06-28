"""CIE Platform — Security package.

Implements the Security-by-Design principle (PROJECT_RULES.md Section 8).
Default policy: Deny first; allow explicitly.

Responsibilities:
    - Policy engine integration
    - PII detection pipeline (Layer 1: regex, Layer 2: statistical, Layer 3: ML)
    - Permission enforcement
    - Audit logging

All internet access is denied by default.
Human approval is required for: export, external_api, package_install,
skill_update, user_skill_registration.
"""
