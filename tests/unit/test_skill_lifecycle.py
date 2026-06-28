"""Unit tests for SkillLifecycleService (ADR-0002 Phase 1–4)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from cie.core.audit import AuditService
from cie.core.config import CIEConfig
from cie.core.database import get_engine, get_session, init_db
from cie.core.exceptions import PermissionDeniedError, SkillError
from cie.security.capability_token import CapabilityScope, CapabilityToken
from cie.skills.lifecycle import ProposalStatus, SkillImprovementProposal, SkillLifecycleService
from cie.skills.loader import SkillLoader
from cie.skills.registry_manager import RegistryManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    config = CIEConfig(database_filepath=":memory:")
    eng = await get_engine(config)
    await init_db(eng)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine):
    return lambda: get_session(engine)


@pytest.fixture
def audit_service(session_factory) -> AuditService:
    return AuditService(session_factory)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(scopes: set[CapabilityScope]) -> CapabilityToken:
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=str(uuid.uuid4()),
        bound_agent_id="skill_lifecycle",
        bound_step_id="test-step",
        granted_scopes=frozenset(scopes),
        denied_scopes=frozenset(),
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


def _make_service(
    tmp_path: Path,
    session_factory,
    audit_service: AuditService,
) -> SkillLifecycleService:
    skills_root = tmp_path / "skills"
    skills_root.mkdir(exist_ok=True)
    loader = SkillLoader(skills_root)
    registry = RegistryManager(tmp_path / "REGISTRY.yaml")
    regression = MagicMock()
    regression.check_skill_triggers = AsyncMock(return_value=[])
    token_manager = MagicMock()
    return SkillLifecycleService(
        skill_loader=loader,
        registry_manager=registry,
        regression_checker=regression,
        token_manager=token_manager,
        audit_service=audit_service,
        db_session_factory=session_factory,
    )


def _write_skill_md(path: Path, version: str = "1.0.0") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Version: {version}\n\n## Description\nTest skill.\n",
        encoding="utf-8",
    )


_VALID_SKILL_CONTENT = """\
# Version: 0.1.0

## Overview
A test user skill.

## Procedure
Step 1: do something.

## Validation Rules
Rule 1: output must be non-empty.

