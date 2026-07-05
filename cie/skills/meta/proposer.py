"""CIE Platform — SkillProposer (Python impl of meta/skill-proposer).

Turns a SkillEvaluationReport into a set of concrete, diff-carrying proposed
changes plus a SemVer bump assessment.

CRITICAL (ADR-0002 Principle 4): this component generates *proposals only*. It
never writes a Skill file. The actual (human-approved) mutation is performed by
``cie.skills.lifecycle.SkillLifecycleService.apply_approved_proposal``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from cie.skills.meta.evaluator import RootCauseAnalysis, SkillEvaluationReport


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Change strategies: check_id → (section, change_type, diff template)
# ---------------------------------------------------------------------------
# A non-None ``diff`` is an executable/insertable block that
# apply_approved_proposal can splice into the named section. A None diff means
# "advisory only — a human must author the fix".

_CC006_CI_DIRECTION_CHECK = """\
- **[auto/CC-006] CI direction must be consistent with significance (executable):**
```r
# Addresses recurring reviewer finding CC-006: when a result is significant,
# its confidence interval must exclude the null value.
if (result$primary_result$p_value < 0.05) {
  ci_excludes_null <- result$primary_result$ci_lower > 0 ||
                      result$primary_result$ci_upper < 0
  if (!ci_excludes_null) {
    stop(paste(
      "CI_DIRECTION_INCONSISTENT: p =",
      round(result$primary_result$p_value, 4),
      "but CI [",
      round(result$primary_result$ci_lower, 3), ",",
      round(result$primary_result$ci_upper, 3), "] includes the null value."
    ))
  }
}
```"""

_CC001_PVALUE_TRACE = """\
- **[auto/CC-001] p-value traceability:** every p-value written to the manuscript
  must be copied verbatim from `statistical_results.p_value` (tagged
  `[TRACE: statistical_results.p_value]`). Never round or restate a p-value that
  is not present in the executed result.json."""

_CC002_EFFECT_TRACE = """\
- **[auto/CC-002] effect-size traceability:** the reported effect size and its
  measure must equal `statistical_results.effect_size` /
  `statistical_results.effect_size_measure`; do not substitute a different
  measure than the one produced by the executed R."""

_CC003_SAMPLE_SIZE = """\
- **[auto/CC-003] sample-size consistency:** the N reported in text must equal
  `statistical_results.sample_size` (and the sum of `group_summaries` n)."""

CHANGE_STRATEGIES: dict[str, tuple[str, str, str | None]] = {
    "CC-006": ("Validation Rules", "add", _CC006_CI_DIRECTION_CHECK),
    "CC-001": ("Validation Rules", "add", _CC001_PVALUE_TRACE),
    "CC-002": ("Validation Rules", "add", _CC002_EFFECT_TRACE),
    "CC-003": ("Validation Rules", "add", _CC003_SAMPLE_SIZE),
}

# Sections whose modification implies an interface/contract change → MAJOR bump.
_INTERFACE_SECTIONS = frozenset(
    {"Component Contract", "input_schema", "output_schema", "Interface"}
)


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass
class ProposedChange:
    change_id: str
    finding_id: str
    section: str
    change_type: str  # "add" | "modify" | "remove" | "advisory"
    description: str
    diff: str | None
    addresses_finding: str

    def to_dict(self) -> dict:
        return {
            "change_id": self.change_id,
            "finding_id": self.finding_id,
            "trigger_id": self.finding_id,
            "section": self.section,
            "change_type": self.change_type,
            "description": self.description,
            "diff": self.diff,
            "addresses_finding": self.addresses_finding,
        }


@dataclass
class ImpactAssessment:
    breaking_change: bool
    regression_risk: str  # "high" | "medium" | "low"
    proposed_version: str
    version_bump_type: str  # "MAJOR" | "MINOR" | "PATCH"
    test_coverage_delta: str
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "breaking_change": self.breaking_change,
            "regression_risk": self.regression_risk,
            "proposed_version": self.proposed_version,
            "version_bump_type": self.version_bump_type,
            "test_coverage_delta": self.test_coverage_delta,
            **self.extra,
        }


def bump_version(version: str, bump: str) -> str:
    """Increment a SemVer string; returns the input unchanged if unparseable."""
    parts = version.split(".")
    try:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        return version
    if bump == "MAJOR":
        return f"{major + 1}.0.0"
    if bump == "MINOR":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# ---------------------------------------------------------------------------
# SkillProposer
# ---------------------------------------------------------------------------


class SkillProposer:
    """Generates concrete proposed changes from a SkillEvaluationReport.

    Pure — no file writes, no DB access. Persistence and human-approved
    application are the SkillLifecycleService's job.
    """

    def map_findings_to_changes(self, root_cause: RootCauseAnalysis) -> list[ProposedChange]:
        """Produce one ProposedChange per implicated finding.

        Known check_ids get a concrete diff from CHANGE_STRATEGIES; unknown
        ones become advisory-only (diff=None), forcing human authorship.
        """
        changes: list[ProposedChange] = []
        for finding in root_cause.affected_sections:
            cid = finding["finding_id"]
            if cid in CHANGE_STRATEGIES:
                section, change_type, template = CHANGE_STRATEGIES[cid]
                changes.append(
                    ProposedChange(
                        change_id=f"CHG-{_short_id()}",
                        finding_id=cid,
                        section=section,
                        change_type=change_type,
                        description=f"Address {cid} in section '{section}'.",
                        diff=template,
                        addresses_finding=cid,
                    )
                )
            else:
                changes.append(
                    ProposedChange(
                        change_id=f"CHG-{_short_id()}",
                        finding_id=cid,
                        section=finding.get("affected_section", "Unknown"),
                        change_type="advisory",
                        description=f"Manual review required for {cid}.",
                        diff=None,
                        addresses_finding=cid,
                    )
                )
        return changes

    def assess_impact(
        self,
        proposed_changes: list[ProposedChange],
        current_version: str,
    ) -> ImpactAssessment:
        """Determine the SemVer bump and regression risk for the change set."""
        has_interface_change = any(
            c.section in _INTERFACE_SECTIONS for c in proposed_changes
        )
        has_remove = any(c.change_type == "remove" for c in proposed_changes)
        has_add = any(c.change_type == "add" for c in proposed_changes)

        if has_interface_change or has_remove:
            version_bump = "MAJOR"
        elif has_add:
            version_bump = "MINOR"
        else:
            version_bump = "PATCH"

        proposed_version = bump_version(current_version, version_bump)
        test_added = sum(1 for c in proposed_changes if c.section == "Tests")
        return ImpactAssessment(
            breaking_change=has_interface_change or has_remove,
            regression_risk=(
                "high"
                if version_bump == "MAJOR"
                else "medium"
                if version_bump == "MINOR"
                else "low"
            ),
            proposed_version=proposed_version,
            version_bump_type=version_bump,
            test_coverage_delta=f"+{test_added} test(s)",
        )

    def build_proposal_changes(
        self,
        evaluation_report: SkillEvaluationReport,
        current_version: str | None = None,
    ) -> tuple[list[dict], ImpactAssessment]:
        """Return (proposed_changes as dicts, impact) for a lifecycle proposal.

        ``human_review_required`` is not represented here — the lifecycle layer
        stamps it True unconditionally. This method only shapes the diff content.
        """
        version = current_version or evaluation_report.current_version
        changes = self.map_findings_to_changes(evaluation_report.root_cause)
        # A no-op root cause (nothing implicated) still yields at least one
        # advisory change so the human sees *something* actionable.
        if not changes:
            changes = [
                ProposedChange(
                    change_id=f"CHG-{_short_id()}",
                    finding_id=evaluation_report.trigger.trigger_id,
                    section="Procedure",
                    change_type="advisory",
                    description=(
                        f"Investigate trigger {evaluation_report.trigger.trigger_id}: "
                        f"{evaluation_report.trigger.description}"
                    ),
                    diff=None,
                    addresses_finding=evaluation_report.trigger.trigger_id,
                )
            ]
        impact = self.assess_impact(changes, version)
        return [c.to_dict() for c in changes], impact
