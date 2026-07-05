"""CIE Platform — Format context builder (Phase 5).

Pure-Python helper with no Streamlit dependency, so it is directly importable
from unit tests.  ``app.py`` delegates to this module; tests import it too.
"""

from __future__ import annotations


def build_format_context(
    checklist_id: str | None = None,
    journal_style: str = "APA",
    skill_id: str | None = None,
) -> dict:
    """Build the reporting-format portion of the workflow's initial context.

    Args:
        checklist_id:  Explicit reporting checklist (CONSORT/STROBE/TRIPOD/PRISMA/STARD)
                       or None to let ReportingAgent infer from study_design.
        journal_style: p-value format style ("APA" / "AMA" / "Vancouver").
                       Defaults to "APA" when None or empty.
        skill_id:      User-defined reporting Skill ID from skills/user/, or None
                       to use the core "reporting/manuscript-section" skill.

    Returns:
        Dict to be merged into ``dataset_context`` before ``run_workflow``:
          target_journal_style   — always present
          reporting_checklist_id — present only when explicitly chosen
          reporting_skill_id     — present only when a user Skill is selected
    """
    ctx: dict = {"target_journal_style": journal_style or "APA"}
    if checklist_id:
        ctx["reporting_checklist_id"] = checklist_id
    if skill_id:
        ctx["reporting_skill_id"] = skill_id
    return ctx
