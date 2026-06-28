"""CIE Platform — EvaluatorService: Evaluation pipeline orchestrator.

Runs all registered BaseEvaluator instances for a single workflow execution,
computes the weighted aggregate score, writes the result to the audit log,
and records SkillPerformanceRecord for ADR-0002 monitoring.

Architecture constraints:
  - SkillPerformanceRecord write happens AFTER EvaluationReport is built
    and does not affect the evaluation result.
  - Weight sum across all registered evaluators must equal 100.
  - MINIMUM_PASS_SCORE = 90.0 per spec/configuration.yaml
    §evaluation_gateways.global_minimum_pass_score.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from sqlalchemy import select

from cie.core.audit import AuditEvent, AuditEventSeverity, AuditService
from cie.core.database import SkillPerformanceRecord
from cie.evaluation.base import (
    BaseEvaluator,
    DimensionScore,
    EvaluationDimension,
    EvaluationReport,
)
from cie.evaluation.regression import RegressionChecker

logger = logging.getLogger(__name__)

# Threshold from spec/configuration.yaml §evaluation_gateways
MINIMUM_PASS_SCORE: float = 90.0


class EvaluatorService:
    """Orchestrates all evaluation dimensions and records results.

    Responsibilities:
      1. Run each registered BaseEvaluator against the provided artifacts.
      2. Compute weighted_total_score from DimensionScore.weight_pct.
      3. Determine overall passed status.
      4. Write an EvaluationCompleted audit event.
      5. Write a SkillPerformanceRecord to the database (ADR-0002).
      6. Check skill degradation triggers via RegressionChecker.

    Args:
        evaluators: List of BaseEvaluator subclass instances.
            Weights must sum to 100.
        audit_service: The platform AuditService instance.
        db_session_factory: Zero-argument callable returning an async
            SQLAlchemy session context manager (for SkillPerformanceRecord).
    """

    def __init__(
        self,
        evaluators: list[BaseEvaluator],
        audit_service: AuditService,
        db_session_factory: Callable,
    ) -> None:
        self._evaluators = evaluators
        self._audit = audit_service
        self._session_factory = db_session_factory
        self._regression_checker = RegressionChecker(db_session_factory)

        # Validate weights at startup — fail fast
        total_weight = sum(e.weight_pct for e in evaluators)
        if total_weight != 100:
            raise ValueError(
                f"EvaluatorService: evaluator weights must sum to 100, got {total_weight}. "
                f"Registered: {[(type(e).__name__, e.weight_pct) for e in evaluators]}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_full_evaluation(
        self,
        execution_id: str,
        artifacts: dict,
    ) -> EvaluationReport:
        """Run all evaluators and return an EvaluationReport.

        Steps:
          1. Run each evaluator → collect DimensionScore dict.
          2. Build EvaluationReport via EvaluationReport.build().
          3. Emit EvaluationCompleted audit event.
          4. Write SkillPerformanceRecord (non-blocking; errors logged only).
          5. Check and log regression triggers (non-blocking).

        Args:
            execution_id: Orchestrator execution identifier.
            artifacts: Shared artifact dict passed to every evaluator.

        Returns:
            Fully populated EvaluationReport.
        """
        dimension_scores: dict[EvaluationDimension, DimensionScore] = {}

        for evaluator in self._evaluators:
            try:
                score = evaluator.evaluate(artifacts)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Evaluator %s raised unexpectedly: %s",
                    type(evaluator).__name__,
                    exc,
                    exc_info=True,
                )
                # Produce a zero score to avoid silently skipping evaluation
                from cie.evaluation.base import CheckResult
                score = DimensionScore(
                    dimension=evaluator.dimension,
                    score=0.0,
                    weight_pct=evaluator.weight_pct,
                    check_results=[
                        CheckResult(
                            check_id=f"{evaluator.dimension.value.upper()}-EXCEPTION",
                            dimension=evaluator.dimension,
                            passed=False,
                            severity="critical",
                            message=f"Evaluator raised an unexpected exception: {exc}",
                        )
                    ],
                    critical_failure=True,
                )
            dimension_scores[evaluator.dimension] = score

        report = EvaluationReport.build(
            execution_id=execution_id,
            dimension_scores=dimension_scores,
        )

        # Audit event
        await self._emit_audit_event(execution_id, report)

        # SkillPerformanceRecord (ADR-0002) — fire-and-log, never raises
        skill_id = artifacts.get("skill_id") or ""
        workflow_id = artifacts.get("workflow_id") or ""
        if skill_id:
            try:
                await self._write_skill_performance_record(
                    execution_id=execution_id,
                    workflow_id=workflow_id,
                    evaluation_report=report,
                    artifacts=artifacts,
                )
                await self._check_and_log_triggers(
                    execution_id=execution_id,
                    skill_id=skill_id,
                    skill_namespace=artifacts.get("skill_namespace") or "core",
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "SkillPerformanceRecord write failed for skill_id=%s: %s",
                    skill_id,
                    exc,
                    exc_info=True,
                )

        return report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _emit_audit_event(
        self,
        execution_id: str,
        report: EvaluationReport,
    ) -> None:
        """Write EvaluationCompleted audit event."""
        try:
            await self._audit.write(
                AuditEvent(
                    execution_id=execution_id,
                    agent_id="evaluation",
                    action="EVALUATION_COMPLETED",
                    status="passed" if report.passed else "failed",
                    severity=(
                        AuditEventSeverity.INFO
                        if report.passed
                        else AuditEventSeverity.WARNING
                    ),
                    payload={
                        "report_id": report.report_id,
                        "weighted_total_score": report.weighted_total_score,
                        "passed": report.passed,
                        "dimension_scores": {
                            dim.value: score.score
                            for dim, score in report.dimension_scores.items()
                        },
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write evaluation audit event: %s", exc)

    async def _write_skill_performance_record(
        self,
        execution_id: str,
        workflow_id: str,
        evaluation_report: EvaluationReport,
        artifacts: dict,
    ) -> None:
        """Persist a SkillPerformanceRecord for ADR-0002 monitoring.

        Extracts correctness and statistical dimension scores from the
        evaluation report and persists them alongside test result metadata.

        Args:
            execution_id: Orchestrator execution identifier.
            workflow_id: Parent workflow identifier.
            evaluation_report: Completed EvaluationReport.
            artifacts: Full artifact dict (provides skill_id, etc.).
        """
        skill_id: str = artifacts.get("skill_id") or ""
        skill_namespace: str = artifacts.get("skill_namespace") or "core"
        skill_version: str | None = artifacts.get("skill_version")

        # Extract test counts from review_report if available
        review_report: dict = artifacts.get("review_report") or {}
        total_tests: int | None = review_report.get("total_tests")
        passed_tests: int | None = review_report.get("passed_tests")
        failed_test_ids: list = review_report.get("failed_test_ids") or []
        reviewer_finding_ids: list = review_report.get("reviewer_finding_ids") or []

        # Dimension scores
        scores = evaluation_report.dimension_scores
        correctness_score: float | None = (
            scores[EvaluationDimension.CORRECTNESS].score
            if EvaluationDimension.CORRECTNESS in scores
            else None
        )
        statistical_score: float | None = (
            scores[EvaluationDimension.STATISTICAL].score
            if EvaluationDimension.STATISTICAL in scores
            else None
        )

        record = SkillPerformanceRecord(
            id=str(uuid4()),
            skill_id=skill_id,
            skill_namespace=skill_namespace,
            skill_version=skill_version,
            execution_id=execution_id,
            workflow_id=workflow_id or None,
            total_tests=total_tests,
            passed_tests=passed_tests,
            failed_test_ids=failed_test_ids or None,
            reviewer_finding_ids=reviewer_finding_ids or None,
            correctness_score=correctness_score,
            statistical_score=statistical_score,
            timestamp=datetime.now(timezone.utc),
        )

        async with self._session_factory() as session:
            session.add(record)
            await session.commit()

        logger.info(
            "SkillPerformanceRecord written: skill_id=%s execution_id=%s",
            skill_id,
            execution_id,
        )

    async def _check_and_log_triggers(
        self,
        execution_id: str,
        skill_id: str,
        skill_namespace: str,
    ) -> None:
        """Check regression triggers and log to audit if any fire.

        Args:
            execution_id: Current execution context.
            skill_id: Skill to check.
            skill_namespace: "core" or "user".
        """
        triggered = await self._regression_checker.check_skill_triggers(
            skill_id=skill_id,
            skill_namespace=skill_namespace,
        )

        if triggered:
            await self._audit.write(
                AuditEvent(
                    execution_id=execution_id,
                    agent_id="evaluation",
                    action="SKILL_EVALUATION_TRIGGERED",
                    status="triggered",
                    severity=AuditEventSeverity.WARNING,
                    payload={
                        "skill_id": skill_id,
                        "skill_namespace": skill_namespace,
                        "triggers": triggered,
                        "recommendation": "dispatch meta/skill-evaluator",
                    },
                )
            )
            logger.warning(
                "Skill degradation triggers fired for %s: %s",
                skill_id,
                triggered,
            )
