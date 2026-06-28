"""Unit tests for cie.evaluation.evaluator_service.EvaluatorService
and cie.evaluation.regression.RegressionChecker.

Tests use unittest.mock to avoid real DB connections and audit writes.
Run with: pytest tests/unit/test_evaluator_service.py -v
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cie.evaluation.base import (
    BaseEvaluator,
    CheckResult,
    DimensionScore,
    EvaluationDimension,
)
from cie.evaluation.correctness import CorrectnessEvaluator
from cie.evaluation.evaluator_service import MINIMUM_PASS_SCORE, EvaluatorService
from cie.evaluation.regression import (
    PASS_RATE_THRESHOLD,
    PASS_RATE_WINDOW,
    RECURRING_FINDING_THRESHOLD,
    RECURRING_FINDING_WINDOW,
    RegressionChecker,
)
from cie.evaluation.security import SecurityEvaluator
from cie.evaluation.statistical import StatisticalEvaluator
from cie.evaluation.usability import UsabilityEvaluator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stub_evaluator(
    dimension: EvaluationDimension,
    weight_pct: int,
    score: float = 95.0,
    critical_failure: bool = False,
) -> BaseEvaluator:
    """Create a stub evaluator that always returns a fixed DimensionScore."""

    class _StubEvaluator(BaseEvaluator):
        @property
        def dimension(self) -> EvaluationDimension:
            return dimension

        @property
        def weight_pct(self) -> int:
            return weight_pct

        def evaluate(self, artifacts: dict) -> DimensionScore:
            return DimensionScore(
                dimension=dimension,
                score=score,
                weight_pct=weight_pct,
                check_results=[
                    CheckResult(
                        check_id=f"{dimension.value.upper()}-STUB",
                        dimension=dimension,
                        passed=not critical_failure,
                        severity="critical",
                        message="Stub check.",
                    )
                ],
                critical_failure=critical_failure,
            )

    return _StubEvaluator()


def _stub_evaluators(
    *,
    correctness_score: float = 95.0,
    statistical_score: float = 95.0,
    security_score: float = 95.0,
    usability_score: float = 95.0,
    security_critical: bool = False,
) -> list[BaseEvaluator]:
    """Return 4 stub evaluators that sum to 100% weight."""
    return [
        _make_stub_evaluator(EvaluationDimension.CORRECTNESS, 40, correctness_score),
        _make_stub_evaluator(EvaluationDimension.STATISTICAL, 35, statistical_score),
        _make_stub_evaluator(EvaluationDimension.SECURITY, 15, security_score, security_critical),
        _make_stub_evaluator(EvaluationDimension.USABILITY, 10, usability_score),
    ]


def _make_mock_audit() -> AsyncMock:
    audit = AsyncMock()
    audit.write = AsyncMock()
    return audit


@asynccontextmanager
async def _null_session() -> AsyncIterator:
    """Yield a mock session that does nothing."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    yield session


def _null_session_factory():
    return _null_session()


def _make_service(
    evaluators: list[BaseEvaluator] | None = None,
    audit: AsyncMock | None = None,
) -> EvaluatorService:
    return EvaluatorService(
        evaluators=evaluators or _stub_evaluators(),
        audit_service=audit or _make_mock_audit(),
        db_session_factory=_null_session_factory,
    )


_BASE_ARTIFACTS = {
    "skill_id": "statistics/t-test",
    "skill_namespace": "core",
    "skill_version": "1.0.0",
    "workflow_id": "workflow-001",
    "review_report": {
        "total_tests": 5,
        "passed_tests": 5,
        "failed_test_ids": [],
        "reviewer_finding_ids": [],
    },
}


# ---------------------------------------------------------------------------
# EvaluatorService — weight validation
# ---------------------------------------------------------------------------

