"""CIE Platform — UI package.

Presentation layer responsibilities (spec/system.yaml ``layers.presentation``):
    - User interface rendering
    - User interaction handling
    - Authentication
    - Progress reporting

Dependency direction: UI → Workflow → Agents → Runtime
UI must NEVER depend directly on Runtime (PROJECT_RULES.md Section 5).
"""
