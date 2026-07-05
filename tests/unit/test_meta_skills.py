"""Unit tests for the Phase 8 meta-skill layer (ADR-0002).

Covers the pure (no-DB, no-file-write) analysis components:
  - SkillEvaluator: trigger detection + root-cause localisation
  - SkillProposer: concrete diff generation + version-bump assessment
  - _apply_changes_to_content: deterministic diff splicing into SKILL.md
"""

from __future__ import annotations

from cie.skills.lifecycle import _apply_changes_to_content
from cie.skills.meta.evaluator import (
    FINDING_TO_SECTION,
    SkillEvaluator,
    TriggerResult,
)
from cie.skills.meta.proposer import CHANGE_STRATEGIES, SkillProposer


# ---------------------------------------------------------------------------
# SkillEvaluator — trigger detection
# ---------------------------------------------------------------------------


def test_se001_detects_recurring_check_id() -> None:
    """CC-006 in 3 of the last 5 records → SE-001 fires with evidence."""
    evaluator = SkillEvaluator()
    records = [{"check_ids": ["CC-006"]} for _ in range(3)]
    records += [{"check_ids": []} for _ in range(2)]
    result = evaluator.evaluate_triggers(records, "SE-001")
    assert result.triggered is True
    assert result.evidence.get("CC-006") == 3


def test_se001_does_not_fire_below_threshold() -> None:
    """Only 2 occurrences → below the 3/5 threshold → no trigger."""
    evaluator = SkillEvaluator()
    records = [{"check_ids": ["CC-006"]} for _ in range(2)]
    records += [{"check_ids": []} for _ in range(3)]
    result = evaluator.evaluate_triggers(records, "SE-001")
    assert result.triggered is False
    assert result.evidence == {}


def test_se001_reads_skillperformancerecord_finding_ids() -> None:
    """SE-001 must also read the SkillPerformanceRecord reviewer_finding_ids shape."""
    evaluator = SkillEvaluator()
    records = [{"reviewer_finding_ids": ["CC-001"]} for _ in range(3)]
    result = evaluator.evaluate_triggers(records, "SE-001")
    assert result.triggered is True
    assert "CC-001" in result.evidence


def test_se002_low_pass_rate_triggers() -> None:
    evaluator = SkillEvaluator()
    records = [{"passed_tests": 1, "total_tests": 5} for _ in range(10)]
    result = evaluator.evaluate_triggers(records, "SE-002")
    assert result.triggered is True
    assert result.evidence["avg_pass_rate"] == 0.2


def test_se002_healthy_pass_rate_no_trigger() -> None:
    evaluator = SkillEvaluator()
    records = [{"passed_tests": 5, "total_tests": 5} for _ in range(10)]
    result = evaluator.evaluate_triggers(records, "SE-002")
    assert result.triggered is False


def test_se003_latest_failed_tests_triggers() -> None:
    evaluator = SkillEvaluator()
    records = [{"failed_test_ids": ["TEST-T03"]}, {"failed_test_ids": []}]
    result = evaluator.evaluate_triggers(records, "SE-003")
    assert result.triggered is True
    assert result.evidence["failed_test_ids"] == ["TEST-T03"]


def test_se004_manual_always_triggers() -> None:
    evaluator = SkillEvaluator()
    result = evaluator.evaluate_triggers([], "SE-004")
    assert result.triggered is True


# ---------------------------------------------------------------------------
# SkillEvaluator — root-cause localisation
# ---------------------------------------------------------------------------


def test_root_cause_maps_known_check_to_section() -> None:
    evaluator = SkillEvaluator()
    rc = evaluator.analyze_root_cause("statistics/t-test", ["CC-006"], {"CC-006": 3})
    assert rc.affected_sections[0]["affected_section"] == FINDING_TO_SECTION["CC-006"]
    assert rc.confidence == "high"


def test_root_cause_unknown_check_is_low_confidence() -> None:
    evaluator = SkillEvaluator()
    rc = evaluator.analyze_root_cause("statistics/t-test", ["ZZ-999"])
    assert rc.affected_sections[0]["affected_section"] == "Unknown section"
    assert rc.confidence == "low"


def test_build_report_recommends_proposer_when_triggered() -> None:
    evaluator = SkillEvaluator()
    trigger = TriggerResult("SE-001", True, {"CC-006": 3}, "recurring")
    report = evaluator.build_evaluation_report(
        "statistics/t-test", "core", "2.0.0", trigger
    )
    assert report.recommendation == "proceed_to_skill_proposer"
    d = report.to_dict()
    assert d["root_cause"]["affected_sections"][0]["finding_id"] == "CC-006"
    # No raw data / var_n leakage in the report.
    assert "var_" not in str(d)