class TestWeightValidation:
    def test_weights_not_100_raises_at_init(self) -> None:
        bad = [
            _make_stub_evaluator(EvaluationDimension.CORRECTNESS, 50),
            _make_stub_evaluator(EvaluationDimension.STATISTICAL, 30),
        ]
        with pytest.raises(ValueError, match="sum to 100"):
            _make_service(evaluators=bad)

    def test_weights_100_creates_service(self) -> None:
        svc = _make_service()
        assert svc is not None


# ---------------------------------------------------------------------------
# EvaluatorService — all_dimensions_run
# ---------------------------------------------------------------------------

class TestAllDimensionsRun:
    def test_all_dimensions_run(self) -> None:
        """All 4 registered evaluators must produce a DimensionScore."""
        svc = _make_service()
        report = asyncio.get_event_loop().run_until_complete(
            svc.run_full_evaluation("exec-001", _BASE_ARTIFACTS)
        )
        assert len(report.dimension_scores) == 4
        assert EvaluationDimension.CORRECTNESS in report.dimension_scores
        assert EvaluationDimension.STATISTICAL in report.dimension_scores
        assert EvaluationDimension.SECURITY in report.dimension_scores
        assert EvaluationDimension.USABILITY in report.dimension_scores


# ---------------------------------------------------------------------------
# EvaluatorService — weighted score calculation
# ---------------------------------------------------------------------------

class TestWeightedScore:
    def test_weighted_score_calculated(self) -> None:
        """Weighted score must equal sum(score * weight_pct / 100)."""
        evaluators = _stub_evaluators(
            correctness_score=100.0,
            statistical_score=80.0,
            security_score=60.0,
            usability_score=50.0,
        )
        # Expected: 100*0.40 + 80*0.35 + 60*0.15 + 50*0.10
        #         = 40 + 28 + 9 + 5 = 82.0
        expected = 100.0 * 0.40 + 80.0 * 0.35 + 60.0 * 0.15 + 50.0 * 0.10

        svc = _make_service(evaluators=evaluators)
        report = asyncio.get_event_loop().run_until_complete(
            svc.run_full_evaluation("exec-002", _BASE_ARTIFACTS)
        )
        assert abs(report.weighted_total_score - expected) < 0.01

    def test_all_100_gives_total_100(self) -> None:
        svc = _make_service(evaluators=_stub_evaluators(
            correctness_score=100.0,
            statistical_score=100.0,
            security_score=100.0,
            usability_score=100.0,
        ))
        report = asyncio.get_event_loop().run_until_complete(
            svc.run_full_evaluation("exec-003", _BASE_ARTIFACTS)
        )
        assert report.weighted_total_score == 100.0
        assert report.passed is True

    def test_score_below_threshold_fails(self) -> None:
        svc = _make_service(evaluators=_stub_evaluators(
            correctness_score=50.0,
            statistical_score=50.0,
            security_score=50.0,
            usability_score=50.0,
        ))
        report = asyncio.get_event_loop().run_until_complete(
            svc.run_full_evaluation("exec-004", _BASE_ARTIFACTS)
        )
        assert report.weighted_total_score == 50.0
        assert report.passed is False


# ---------------------------------------------------------------------------
# EvaluatorService — critical failure handling
# ---------------------------------------------------------------------------

class TestCriticalFailure:
    def test_critical_failure_fails_overall(self) -> None:
        """A single dimension with critical_failure=True sets passed=False."""
        evaluators = _stub_evaluators(security_critical=True, security_score=0.0)
        svc = _make_service(evaluators=evaluators)
        report = asyncio.get_event_loop().run_until_complete(
            svc.run_full_evaluation("exec-005", _BASE_ARTIFACTS)
        )
        assert report.passed is False
        assert report.dimension_scores[EvaluationDimension.SECURITY].critical_failure is True

    def test_no_critical_failure_with_high_scores_passes(self) -> None:
        svc = _make_service()
        report = asyncio.get_event_loop().run_until_complete(
            svc.run_full_evaluation("exec-006", _BASE_ARTIFACTS)
        )
        assert report.passed is True


