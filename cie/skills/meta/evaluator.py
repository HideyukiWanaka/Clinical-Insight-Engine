"""CIE Platform — SkillEvaluator (Python impl of meta/skill-evaluator).

Analyses reviewer findings and SkillPerformanceRecord history to detect skill
degradation (triggers SE-001…SE-004) and localise the most likely SKILL.md
section responsible for a recurring finding.

This component is READ-ONLY (ADR-0002 Principle 4): it never writes a Skill file.
Its output (SkillEvaluationReport) is consumed by
``cie.skills.meta.proposer.SkillProposer`` to draft concrete change proposals.

Design notes:
  - Recurring-finding detection keys on the reviewer *check_id* (CC-001…CC-007),
    not the per-execution unique finding_id (``RV-CC006-ab12cd``). The check_id
    is the stable class-of-problem identifier, so "the same problem keeps
    happening" is expressed as "the same check_id keeps failing".
  - Record normalisation accepts both the ``SkillPerformanceRecord``-shaped dict
    (``finding_ids`` / ``check_ids`` / ``total_tests`` / ``passed_tests`` /
    ``failed_test_ids``) and the illustrative nested form used in the SKILL.md.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Windows / thresholds mirror cie.evaluation.regression (regression.yaml).
RECURRING_FINDING_WINDOW: int = 5
RECURRING_FINDING_THRESHOLD: int = 3
PASS_RATE_WINDOW: int = 10
PASS_RATE_THRESHOLD: float = 0.80

# check_id → the SKILL.md section most likely responsible for the finding.
# These are the reviewer consistency checks CC-001…CC-007 (agents/reviewer.yaml).
FINDING_TO_SECTION: dict[str, str] = {
    "CC-001": "Validation Rules",   # p-value traceability
    "CC-002": "Validation Rules",   # effect-size traceability
    "CC-003": "Validation Rules",   # sample-size consistency
    "CC-004": "Procedure",          # figure references
    "CC-005": "Procedure",          # reporting checklist completion
    "CC-006": "Validation Rules",   # CI direction vs significance
    "CC-007": "Procedure",          # unresolved items resolution
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


@dataclass
class TriggerResult:
    """Outcome of evaluating a single SE-xxx trigger against records."""

    trigger_id: str
    triggered: bool
    evidence: dict = field(default_factory=dict)
    description: str = ""


@dataclass
class RootCauseAnalysis:
    """Localisation of a trigger to concrete SKILL.md sections."""

    skill_id: str
    affected_sections: list[dict]
    confidence: str  # "high" | "medium" | "low"


@dataclass
class SkillEvaluationReport:
    """Structured analysis consumed by SkillProposer. Contains no raw data."""

    report_id: str
    generated_at: datetime
    target_skill_id: str
    target_namespace: str
    current_version: str
    trigger: TriggerResult
    root_cause: RootCauseAnalysis
    performance_summary: dict
    recommendation: str  # "proceed_to_skill_proposer" | "no_action_required"

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at.isoformat(),
            "target_skill": {
                "skill_id": self.target_skill_id,
                "namespace": self.target_namespace,
                "current_version": self.current_version,
            },
            "trigger": {
                "trigger_id": self.trigger.trigger_id,
                "triggered": self.trigger.triggered,
                "evidence": self.trigger.evidence,
                "description": self.trigger.description,
            },
            "root_cause": {
                "skill_id": self.root_cause.skill_id,
                "affected_sections": self.root_cause.affected_sections,
                "confidence": self.root_cause.confidence,
            },
            "performance_summary": self.performance_summary,
            "recommendation": self.recommendation,
            "next_step": "meta/skill-proposer",
        }


# ---------------------------------------------------------------------------
# Record normalisation
# ---------------------------------------------------------------------------


def _record_check_ids(record: dict) -> list[str]:
    """Extract reviewer check_ids from a record in any supported shape."""
    # Preferred: explicit check_ids list.
    if record.get("check_ids"):
        return [str(c) for c in record["check_ids"]]
    # SkillPerformanceRecord form: reviewer_finding_ids may hold check_ids.
    if record.get("reviewer_finding_ids"):
        return [str(c) for c in record["reviewer_finding_ids"]]
    # SKILL.md illustrative nested form.
    nested = (record.get("reviewer_findings") or {}).get("finding_ids")
    if nested:
        return [str(c) for c in nested]
    # Structured findings list (reviewer review_report.findings shape).
    findings = record.get("findings")
    if isinstance(findings, list):
        return [
            str(f.get("check_id"))
            for f in findings
            if isinstance(f, dict) and f.get("check_id")
        ]
    return []


def _record_pass_rate(record: dict) -> float | None:
    """Return passed/total for a record, or None if counts are unavailable."""
    total = record.get("total_tests")
    passed = record.get("passed_tests")
    if total is None or passed is None:
        results = record.get("test_results") or {}
        total = results.get("total_tests", results.get("total"))
        passed = results.get("passed")
    if not total:
        return None
    return float(passed or 0) / float(total)


def _record_failed_ids(record: dict) -> list[str]:
    if record.get("failed_test_ids"):
        return [str(t) for t in record["failed_test_ids"]]
    results = record.get("test_results") or {}
    return [str(t) for t in (results.get("failed_test_ids") or [])]


# ---------------------------------------------------------------------------
# SkillEvaluator
# ---------------------------------------------------------------------------


class SkillEvaluator:
    """Detects skill degradation triggers and localises the root cause.

    Pure analysis — holds no I/O and mutates nothing. Callers pass in the
    normalised performance records (newest first).
    """

    def evaluate_triggers(self, records: list[dict], trigger_id: str) -> TriggerResult:
        """Evaluate a single SE-xxx trigger against ``records`` (newest first)."""
        if trigger_id == "SE-001":
            window = records[:RECURRING_FINDING_WINDOW]
            counter: Counter[str] = Counter()
            for rec in window:
                for cid in _record_check_ids(rec):
                    counter[cid] += 1
            recurring = {
                cid: cnt
                for cid, cnt in counter.items()
                if cnt >= RECURRING_FINDING_THRESHOLD
            }
            return TriggerResult(
                trigger_id="SE-001",
                triggered=bool(recurring),
                evidence=recurring,
                description=f"Recurring findings (≥{RECURRING_FINDING_THRESHOLD}/"
                f"{RECURRING_FINDING_WINDOW}): {recurring}"
                if recurring
                else "No recurring findings detected",
            )

        if trigger_id == "SE-002":
            window = records[:PASS_RATE_WINDOW]
            rates = [r for r in (_record_pass_rate(rec) for rec in window) if r is not None]
            avg = sum(rates) / len(rates) if rates else 1.0
            return TriggerResult(
                trigger_id="SE-002",
                triggered=bool(rates) and avg < PASS_RATE_THRESHOLD,
                evidence={"avg_pass_rate": round(avg, 3), "executions": len(rates)},
                description=f"Average pass rate: {avg:.1%}",
            )

        if trigger_id == "SE-003":
            latest = records[0] if records else None
            failed = _record_failed_ids(latest) if latest else []
            return TriggerResult(
                trigger_id="SE-003",
                triggered=bool(failed),
                evidence={"failed_test_ids": failed},
                description=f"Test failures in latest execution: {len(failed)}",
            )

        # SE-004: manual request — always considered "triggered" so the human
        # can force an evaluation regardless of automatic thresholds.
        if trigger_id == "SE-004":
            return TriggerResult(
                trigger_id="SE-004",
                triggered=True,
                evidence={"manual": True},
                description="Manual evaluation request",
            )

        return TriggerResult(
            trigger_id=trigger_id,
            triggered=False,
            evidence={},
            description=f"Unknown trigger_id: {trigger_id}",
        )

    def analyze_root_cause(
        self,
        skill_id: str,
        finding_ids: list[str],
        evidence: dict | None = None,
    ) -> RootCauseAnalysis:
        """Map failing check_ids to the SKILL.md sections responsible.

        Args:
            skill_id: Target skill.
            finding_ids: reviewer check_ids (CC-001…CC-007) implicated.
            evidence: optional {check_id: frequency} for the SE-001 case.
        """
        evidence = evidence or {}
        affected: list[dict] = []
        for cid in finding_ids:
            affected.append(
                {
                    "finding_id": cid,
                    "affected_section": FINDING_TO_SECTION.get(cid, "Unknown section"),
                    "frequency": evidence.get(cid),
                }
            )
        # Confidence is high when a single, known section is implicated.
        known = [a for a in affected if a["affected_section"] != "Unknown section"]
        if affected and len(known) == len(affected) and len({a["affected_section"] for a in affected}) == 1:
            confidence = "high"
        elif known:
            confidence = "medium"
        else:
            confidence = "low"
        return RootCauseAnalysis(
            skill_id=skill_id,
            affected_sections=affected,
            confidence=confidence,
        )

    def build_evaluation_report(
        self,
        skill_id: str,
        namespace: str,
        current_version: str,
        trigger: TriggerResult,
        records: list[dict] | None = None,
    ) -> SkillEvaluationReport:
        """Assemble the full SkillEvaluationReport for a triggered condition."""
        records = records or []
        # The finding_ids driving the root cause come from the trigger evidence
        # (SE-001) or the failing tests / latest findings otherwise.
        if trigger.trigger_id == "SE-001":
            finding_ids = list(trigger.evidence.keys())
        elif records:
            finding_ids = _record_check_ids(records[0])
        else:
            finding_ids = []

        root_cause = self.analyze_root_cause(
            skill_id, finding_ids, evidence=trigger.evidence
        )

        rates = [r for r in (_record_pass_rate(rec) for rec in records) if r is not None]
        performance_summary = {
            "avg_pass_rate": round(sum(rates) / len(rates), 3) if rates else None,
            "recurring_findings": trigger.evidence if trigger.trigger_id == "SE-001" else {},
            "executions_analyzed": len(records),
        }

        return SkillEvaluationReport(
            report_id=str(uuid.uuid4()),
            generated_at=_utc_now(),
            target_skill_id=skill_id,
            target_namespace=namespace,
            current_version=current_version,
            trigger=trigger,
            root_cause=root_cause,
            performance_summary=performance_summary,
            recommendation="proceed_to_skill_proposer"
            if trigger.triggered
            else "no_action_required",
        )
