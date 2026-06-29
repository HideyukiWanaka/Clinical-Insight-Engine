"""CIE Platform — Database layer.

Defines the SQLAlchemy 2.0 async engine, ORM table models, and helper
functions for session management.

All persistence is backed by SQLite via ``aiosqlite``, satisfying the
*Offline First* principle (PROJECT_RULES.md Section 3.4, AP-012).

Design decisions (PROJECT_RULES.md Section 14):
- Raw SQL is forbidden; all queries use SQLAlchemy ORM.
- Every column carries a Python type annotation.
- Business logic is intentionally absent (Phase 1 skeleton).
- The three tables defined here correspond directly to the storage
  concerns described in ``spec/configuration.yaml``:
  ``AuditLog``, ``WorkflowInstance``, and ``SkillPerformanceRecord``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from cie.core.config import CIEConfig


# ---------------------------------------------------------------------------
# ORM base
# ---------------------------------------------------------------------------


class _Base(DeclarativeBase):
    """Shared declarative base for all CIE ORM models."""


# ---------------------------------------------------------------------------
# Table models
# ---------------------------------------------------------------------------


class AuditLog(_Base):
    """Immutable audit log entry.

    Records every significant platform event.  Entries must never be
    updated or deleted (``spec/system.yaml audit_logging: enabled``).
    The ``payload_hash`` column stores a ``sha256:…`` digest of the
    event payload; the raw payload is **never** persisted.

    Attributes:
        id: Auto-generated UUID primary key.
        timestamp: UTC datetime when the event occurred.
        execution_id: Workflow / task execution context identifier.
        agent_id: Identifier of the agent that raised the event.
        action: Short machine-readable description of the action.
        status: Outcome of the action (e.g., ``"success"``, ``"failure"``).
        event_severity: One of ``"INFO"``, ``"WARNING"``, ``"CRITICAL"``,
            ``"BREACH"``.
        payload_hash: SHA-256 digest of the event payload in the form
            ``sha256:<hex>`` (71 characters total).
        created_at: UTC datetime when the row was inserted.
    """

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="UUID primary key (auto-generated)",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="UTC datetime when the event occurred",
    )
    execution_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="Workflow / task execution context identifier",
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Identifier of the agent that raised the event",
    )
    action: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        comment="Short machine-readable description of the action",
    )
    status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="Outcome of the action",
    )
    event_severity: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="INFO | WARNING | CRITICAL | BREACH",
    )
    payload_hash: Mapped[str | None] = mapped_column(
        String(71),
        nullable=True,
        comment="sha256:<hex> digest of the event payload (raw payload not stored)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC datetime when the row was inserted",
    )


class WorkflowInstance(_Base):
    """Persistent state of a single workflow execution.

    Each row tracks one end-to-end workflow run.  The
    ``workflow_selection_rule_id`` column records which deterministic
    rule (WS-001 to WS-004) was applied by the Orchestrator to choose
    the workflow (ADR-0001).

    Attributes:
        id: UUID primary key (set by the caller, not auto-generated).
        execution_id: Unique cross-component trace identifier.
        workflow_definition_id: Identifier of the static workflow
            definition (e.g., ``"clinical_analysis_standard"``).
        workflow_selection_rule_id: Rule applied to select this workflow
            (e.g., ``"WS-001"``).
        workflow_selection_justification: Human-readable explanation of
            why the rule was applied.
        current_state: Current state-machine state (e.g., ``"RUNNING"``,
            ``"COMPLETED"``, ``"FAILED"``).
        created_at: UTC datetime when the workflow instance was created.
        updated_at: UTC datetime of the last state transition.
        completed_at: UTC datetime when the workflow reached a terminal
            state.  ``None`` while the workflow is still running.
    """

    __tablename__ = "workflow_instance"

    __table_args__ = (
        UniqueConstraint("execution_id", name="uq_workflow_instance_execution_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        comment="UUID primary key",
    )
    execution_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="Unique cross-component trace identifier",
    )
    workflow_definition_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Identifier of the static workflow definition",
    )
    workflow_selection_rule_id: Mapped[str | None] = mapped_column(
        String(8),
        nullable=True,
        comment="Orchestrator rule applied to select this workflow (WS-001〜WS-004)",
    )
    workflow_selection_justification: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Human-readable explanation of why the rule was applied",
    )
    current_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Current state-machine state",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="UTC datetime when the workflow instance was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="UTC datetime of the last state transition",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC datetime when the workflow reached a terminal state",
    )


class SkillPerformanceRecord(_Base):
    """Skill evaluation performance record (ADR-0002).

    Records the outcome of each skill execution as part of the
    skill performance monitoring system introduced in ADR-0002.
    These records drive the SE-001 and SE-002 automated improvement
    triggers defined in ``spec/configuration.yaml``.

    Attributes:
        id: Auto-generated UUID primary key.
        skill_id: Fully-qualified skill identifier
            (e.g., ``"statistics/t-test"``).
        skill_namespace: Namespace of the skill: ``"core"`` or
            ``"user"``.
        skill_version: Version string extracted from the skill's
            ``SKILL.md`` header.
        execution_id: Cross-component trace identifier.
        workflow_id: Identifier of the parent workflow.
        total_tests: Number of test cases executed by the Reviewer.
        passed_tests: Number of test cases that passed.
        failed_test_ids: JSON array of failed test-case identifiers.
        reviewer_finding_ids: JSON array of finding identifiers raised
            by the Reviewer Agent.
        correctness_score: Correctness dimension score (0–100).
        statistical_score: Statistical validity dimension score (0–100).
        timestamp: UTC datetime when the record was created.
    """

    __tablename__ = "skill_performance_record"

    __table_args__ = (
        Index(
            "ix_skill_performance_record_skill_id",
            "skill_id",
        ),
        Index(
            "ix_skill_performance_record_execution_id",
            "execution_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="UUID primary key (auto-generated)",
    )
    skill_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Fully-qualified skill identifier",
    )
    skill_namespace: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="core | user",
    )
    skill_version: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="Version string from SKILL.md header",
    )
    execution_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        comment="Cross-component trace identifier",
    )
    workflow_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Identifier of the parent workflow",
    )
    total_tests: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of test cases executed",
    )
    passed_tests: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of test cases that passed",
    )
    failed_test_ids: Mapped[list[Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="JSON array of failed test-case identifiers",
    )
    reviewer_finding_ids: Mapped[list[Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="JSON array of finding identifiers raised by the Reviewer Agent",
    )
    correctness_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Correctness dimension score (0–100)",
    )
    statistical_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Statistical validity dimension score (0–100)",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="UTC datetime when the record was created",
    )


class SkillImprovementProposalRow(_Base):
    """Persisted SkillImprovementProposal (ADR-0002 Phase 2–3).

    One row per AI-generated improvement proposal.  Rows are INSERT-only
    until a human reviews them; status and human_decision columns are then
    updated exactly once.

    Attributes:
        id: Auto-generated UUID primary key.
        proposal_id: Application-level UUID used as the stable external key.
        generated_at: UTC datetime when the proposal was created.
        target_skill_id: Fully-qualified skill identifier (e.g. "statistics/t-test").
        target_namespace: ``"core"`` or ``"user"``.
        current_version: Version string of the Skill at proposal time.
        proposed_version: SemVer string after the proposed change is applied.
        trigger_id: ``"SE-001"`` – ``"SE-004"`` that triggered this proposal.
        trigger_evidence: JSON dict containing trigger evidence details.
        proposed_changes: JSON list of change descriptors (diff-style).
        human_review_required: Always ``True`` (ADR-0002 Principle 4).
        status: Current lifecycle state of the proposal.
        human_decision: JSON dict written when the proposal is reviewed.
        reviewed_at: UTC datetime when the human reviewed the proposal.
    """

    __tablename__ = "skill_improvement_proposal"

    __table_args__ = (
        Index("ix_skill_improvement_proposal_skill_id", "target_skill_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="UUID primary key (auto-generated)",
    )
    proposal_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        unique=True,
        comment="Application-level UUID for the proposal",
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="UTC datetime when the proposal was generated",
    )
    target_skill_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Fully-qualified skill identifier",
    )
    target_namespace: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="core | user",
    )
    current_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="Skill version at proposal time",
    )
    proposed_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="SemVer string after the proposed change",
    )
    trigger_id: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        comment="SE-001 | SE-002 | SE-003 | SE-004",
    )
    trigger_evidence: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="JSON evidence dict from RegressionChecker",
    )
    proposed_changes: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
        comment="JSON list of diff-style change descriptors",
    )
    human_review_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Always True per ADR-0002 Principle 4",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending_human_review",
        comment="pending_human_review | approved | rejected | archived",
    )
    human_decision: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="JSON dict written when the human reviews the proposal",
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC datetime when the human reviewed the proposal",
    )


# ---------------------------------------------------------------------------
# Engine and session helpers
# ---------------------------------------------------------------------------


async def get_engine(config: CIEConfig) -> AsyncEngine:
    """Create and return an async SQLAlchemy engine for the CIE database.

    The engine is backed by SQLite via ``aiosqlite``.  SQLite is the sole
    supported database driver, satisfying the *Offline First* constraint.

    Args:
        config: Validated :class:`~cie.core.config.CIEConfig` instance.
            The ``database_filepath`` field determines the database path.
            Use ``":memory:"`` (or configure it) for in-memory testing.

    Returns:
        A configured :class:`~sqlalchemy.ext.asyncio.AsyncEngine` instance.
        The engine is **not** connected until first use.

    Example:
        >>> config = CIEConfig(database_filepath=":memory:")
        >>> engine = await get_engine(config)
    """
    db_path = Path(config.database_filepath)
    if db_path != Path(":memory:"):
        db_path.parent.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite+aiosqlite:///{config.database_filepath}"
    engine: AsyncEngine = create_async_engine(
        db_url,
        echo=False,
        future=True,
        poolclass=NullPool,
    )
    return engine


async def init_db(engine: AsyncEngine) -> None:
    """Create all ORM-defined tables in the target database.

    Idempotent: existing tables are not dropped or modified.  Safe to
    call on every application start.

    Args:
        engine: An :class:`~sqlalchemy.ext.asyncio.AsyncEngine` obtained
            from :func:`get_engine`.

    Example:
        >>> await init_db(engine)
    """
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)


@asynccontextmanager
async def get_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that yields a database session.

    The session is automatically committed on clean exit and rolled back
    on exception.  The session is always closed on exit.

    Args:
        engine: An :class:`~sqlalchemy.ext.asyncio.AsyncEngine` obtained
            from :func:`get_engine`.

    Yields:
        An :class:`~sqlalchemy.ext.asyncio.AsyncSession` bound to the
        given engine.

    Raises:
        Exception: Any exception raised inside the ``async with`` block
            is re-raised after the session is rolled back and closed.

    Example:
        >>> async with get_session(engine) as session:
        ...     session.add(audit_log_entry)
    """
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


__all__: list[str] = [
    # Models
    "AuditLog",
    "WorkflowInstance",
    "SkillPerformanceRecord",
    "SkillImprovementProposalRow",
    # Helpers
    "get_engine",
    "init_db",
    "get_session",
]