# ---------------------------------------------------------------------------
# EvaluatorService — SkillPerformanceRecord
# ---------------------------------------------------------------------------

class TestSkillPerformanceRecord:
    def test_skill_performance_record_written(self) -> None:
        """SkillPerformanceRecord.add() must be called when skill_id is present."""
        added_records = []
        commit_called = []

        @asynccontextmanager
        async def capturing_session():
            session = AsyncMock()

            def capture_add(record):
                added_records.append(record)

            session.add = MagicMock(side_effect=capture_add)
            session.commit = AsyncMock(side_effect=lambda: commit_called.append(True))
            yield session

        svc = EvaluatorService(
            evaluators=_stub_evaluators(),
            audit_service=_make_mock_audit(),
            db_session_factory=capturing_session,
        )
        asyncio.get_event_loop().run_until_complete(
            svc.run_full_evaluation("exec-007", _BASE_ARTIFACTS)
        )

        assert len(added_records) == 1
        assert len(commit_called) >= 1
        record = added_records[0]
        assert record.skill_id == "statistics/t-test"
        assert record.skill_namespace == "core"
        assert record.execution_id == "exec-007"

    def test_no_skill_id_skips_record(self) -> None:
        """When skill_id is absent, no SkillPerformanceRecord is written."""
        added_records = []

        @asynccontextmanager
        async def capturing_session():
            session = AsyncMock()
            session.add = MagicMock(side_effect=added_records.append)
            session.commit = AsyncMock()
            yield session

        svc = EvaluatorService(
            evaluators=_stub_evaluators(),
            audit_service=_make_mock_audit(),
            db_session_factory=capturing_session,
        )
        artifacts_no_skill = {k: v for k, v in _BASE_ARTIFACTS.items() if k != "skill_id"}
        asyncio.get_event_loop().run_until_complete(
            svc.run_full_evaluation("exec-008", artifacts_no_skill)
        )
        assert len(added_records) == 0

    def test_audit_event_written(self) -> None:
        audit = _make_mock_audit()
        svc = _make_service(audit=audit)
        asyncio.get_event_loop().run_until_complete(
            svc.run_full_evaluation("exec-009", _BASE_ARTIFACTS)
        )
        audit.write.assert_called()


# ---------------------------------------------------------------------------
# EvaluatorService — minimum pass score constant
# ---------------------------------------------------------------------------

class TestConstants:
    def test_minimum_pass_score_is_90(self) -> None:
        """Threshold must be 90.0 per spec/configuration.yaml."""
        assert MINIMUM_PASS_SCORE == 90.0


# ---------------------------------------------------------------------------
# RegressionChecker — SE-001: recurring findings
# ---------------------------------------------------------------------------

def _make_spr(
    *,
    reviewer_finding_ids: list | None = None,
    passed_tests: int = 5,
    total_tests: int = 5,
    failed_test_ids: list | None = None,
) -> MagicMock:
    """Create a mock SkillPerformanceRecord."""
    rec = MagicMock(spec=SkillPerformanceRecord)
    rec.reviewer_finding_ids = reviewer_finding_ids or []
    rec.passed_tests = passed_tests
    rec.total_tests = total_tests
    rec.failed_test_ids = failed_test_ids or []
    rec.timestamp = datetime.now(timezone.utc)
    return rec


@asynccontextmanager
async def _session_with_records(records: list):
    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = records
    session.execute = AsyncMock(return_value=execute_result)
    yield session


