"""CIE Platform — Meta-Skill Python implementations (ADR-0002).

These modules are the executable counterparts of the ``skills/meta/*/SKILL.md``
specifications. They are pure, read-only analysis components — they never write
Skill files. The actual (human-approved) file mutation lives in
``cie.skills.lifecycle.SkillLifecycleService``.

  - SkillEvaluator (meta/skill-evaluator): analyses reviewer findings and skill
    performance records to detect degradation and localise the root cause in the
    target SKILL.md.
  - SkillProposer (meta/skill-proposer): turns a SkillEvaluationReport into a set
    of concrete, diff-carrying proposed changes plus a version-bump assessment.
"""

from __future__ import annotations

from cie.skills.meta.evaluator import (
    RootCauseAnalysis,
    SkillEvaluationReport,
    SkillEvaluator,
    TriggerResult,
)
from cie.skills.meta.proposer import (
    ImpactAssessment,
    ProposedChange,
    SkillProposer,
)

__all__ = [
    "SkillEvaluator",
    "TriggerResult",
    "RootCauseAnalysis",
    "SkillEvaluationReport",
    "SkillProposer",
    "ProposedChange",
    "ImpactAssessment",
]
