# SKILL: Skill Performance Evaluator
# Skill ID: meta/skill-evaluator
# Version: 1.0.0
# Namespace: meta
# Consumers: orchestrator (triggered by evaluation results)
# Knowledge references:
#   - spec/skill-lifecycle.md (trigger conditions SE-001 to SE-004)
#   - evaluation/regression.yaml (skill performance thresholds)
#   - evaluation/correctness.yaml (dimension scores)

## Overview

Analyzes evaluation results to detect underperforming Skills and generates
a structured SkillEvaluationReport. This report is consumed by
meta/skill-proposer/ to generate improvement proposals.

This Skill does NOT modify any Skill file. It produces analysis only.

Triggered when:
- SE-001: recurring advisory finding (≥3/5 recent executions)
- SE-002: skill pass rate < 80% over last 10 executions
- SE-003: test failure on new data pattern
- SE-004: manual request

---

## Procedure

### Step 1 — Collect SkillPerformanceRecords

```python
def collect_skill_records(
    skill_id: str,
    namespace: str,
    lookback_executions: int = 10
) -> list[dict]:
    """
    Query skill_performance_records from cie_database.db.
    Sorted by timestamp descending.
    """
    query = """
        SELECT *
        FROM skill_performance_records
        WHERE skill_id = ?
          AND skill_namespace = ?
        ORDER BY timestamp DESC
        LIMIT ?
    """
    return db.execute(query, [skill_id, namespace, lookback_executions])
```

### Step 2 — Evaluate trigger conditions

```python
def evaluate_triggers(records: list[dict], trigger_id: str) -> TriggerResult:

    if trigger_id == "SE-001":
        # Recurring finding: same finding_id in ≥3 of last 5 executions
        last_5 = records[:5]
        all_findings = [f for r in last_5 for f in r["reviewer_findings"]["finding_ids"]]
        from collections import Counter
        freq = Counter(all_findings)
        recurring = {fid: cnt for fid, cnt in freq.items() if cnt >= 3}
        return TriggerResult(
            triggered=bool(recurring),
            evidence=recurring,
            description=f"Recurring findings: {recurring}"
        )

    elif trigger_id == "SE-002":
        # Low pass rate: avg < 0.80 over last 10
        pass_rates = [
            r["test_results"]["passed"] / max(r["test_results"]["total_tests"], 1)
            for r in records
        ]
        avg_rate = sum(pass_rates) / max(len(pass_rates), 1)
        return TriggerResult(
            triggered=avg_rate < 0.80,
            evidence={"avg_pass_rate": round(avg_rate, 3)},
            description=f"Average pass rate: {avg_rate:.1%}"
        )

    elif trigger_id == "SE-003":
        # Any test failure in most recent execution
        latest = records[0] if records else None
        if not latest:
            return TriggerResult(triggered=False)
        failed = latest["test_results"]["failed"]
        return TriggerResult(
            triggered=failed > 0,
            evidence={"failed_tests": latest["test_results"]["failed_test_ids"]},
            description=f"Test failures in latest execution: {failed}"
        )
```

### Step 3 — Analyze root cause

```python
def analyze_root_cause(
    skill_id: str,
    triggered_by: TriggerResult,
    records: list[dict]
) -> RootCauseAnalysis:
    """
    Identify the most likely section of SKILL.md that caused the issue.
    Maps finding_ids to SKILL.md sections.
    """
    FINDING_TO_SECTION = {
        "CC-001": "Validation Rules (p-value extraction)",
        "CC-002": "Validation Rules (effect size extraction)",
        "CC-006": "Validation Rules (CI direction check)",
        "TEST-T03": "Step 3 — Method selection branch (paired)",
        "TEST-T05": "Step 4 — Effect size computation",
    }

    affected_sections = []
    for finding_id in triggered_by.evidence.keys():
        section = FINDING_TO_SECTION.get(finding_id, "Unknown section")
        affected_sections.append({
            "finding_id": finding_id,
            "affected_section": section,
            "frequency": triggered_by.evidence[finding_id]
        })

    return RootCauseAnalysis(
        skill_id=skill_id,
        affected_sections=affected_sections,
        confidence="high" if len(affected_sections) == 1 else "medium"
    )
```

### Step 4 — Generate SkillEvaluationReport

```python
skill_evaluation_report = {
    "report_id": generate_uuid(),
    "generated_at": utc_now(),
    "target_skill": {
        "skill_id": skill_id,
        "namespace": namespace,
        "current_version": read_skill_version(skill_id)
    },
    "trigger": {
        "trigger_id": trigger_id,
        "triggered": trigger_result.triggered,
        "evidence": trigger_result.evidence,
        "description": trigger_result.description
    },
    "root_cause": root_cause_analysis,
    "performance_summary": {
        "avg_pass_rate": avg_pass_rate,
        "recurring_findings": recurring_findings,
        "executions_analyzed": len(records)
    },
    "recommendation": "proceed_to_skill_proposer"
        if trigger_result.triggered else "no_action_required",
    "next_step": "meta/skill-proposer"
}
```

---

## Validation Rules

- `trigger.triggered = false` のとき `recommendation = "no_action_required"`
- `affected_sections` は必ず SKILL.md の実在するセクション名を参照する
- rawデータや患者情報をレポートに含めない
- このSkillはいかなるファイルも変更しない（read-only）

---

## Tests

### TEST-SE01: SE-001トリガーの正確な検出

```python
# CC-006が5回中3回出現 → triggered=True
records = [{"reviewer_findings": {"finding_ids": ["CC-006"]}} for _ in range(3)]
records += [{"reviewer_findings": {"finding_ids": []}} for _ in range(2)]
result = evaluate_triggers(records, "SE-001")
assert result.triggered == True
assert "CC-006" in result.evidence
```

### TEST-SE02: SE-002は5回中4回失敗でもトリガーしない（pass_rate=0.20 < 0.80）

```python
records = [{"test_results": {"passed": 1, "total_tests": 5}} for _ in range(10)]
result = evaluate_triggers(records, "SE-002")
assert result.triggered == True
assert result.evidence["avg_pass_rate"] == 0.2
```

### TEST-SE03: レポートにrawデータが含まれないこと

```python
report = generate_evaluation_report(skill_id="statistics/t-test", ...)
assert "patient" not in str(report).lower()
assert "var_" not in str(report)   # var_n aliases must not leak
```
