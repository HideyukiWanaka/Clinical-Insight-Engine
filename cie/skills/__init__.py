"""CIE Platform — Skills package.

Skills contain domain knowledge, best practices, procedures, examples,
and validation logic (PROJECT_RULES.md Section 11).

ADR-0002 — Three-namespace structure:
    - ``core/``   Official CIE Skills. Immutable without Human Authority approval.
    - ``meta/``   Meta-Skills for skill evaluation, improvement, and scaffolding.
    - ``user/``   User-defined Skills. Registered via REGISTRY.yaml.

Loading priority: user/ > core/ (meta/ cannot be overridden).
"""