class TestRegressionCheckerSE001:
    def test_se001_triggered_on_recurring(self) -> None:
        """Same finding_id in 3 of 5 records must trigger SE-001."""
        # "CC-001" appears in 3 of the 5 records
        records = [
            _make_spr(reviewer_finding_ids=["CC-001", "CC-004"]),  # latest
            _make_spr(reviewer_finding_ids=["CC-001"]),
            _make_spr(reviewer_finding_ids=["CC-001"]),
            _make_spr(reviewer_finding_ids=["CC-005"]),
            _make_spr(reviewer_finding_ids=["CC-003"]),
        ]

        async def factory():
            return _session_with_records(records)

        checker = RegressionChecker(factory)
        result = asyncio.get_event_loop().run_until_complete(
            checker.check_skill_triggers("statistics/t-test", "core")
        )
        assert "SE-001" in result

    def test_se001_not_triggered_below_threshold(self) -> None:
        """Finding appearing only 2 times must NOT trigger SE-001."""
        records = [
            _make_spr(reviewer_finding_ids=["CC-001"]),  # latest
            _make_spr(reviewer_finding_ids=["CC-001"]),
            _make_spr(reviewer_finding_ids=[]),
            _make_spr(reviewer_finding_ids=[]),
            _make_spr(reviewer_finding_ids=[]),
        ]

        async def factory():
            return _session_with_records(records)

        checker = RegressionChecker(factory)
        result = asyncio.get_event_loop().run_until_complete(
            checker.check_skill_triggers("statistics/t-test", "core")
        )
        assert "SE-001" not in result


# ---------------------------------------------------------------------------
# RegressionChecker — SE-002: low pass rate
# ---------------------------------------------------------------------------

class TestRegressionCheckerSE002:
    def test_se002_triggered_on_low_rate(self) -> None:
        """avg pass rate < 80% over 10 records must trigger SE-002."""
        # Each record: 3/5 = 60% pass rate (well below 80%)
        records = [
            _make_spr(passed_tests=3, total_tests=5)
            for _ in range(PASS_RATE_WINDOW)
        ]

        async def factory():
            return _session_with_records(records)

        checker = RegressionChecker(factory)
        result = asyncio.get_event_loop().run_until_complete(
            checker.check_skill_triggers("statistics/t-test", "core")
        )
        assert "SE-002" in result

    def test_se002_not_triggered_above_threshold(self) -> None:
        """avg pass rate >= 80% must NOT trigger SE-002."""
        records = [
            _make_spr(passed_tests=5, total_tests=5)  # 100%
            for _ in range(PASS_RATE_WINDOW)
        ]

        async def factory():
            return _session_with_records(records)

        checker = RegressionChecker(factory)
        result = asyncio.get_event_loop().run_until_complete(
            checker.check_skill_triggers("statistics/t-test", "core")
        )
        assert "SE-002" not in result


# ---------------------------------------------------------------------------
# RegressionChecker — SE-003: latest record has failed tests
# ---------------------------------------------------------------------------

class TestRegressionCheckerSE003:
    def test_se003_triggered_on_failed_tests(self) -> None:
        records = [
            _make_spr(failed_test_ids=["test_cc001", "test_cc003"]),  # latest
            _make_spr(failed_test_ids=[]),
        ]

        async def factory():
            return _session_with_records(records)

        checker = RegressionChecker(factory)
        result = asyncio.get_event_loop().run_until_complete(
            checker.check_skill_triggers("statistics/t-test", "core")
        )
        assert "SE-003" in result

    def test_se003_not_triggered_when_no_failures(self) -> None:
        records = [
            _make_spr(failed_test_ids=[]),  # latest
        ]

        async def factory():
            return _session_with_records(records)

        checker = RegressionChecker(factory)
        result = asyncio.get_event_loop().run_until_complete(
            checker.check_skill_triggers("statistics/t-test", "core")
        )
        assert "SE-003" not in result

    def test_empty_records_returns_no_triggers(self) -> None:
        async def factory():
            return _session_with_records([])

        checker = RegressionChecker(factory)
        result = asyncio.get_event_loop().run_until_complete(
            checker.check_skill_triggers("statistics/unknown", "core")
        )
        assert result == []