def test_build_report_no_action_when_not_triggered() -> None:
    evaluator = SkillEvaluator()
    trigger = TriggerResult("SE-002", False, {"avg_pass_rate": 0.95}, "healthy")
    report = evaluator.build_evaluation_report(
        "statistics/t-test", "core", "2.0.0", trigger
    )
    assert report.recommendation == "no_action_required"


# ---------------------------------------------------------------------------
# SkillProposer — concrete diffs + impact
# ---------------------------------------------------------------------------


def _report_for(check_ids: list[str], version: str = "2.0.0") -> object:
    evaluator = SkillEvaluator()
    trigger = TriggerResult("SE-001", True, {c: 3 for c in check_ids}, "recurring")
    return evaluator.build_evaluation_report(
        "statistics/t-test", "core", version, trigger
    )


def test_proposer_generates_concrete_diff_for_cc006() -> None:
    proposer = SkillProposer()
    changes, impact = proposer.build_proposal_changes(_report_for(["CC-006"]))
    cc006 = next(c for c in changes if c["addresses_finding"] == "CC-006")
    assert cc006["diff"] is not None
    assert "ci_excludes_null" in cc006["diff"]
    assert cc006["section"] == "Validation Rules"
    # add-type change → MINOR bump
    assert impact.version_bump_type == "MINOR"
    assert impact.proposed_version == "2.1.0"


def test_proposer_unknown_finding_is_advisory_only() -> None:
    proposer = SkillProposer()
    changes, _ = proposer.build_proposal_changes(_report_for(["ZZ-000"]))
    assert changes[0]["diff"] is None
    assert changes[0]["change_type"] == "advisory"


def test_proposer_every_change_records_addresses_finding() -> None:
    proposer = SkillProposer()
    changes, _ = proposer.build_proposal_changes(_report_for(["CC-001", "CC-006"]))
    for c in changes:
        assert c["addresses_finding"]


def test_change_strategies_target_existing_sections() -> None:
    """Every strategy must target a section that FINDING_TO_SECTION knows."""
    for cid, (section, _type, _diff) in CHANGE_STRATEGIES.items():
        assert FINDING_TO_SECTION.get(cid) == section


# ---------------------------------------------------------------------------
# _apply_changes_to_content — deterministic splicing
# ---------------------------------------------------------------------------


_SKILL_WITH_SECTION = (
    "# Version: 2.0.0\n\n"
    "## Overview\nA skill.\n\n"
    "## Validation Rules\n\n"
    "- existing rule\n\n"
    "## Tests\n\n- t1\n"
)


def test_apply_inserts_block_into_named_section() -> None:
    changes = [
        {
            "section": "Validation Rules",
            "diff": "- **[auto/CC-006] new executable check**",
            "change_type": "add",
        }
    ]
    result = _apply_changes_to_content(_SKILL_WITH_SECTION, changes)
    assert "[auto/CC-006] new executable check" in result
    # Inserted inside Validation Rules, before the Tests header.
    vr_idx = result.index("## Validation Rules")
    tests_idx = result.index("## Tests")
    new_idx = result.index("[auto/CC-006]")
    assert vr_idx < new_idx < tests_idx


def test_apply_appends_missing_section() -> None:
    content = "# Version: 1.0.0\n\n## Description\nOnly this.\n"
    changes = [
        {"section": "Validation Rules", "diff": "- new rule", "change_type": "add"}
    ]
    result = _apply_changes_to_content(content, changes)
    assert "## Validation Rules" in result
    assert "- new rule" in result


def test_apply_is_idempotent() -> None:
    changes = [
        {"section": "Validation Rules", "diff": "- unique-block-xyz", "change_type": "add"}
    ]
    once = _apply_changes_to_content(_SKILL_WITH_SECTION, changes)
    twice = _apply_changes_to_content(once, changes)
    assert once == twice
    assert once.count("- unique-block-xyz") == 1


def test_apply_skips_advisory_none_diff() -> None:
    changes = [{"section": "Procedure", "diff": None, "change_type": "advisory"}]
    result = _apply_changes_to_content(_SKILL_WITH_SECTION, changes)
    assert result == _SKILL_WITH_SECTION