## Tests
### TEST-USR01
assert result is not None
"""


# ---------------------------------------------------------------------------
# Phase 2: generate_proposal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proposal_always_requires_human(
    tmp_path: Path,
    session_factory,
    audit_service: AuditService,
) -> None:
    """human_review_required must always be True (ADR-0002 Principle 4)."""
    svc = _make_service(tmp_path, session_factory, audit_service)
    proposal = await svc.generate_proposal(
        "statistics/t-test", "SE-001", {"CC-001": 3}
    )
    assert isinstance(proposal, SkillImprovementProposal)
    assert proposal.human_review_required is True
    assert proposal.status == ProposalStatus.PENDING_HUMAN_REVIEW


# ---------------------------------------------------------------------------
# Phase 3: apply_approved_proposal — scope check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_requires_scope(
    tmp_path: Path,
    session_factory,
    audit_service: AuditService,
) -> None:
    """Calling apply_approved_proposal without SKILL_UPDATE_CORE must raise PermissionDeniedError."""
    svc = _make_service(tmp_path, session_factory, audit_service)
    token = _make_token({CapabilityScope.AUDIT_WRITE_ENTRY})  # missing SKILL_UPDATE_CORE

    with pytest.raises(PermissionDeniedError):
        await svc.apply_approved_proposal(
            "any-id", token, {"action": "approved"}
        )


# ---------------------------------------------------------------------------
# Phase 3: apply_approved_proposal — archive before update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_before_update(
    tmp_path: Path,
    session_factory,
    audit_service: AuditService,
) -> None:
    """Current SKILL.md must be archived under versions/{current_version}/ before update."""
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "core" / "statistics" / "t-test"
    skill_dir.mkdir(parents=True, exist_ok=True)
    original = "# Version: 1.0.0\n\n## Description\nOriginal content.\n"
    (skill_dir / "SKILL.md").write_text(original, encoding="utf-8")

    svc = _make_service(tmp_path, session_factory, audit_service)
    proposal = await svc.generate_proposal(
        "statistics/t-test", "SE-001", {"CC-001": 3}
    )

    token = _make_token({CapabilityScope.SKILL_UPDATE_CORE})
    await svc.apply_approved_proposal(
        proposal.proposal_id, token, {"action": "approved"}
    )

    archive_path = skill_dir / "versions" / "1.0.0" / "SKILL.md"
    assert archive_path.is_file(), "Archive must be created before the update"
    assert archive_path.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# Phase 3: apply_approved_proposal — rollback on write failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_on_write_failure(
    tmp_path: Path,
    session_factory,
    audit_service: AuditService,
) -> None:
    """If writing the new SKILL.md fails, the original content must be restored."""
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "core" / "statistics" / "t-test"
    skill_dir.mkdir(parents=True, exist_ok=True)
    original = "# Version: 1.0.0\n\n## Description\nOriginal content.\n"
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(original, encoding="utf-8")

    svc = _make_service(tmp_path, session_factory, audit_service)
    proposal = await svc.generate_proposal(
        "statistics/t-test", "SE-001", {"CC-001": 3}
    )

    token = _make_token({CapabilityScope.SKILL_UPDATE_CORE})

    writes_to_skill_md = 0
    original_write = Path.write_text

    def patched_write(self: Path, data: str, *args, **kwargs):
        nonlocal writes_to_skill_md
        if self == skill_md:
            writes_to_skill_md += 1
            if writes_to_skill_md == 1:
                raise OSError("Simulated disk failure on update write")
        return original_write(self, data, *args, **kwargs)

    with patch.object(Path, "write_text", patched_write):
        with pytest.raises(SkillError):
            await svc.apply_approved_proposal(
                proposal.proposal_id, token, {"action": "approved"}
            )

    assert skill_md.read_text(encoding="utf-8") == original, (
        "Original SKILL.md content must be restored after write failure"
    )


# ---------------------------------------------------------------------------
# Phase 3: apply_approved_proposal — rejected proposal leaves files unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_proposal_not_applied(
    tmp_path: Path,
    session_factory,
    audit_service: AuditService,
) -> None:
    """Rejecting a proposal must leave SKILL.md and versions/ directory unchanged."""
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "core" / "statistics" / "t-test"
    skill_dir.mkdir(parents=True, exist_ok=True)
    original = "# Version: 1.0.0\n\n## Description\nOriginal content.\n"
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(original, encoding="utf-8")

    svc = _make_service(tmp_path, session_factory, audit_service)
    proposal = await svc.generate_proposal(
        "statistics/t-test", "SE-001", {"CC-001": 3}
    )

    token = _make_token({CapabilityScope.SKILL_UPDATE_CORE})
    await svc.apply_approved_proposal(
        proposal.proposal_id, token, {"action": "rejected"}
    )

    assert skill_md.read_text(encoding="utf-8") == original, "SKILL.md must be unchanged"
    assert not (skill_dir / "versions").exists(), "No archive must be created on rejection"


# ---------------------------------------------------------------------------
# Phase 4: register_user_skill — section validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_user_skill_validates_sections(
    tmp_path: Path,
    session_factory,
    audit_service: AuditService,
) -> None:
    """SKILL.md missing any of the four required sections must raise SkillError."""
    svc = _make_service(tmp_path, session_factory, audit_service)
    token = _make_token({CapabilityScope.SKILL_REGISTER_USER})

    # Missing "## Procedure"
    incomplete = (
        "# Version: 0.1.0\n\n"
        "## Overview\nSome overview.\n\n"
        "## Validation Rules\nSome rules.\n\n"
        "## Tests\nSome test content here.\n"
    )

    with pytest.raises(SkillError):
        await svc.register_user_skill("my-skill", incomplete, {}, token)


# ---------------------------------------------------------------------------
# Phase 4: register_user_skill — scope check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_requires_scope(
    tmp_path: Path,
    session_factory,
    audit_service: AuditService,
) -> None:
    """register_user_skill without SKILL_REGISTER_USER must raise PermissionDeniedError."""
    svc = _make_service(tmp_path, session_factory, audit_service)
    token = _make_token({CapabilityScope.AUDIT_WRITE_ENTRY})  # missing SKILL_REGISTER_USER

    with pytest.raises(PermissionDeniedError):
        await svc.register_user_skill("my-skill", _VALID_SKILL_CONTENT, {}, token)


# ---------------------------------------------------------------------------
# Phase 4: register_user_skill — skill_id format validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_id_format_validated(
    tmp_path: Path,
    session_factory,
    audit_service: AuditService,
) -> None:
    """Skill IDs with uppercase letters or underscores must raise SkillError."""
    svc = _make_service(tmp_path, session_factory, audit_service)
    token = _make_token({CapabilityScope.SKILL_REGISTER_USER})

    for invalid_id in ("My_Invalid", "UPPER", "has space", "ab", "a"):
        with pytest.raises(SkillError, match="Invalid skill_id"):
            await svc.register_user_skill(invalid_id, _VALID_SKILL_CONTENT, {}, token)


# ---------------------------------------------------------------------------
# Phase 4: register_user_skill — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_user_skill_happy_path(
    tmp_path: Path,
    session_factory,
    audit_service: AuditService,
) -> None:
    """A valid user skill must be written to disk and registered in REGISTRY.yaml."""
    svc = _make_service(tmp_path, session_factory, audit_service)
    token = _make_token({CapabilityScope.SKILL_REGISTER_USER})

    await svc.register_user_skill("my-skill", _VALID_SKILL_CONTENT, {}, token)

    skill_md = tmp_path / "skills" / "user" / "my-skill" / "SKILL.md"
    assert skill_md.is_file()
    assert skill_md.read_text(encoding="utf-8") == _VALID_SKILL_CONTENT

    registry = RegistryManager(tmp_path / "REGISTRY.yaml")
    entry = registry.get("my-skill")
    assert entry is not None
    assert entry["status"] == "active"
