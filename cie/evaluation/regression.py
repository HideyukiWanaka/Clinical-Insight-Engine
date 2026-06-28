"""CIE Platform — Regression Checker & Skill Performance Monitor.

Implements:
  - RegressionChecker: Reads skill_performance_record table and detects
    degradation triggers SE-001 and SE-002 (regression.yaml
    §skill_performance_monitoring + spec/configuration.yaml).
  - SE-003: Any failed_test_ids in the latest record triggers SE-003.

Architecture constraints:
  - RegressionChecker is read-only: never modifies Skill files.
  - All thresholds come from regression.yaml §skill_performance_monitoring
    and spec/configuration.yaml §skill_performance_gateways.
  - DB access is via session_factory (aiosqlite / SQLAlchemy async).
"""

from __future__ import annotations

from collections import Counter
from typing import Callable

from sqlalchemy import select

from cie.core.database import SkillPerformanceRecord

# ---------------------------------------------------------------------------
# Constants (regression.yaml §skill_performance_monitoring + configuration.yaml)
# ---------------------------------------------------------------------------

RECURRING_FINDING_WINDOW: int = 5       # last N records to inspect
RECURRING_FINDING_THRESHOLD: int = 3   # finding_id must appear >= this many times

PASS_RATE_WINDOW: int = 10              # last N records for pass rate
PASS_RATE_THRESHOLD: float = 0.80      # avg pass rate must be >= this


class RegressionChecker:
    """Detects skill performance degradation and returns trigger IDs.

    Trigger IDs (regression.yaml §skill_performance_monitoring):
      SE-001: Same finding_id appears >= 3 of the last 5 executions.
      SE-002: Average test pass rate < 80% over the last 10 executions.
      SE-003: The most recent record contains non-empty failed_test_ids.

    This class is read-only and never modifies Skill files or DB records.
    """

    def __init__(self, db_session_factory: Callable) -> None:
        """Initialise RegressionChecker.

        Args:
            db_session_factory: Zero-argument callable that returns an async
                SQLAlchemy session context manager.
        """
        self._session_factory = db_session_factory

    async def check_skill_triggers(
        self,
        skill_id: str,
        skill_namespace: str,
    ) -> list[str]:
        """Evaluate degradation triggers for a given skill.

        Queries the skill_performance_record table (cie_database.db) for
        recent records matching skill_id + skill_namespace.

        Args:
            skill_id: Fully-qualified skill identifier (e.g. "statistics/t-test").
            skill_namespace: "core" or "user".

        Returns:
            List of triggered trigger IDs. Empty list means no degradation.
            Example: ["SE-001", "SE-003"]
        """
        triggered: list[str] = []

        async with self._session_factory() as session:
            # Fetch last max(RECURRING_FINDING_WINDOW, PASS_RATE_WINDOW) records
            # ordered newest first, so we can slice as needed.
            fetch_limit = max(RECURRING_FINDING_WINDOW, PASS_RATE_WINDOW)

            stmt = (
                select(SkillPerformanceRecord)
                .where(SkillPerformanceRecord.skill_id == skill_id)
                .where(SkillPerformanceRecord.skill_namespace == skill_namespace)
                .order_by(SkillPerformanceRecord.timestamp.desc())
                .limit(fetch_limit)
            )
            result = await session.execute(stmt)
            records: list[SkillPerformanceRecord] = list(result.scalars().all())

        if not records:
            return triggered

        # --- SE-001: recurring finding trigger ---
        window_records = records[:RECURRING_FINDING_WINDOW]
        finding_counter: Counter[str] = Counter()
        for rec in window_records:
            finding_ids: list = rec.reviewer_finding_ids or []
            for fid in finding_ids:
                finding_counter[fid] += 1

        recurring = [
            fid
            for fid, count in finding_counter.items()
            if count >= RECURRING_FINDING_THRESHOLD
        ]
        if recurring:
            triggered.append("SE-001")

        # --- SE-002: low pass rate trigger ---
        rate_records = records[:PASS_RATE_WINDOW]
        pass_rates: list[float] = []
        for rec in rate_records:
            total = rec.total_tests or 0
            passed = rec.passed_tests or 0
            if total > 0:
                pass_rates.append(passed / total)

        if pass_rates:
            avg_rate = sum(pass_rates) / len(pass_rates)
            if avg_rate < PASS_RATE_THRESHOLD:
                triggered.append("SE-002")

        # --- SE-003: latest record has failed tests ---
        latest = records[0]
        failed_ids: list = latest.failed_test_ids or []
        if failed_ids:
            triggered.append("SE-003")

        return triggered
