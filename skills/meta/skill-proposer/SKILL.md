# SKILL: Skill Improvement Proposer
# Skill ID: meta/skill-proposer
# Version: 1.0.0
# Namespace: meta
# Consumers: orchestrator (triggered by skill-evaluator output)
# Knowledge references:
#   - spec/skill-lifecycle.md (SkillImprovementProposal schema)
#   - skills/core/{target_skill_id}/SKILL.md (target for improvement)

## Overview

Generates a structured SkillImprovementProposal from a SkillEvaluationReport.
The proposal contains:
- Specific diff-style changes to SKILL.md
- New or modified test cases
- Impact assessment

CRITICAL: This Skill generates proposals ONLY.
It does NOT write to any Skill file.
All file changes require explicit human approval (ADR-0002 Principle 4).

---

## Procedure

### Step 1 — Load target Skill content

```python
def load_skill_content(skill_id: str, namespace: str) -> dict:
    """
    Read the current SKILL.md content of the target skill.
    Parsed into sections: Overview, Procedure, Validation Rules, Tests.
    """
    skill_path = resolve_skill_path(skill_id, namespace)
    content = read_file(skill_path / "SKILL.md")
    return parse_skill_sections(content)
```

### Step 2 — Map root cause to change strategy

```python
CHANGE_STRATEGIES = {
    # finding_id → (target_section, change_type, template)
    "CC-006": (
        "Validation Rules",
        "add",
        """
# CI direction consistency check (addresses CC-006 recurring finding)
if (result$primary_result$p_value < 0.05) {{
  ci_excludes_null <- result$primary_result$ci_lower > 0 ||
                       result$primary_result$ci_upper < 0
  if (!ci_excludes_null) {{
    stop(paste(
      "CI_DIRECTION_INCONSISTENT: p =",
      round(result$primary_result$p_value, 4),
      "but CI [",
      round(result$primary_result$ci_lower, 3), ",",
      round(result$primary_result$ci_upper, 3), "] includes null value."
    ))
  }}
}}
"""
    ),
    "CC-001": (
        "Step 5 — Structure output",
        "modify",
        "Add explicit p_value traceability assertion before returning skill_result."
    ),
    "TEST-T03": (
        "tests/",
        "add",
        "Add test case for the specific branch that failed."
    ),
}

def map_findings_to_changes(root_cause: RootCauseAnalysis) -> list[ProposedChange]:
    changes = []
    for finding in root_cause.affected_sections:
        finding_id = finding["finding_id"]
        if finding_id in CHANGE_STRATEGIES:
            section, change_type, template = CHANGE_STRATEGIES[finding_id]
            changes.append(ProposedChange(
                change_id=f"CHG-{generate_short_id()}",
                finding_id=finding_id,
                section=section,
                change_type=change_type,
                description=f"Address {finding_id}: {finding['affected_section']}",
                diff=template,
                addresses_finding=finding_id
            ))
        else:
            # Unknown finding: generate advisory-only change
            changes.append(ProposedChange(
                change_id=f"CHG-{generate_short_id()}",
                finding_id=finding_id,
                section="Unknown",
                change_type="advisory",
                description=f"Manual review required for {finding_id}",
                diff=None,
                addresses_finding=finding_id
            ))
    return changes
```

### Step 3 — Assess impact

```python
def assess_impact(
    proposed_changes: list[ProposedChange],
    current_skill_version: str
) -> ImpactAssessment:

    has_breaking = any(c.change_type == "remove" for c in proposed_changes)
    has_interface_change = any(
        c.section in ("Component Contract", "input_schema", "output_schema")
        for c in proposed_changes
    )

    # Determine version bump
    if has_interface_change:
        version_bump = "MAJOR"
    elif any(c.change_type == "add" for c in proposed_changes):
        version_bump = "MINOR"
    else:
        version_bump = "PATCH"

    proposed_version = bump_version(current_skill_version, version_bump)

    return ImpactAssessment(
        breaking_change=has_interface_change,
        regression_risk="high" if has_interface_change else
                        "medium" if version_bump == "MINOR" else "low",
        proposed_version=proposed_version,
        version_bump_type=version_bump,
        test_coverage_delta=f"+{sum(1 for c in proposed_changes if c.section == 'tests/')} test(s)"
    )
```

### Step 4 — Assemble SkillImprovementProposal

```python
proposal = {
    "proposal_id": f"prop-{utc_date()}-{generate_short_id()}",
    "generated_at": utc_now(),
    "generated_by": "meta/skill-proposer",

    "target_skill": {
        "skill_id": skill_id,
        "namespace": namespace,
        "current_version": current_version,
        "proposed_version": impact.proposed_version
    },

    "trigger": evaluation_report["trigger"],
    "root_cause": evaluation_report["root_cause"],

    "proposed_changes": [c.to_dict() for c in proposed_changes],
    "estimated_impact": impact.to_dict(),

    # ADR-0002 Principle 4: always True
    "human_review_required": True,
    "proposal_status": "pending_human_review",

    # Changelog entry for SKILL.md header
    "changelog_entry": (
        f"# Changelog v{impact.proposed_version} "
        f"(proposed by meta/skill-proposer, proposal_id: prop-...)\n"
        f"#   - {'; '.join(c.description for c in proposed_changes)}"
    )
}

# Save proposal to database (NOT to Skill file)
db.insert("skill_improvement_proposals", proposal)
# Notify Orchestrator for human approval routing
notify_orchestrator(
    event="SKILL_IMPROVEMENT_PROPOSAL_READY",
    proposal_id=proposal["proposal_id"]
)
```

---

## Validation Rules

- `human_review_required` は常に `True`。False に設定することは禁止
- `proposal_status` の初期値は必ず `"pending_human_review"`
- `diff` フィールドは SKILL.md の実在するセクション名のみを参照する
- 提案がどのfinding_idに対応するかを `addresses_finding` に必ず記録する
- rawデータ・患者情報・実際のvar_n値を提案内容に含めない

---

## Tests

### TEST-SP01: human_review_required は常にTrue

```python
proposal = generate_proposal(evaluation_report=mock_report)
assert proposal["human_review_required"] == True
```

### TEST-SP02: 既知のfinding_idは具体的なdiffを生成する

```python
report = mock_evaluation_report(recurring_findings={"CC-006": 3})
proposal = generate_proposal(report)
cc006_change = next(c for c in proposal["proposed_changes"]
                    if c["finding_id"] == "CC-006")
assert cc006_change["diff"] is not None
assert "ci_excludes_null" in cc006_change["diff"]
```

### TEST-SP03: interface変更はMAJORバンプを生成する

```python
changes = [ProposedChange(section="Component Contract", change_type="modify")]
impact = assess_impact(changes, current_version="2.0.0")
assert impact.version_bump_type == "MAJOR"
assert impact.proposed_version == "3.0.0"
```

### TEST-SP04: 提案はいかなるファイルも変更しない

```python
files_before = snapshot_skill_directory("statistics/t-test")
generate_proposal(mock_evaluation_report)
files_after = snapshot_skill_directory("statistics/t-test")
assert files_before == files_after   # No file was modified
```
