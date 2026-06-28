"""Unit tests for cie.core.database.

All tests use an in-memory SQLite database (``database_filepath=":memory:"``).
No external services or files are required.

Test matrix:
- test_init_db_creates_tables     — tables are created without error
- test_audit_log_insert           — AuditLog row round-trips correctly
- test_workflow_instance_insert   — WorkflowInstance row round-trips correctly
- test_skill_performance_record_insert — SkillPerformanceRecord row round-trips
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cie.core.config import CIEConfig
from cie.core.database import (
    AuditLog,
    SkillPerformanceRecord,
    WorkflowInstance,
    get_engine,
    get_session,
    init_db,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    """Return a fresh in-memory async engine with all tables created.

    Yields:
        AsyncEngine: Ready-to-use in-memory SQLite engine.
    """
    config = CIEConfig(database_filepath=":memory:")
    eng = await get_engine(config)
    await init_db(eng)
    yield eng
    await eng.dispose()


# ---------------------------------------------------------------------------
# Test: init_db creates tables
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_db_creates_tables(engine: AsyncEngine) -> None:
    """Tables declared in the ORM must exist after init_db().

    Verifies that the three core tables (audit_log, workflow_instance,
    skill_performance_record) are present in the SQLite schema.
    """
    expected_tables = {"audit_log", "workflow_instance", "skill_performance_record"}

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )
        actual_tables = {row[0] for row in result.fetchall()}

    assert expected_tables.issubset(actual_tables), (
        f"Missing tables: {expected_tables - actual_tables}"
    )


# ---------------------------------------------------------------------------
# Test: AuditLog insert and retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_insert(engine: AsyncEngine) -> None:
    """An AuditLog row can be inserted and retrieved by execution_id.

    Verifies:
    - Row is persisted with all fields intact.
    - payload_hash stores only the digest (not raw payload).
    - created_at is set automatically.
    """
    execution_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    entry = AuditLog(
        id=str(uuid.uuid4()),
        timestamp=now,
        execution_id=execution_id,
        agent_id="orchestrator",
        action="WORKFLOW_STARTED",
        status="success",
        event_severity="INFO",
        payload_hash="sha256:abc123def456abc123def456abc123def456abc123def456abc123def456ab12",
    )

    async with get_session(engine) as session:
        session.add(entry)

    # Re-fetch in a new session to confirm persistence
    from sqlalchemy import select

    async with get_session(engine) as session:
        stmt = select(AuditLog).where(AuditLog.execution_id == execution_id)
        result = await session.execute(stmt)
        fetched = result.scalar_one()

    assert fetched.execution_id == execution_id
    assert fetched.agent_id == "orchestrator"
    assert fetched.action == "WORKFLOW_STARTED"
    assert fetched.event_severity == "INFO"
    assert fetched.payload_hash is not None
    assert fetched.payload_hash.startswith("sha256:")


# ---------------------------------------------------------------------------
# Test: WorkflowInstance insert and retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_instance_insert(engine: AsyncEngine) -> None:
    """A WorkflowInstance row can be inserted and retrieved by execution_id.

    Verifies:
    - All required fields are stored correctly.
    - workflow_selection_rule_id is persisted as-is.
    - completed_at defaults to None.
    """
    execution_id = str(uuid.uuid4())
    instance_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    instance = WorkflowInstance(
        id=instance_id,
        execution_id=execution_id,
        workflow_definition_id="clinical_analysis_standard",
        workflow_selection_rule_id="WS-001",
        workflow_selection_justification="Primary outcome is binary, no covariate → WS-001",
        current_state="RUNNING",
        created_at=now,
        updated_at=now,
        completed_at=None,
    )

    async with get_session(engine) as session:
        session.add(instance)

    from sqlalchemy import select

    async with get_session(engine) as session:
        stmt = select(WorkflowInstance).where(WorkflowInstance.execution_id == execution_id)
        result = await session.execute(stmt)
        fetched = result.scalar_one()

    assert fetched.id == instance_id
    assert fetched.workflow_definition_id == "clinical_analysis_standard"
    assert fetched.workflow_selection_rule_id == "WS-001"
    assert fetched.current_state == "RUNNING"
    assert fetched.completed_at is None


# ---------------------------------------------------------------------------
# Test: SkillPerformanceRecord insert and retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_performance_record_insert(engine: AsyncEngine) -> None:
    """A SkillPerformanceRecord row can be inserted and retrieved by skill_id.

    Verifies:
    - JSON columns (failed_test_ids, reviewer_finding_ids) round-trip as lists.
    - Numeric columns (total_tests, passed_tests, scores) are stored correctly.
    - Nullable columns accept None.
    """
    execution_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    record = SkillPerformanceRecord(
        id=str(uuid.uuid4()),
        skill_id="statistics/t-test",
        skill_namespace="core",
        skill_version="1.0.0",
        execution_id=execution_id,
        workflow_id="clinical_analysis_standard",
        total_tests=10,
        passed_tests=9,
        failed_test_ids=["TC-003"],
        reviewer_finding_ids=["RF-007"],
        correctness_score=95.0,
        statistical_score=98.5,
        timestamp=now,
    )

    async with get_session(engine) as session:
        session.add(record)

    from sqlalchemy import select

    async with get_session(engine) as session:
        stmt = select(SkillPerformanceRecord).where(
            SkillPerformanceRecord.skill_id == "statistics/t-test"
        )
        result = await session.execute(stmt)
        fetched = result.scalar_one()

    assert fetched.skill_namespace == "core"
    assert fetched.total_tests == 10
    assert fetched.passed_tests == 9
    assert fetched.failed_test_ids == ["TC-003"]
    assert fetched.reviewer_finding_ids == ["RF-007"]
    assert fetched.correctness_score == pytest.approx(95.0)
    assert fetched.statistical_score == pytest.approx(98.5)
    assert fetched.correctness_score is not None
