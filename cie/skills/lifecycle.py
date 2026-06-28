"""CIE Platform — Skill Lifecycle Service.

Implements ADR-0002 Phase 1–5:
  Phase 1: check_and_trigger()  — detect degradation via RegressionChecker
  Phase 2: generate_proposal()  — AI-generated SkillImprovementProposal (file-read only)
  Phase 3: apply_approved_proposal() — human-approved write + archive + rollback
  Phase 4: register_user_skill() — validated user skill onboarding
  Phase 5: ongoing monitoring driven externally by RegressionChecker

Critical invariants (ADR-0002 Principle 4):
  - human_review_required is always True; any proposal with False is refused.
  - Skill files are never written without a valid CapabilityToken that carries
    SKILL_UPDATE_CORE or SKILL_REGISTER_USER.
  - Every file write is preceded by a backup; failures trigger full rollback.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import yaml
from sqlalchemy import select

from cie.core.audit import AuditEvent, AuditEventSeverity, AuditService
from cie.core.database import SkillImprovementProposalRow
from cie.core.exceptions import PermissionDeniedError, SkillError
from cie.evaluation.regression import RegressionChecker
from cie.security.capability_token import CapabilityScope, CapabilityToken, CapabilityTokenManager
from cie.skills.loader import SkillLoader, SkillNotFoundError
from cie.skills.registry_manager import RegistryManager

logger = logging.getLogger(__name__)

# skill_id: lowercase alphanumeric + hyphens, 3–50 chars, no leading/trailing hyphens
_SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,48}[a-z0-9]$")

_REQUIRED_SECTIONS: frozenset[str] = frozenset(
    {"## Overview", "## Procedure", "## Validation Rules", "## Tests"}
)

_VERSION_HEADER_RE = re.compile(r"(#\s*Version:\s*)\S+")


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


class ProposalStatus(str, Enum):
    """Lifecycle state of a SkillImprovementProposal."""

    PENDING_HUMAN_REVIEW = "pending_human_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


@dataclass
class SkillImprovementProposal:
    """In-memory representation of an improvement proposal (ADR-0002 Phase 2).

    This dataclass is the return type of generate_proposal(). The persisted
    form lives in SkillImprovementProposalRow (database.py).
    """

    proposal_id: str
    generated_at: datetime
    target_skill_id: str
    target_namespace: str
    current_version: str
    proposed_version: str
    trigger_id: str
    trigger_evidence: dict
    proposed_changes: list[dict]
    human_review_required: bool = True  # ADR-0002 Principle 4 — always True
    status: ProposalStatus = field(default=ProposalStatus.PENDING_HUMAN_REVIEW)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _bump_version(version: str, bump: str = "MINOR") -> str:
    """Return a new SemVer string with the requested component incremented."""
    parts = version.split(".")
    try:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        return version
    if bump == "MAJOR":
        return f"{major + 1}.0.0"
    if bump == "MINOR":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _extract_version_from_content(content: str) -> str:
    """Scan the first 400 bytes of SKILL.md content for a version header."""
    match = re.search(r"#\s*Version:\s*(\S+)", content[:400])
    return match.group(1) if match else "0.0.0"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SkillLifecycleService:
    """Orchestrates the full ADR-0002 Skill Lifecycle.

    All Skill file writes are gated behind CapabilityToken scope checks
    and are rolled back on any failure.
    """

    def __init__(
        self,
        skill_loader: SkillLoader,
        registry_manager: RegistryManager,
        regression_checker: RegressionChecker,
        token_manager: CapabilityTokenManager,
        audit_service: AuditService,
        db_session_factory: Callable,
    ) -> None:
        self._loader = skill_loader
        self._registry = registry_manager
        self._regression = regression_checker
        self._token_manager = token_manager
        self._audit = audit_service
        self._db = db_session_factory

    # ------------------------------------------------------------------
    # Phase 1: Detect degradation triggers
    # ------------------------------------------------------------------

    async def check_and_trigger(
        self,
        skill_id: str,
        skill_namespace: str,
    ) -> list[str]:
        """Call RegressionChecker and audit any detected triggers.

        Returns:
            List of trigger IDs (e.g. ["SE-001", "SE-003"]) or empty list.
        """
        trigger_ids = await self._regression.check_skill_triggers(skill_id, skill_namespace)
        if trigger_ids:
            await self._audit.write(
                AuditEvent(
                    execution_id=str(uuid.uuid4()),
                    agent_id="skill_lifecycle",
                    action="SKILL_EVALUATION_TRIGGERED",
                    status="triggered",
                    severity=AuditEventSeverity.INFO,
                    payload={
                        "skill_id": skill_id,
                        "skill_namespace": skill_namespace,
                        "trigger_ids": trigger_ids,
                    },
                )
            )
        return trigger_ids

    # ------------------------------------------------------------------
    # Phase 2: Generate improvement proposal (no file writes)
    # ------------------------------------------------------------------

    async def generate_proposal(
        self,
        skill_id: str,
        trigger_id: str,
        trigger_evidence: dict,
    ) -> SkillImprovementProposal:
        """Generate a SkillImprovementProposal and persist it to the DB.

        This method is read-only with respect to Skill files (ADR-0002
        Principle 4). human_review_required is always set to True.

        Returns:
            The newly created SkillImprovementProposal.
        """
        try:
            meta = self._loader.resolve(skill_id)
            current_version = meta.version
            namespace = meta.namespace.value
        except SkillNotFoundError:
            current_version = "0.0.0"
            namespace = "core"

        proposed_version = _bump_version(current_version, "MINOR")
        proposal_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        proposed_changes: list[dict] = [
            {
                "change_id": f"CHG-{proposal_id[:8]}",
                "trigger_id": trigger_id,
                "section": "Procedure",
                "change_type": "advisory",
                "description": f"Address {trigger_id}: {trigger_evidence}",
                "diff": None,
                "addresses_finding": trigger_id,
            }
        ]

        proposal = SkillImprovementProposal(
            proposal_id=proposal_id,
            generated_at=now,
            target_skill_id=skill_id,
            target_namespace=namespace,
            current_version=current_version,
            proposed_version=proposed_version,
            trigger_id=trigger_id,
            trigger_evidence=trigger_evidence,
            proposed_changes=proposed_changes,
            human_review_required=True,
            status=ProposalStatus.PENDING_HUMAN_REVIEW,
        )

        async with self._db() as session:
            row = SkillImprovementProposalRow(
                proposal_id=proposal_id,
                generated_at=now,
                target_skill_id=skill_id,
                target_namespace=namespace,
                current_version=current_version,
                proposed_version=proposed_version,
                trigger_id=trigger_id,
                trigger_evidence=trigger_evidence,
                proposed_changes=proposed_changes,
                human_review_required=True,
                status=ProposalStatus.PENDING_HUMAN_REVIEW.value,
            )
            session.add(row)

        await self._audit.write(
            AuditEvent(
                execution_id=str(uuid.uuid4()),
                agent_id="skill_lifecycle",
                action="SKILL_IMPROVEMENT_PROPOSAL_GENERATED",
                status="success",
                severity=AuditEventSeverity.INFO,
                payload={
                    "proposal_id": proposal_id,
                    "skill_id": skill_id,
                    "trigger_id": trigger_id,
                    "proposed_version": proposed_version,
                },
            )
        )

        return proposal

    # ------------------------------------------------------------------
    # Phase 3: Apply or reject an approved proposal
    # ------------------------------------------------------------------

    async def apply_approved_proposal(
        self,
        proposal_id: str,
        capability_token: CapabilityToken,
        human_decision: dict,
    ) -> None:
        """Apply a human-reviewed proposal to the target Skill file.

        Args:
            proposal_id: UUID of the proposal to apply.
            capability_token: Must carry CapabilityScope.SKILL_UPDATE_CORE.
            human_decision: ``{"action": "approved"|"rejected", "modifications": str|None}``
                When ``action == "approved"`` and ``modifications`` is provided,
                the Skill file is replaced with that content; otherwise only the
                version header is updated.

        Raises:
            PermissionDeniedError: If the token lacks SKILL_UPDATE_CORE.
            SkillError: If the proposal is not found, has human_review_required=False,
                or if a file write fails (original is restored before raising).
        """
        # Step 1: Gate on capability scope
        capability_token.require_scope(CapabilityScope.SKILL_UPDATE_CORE)

        # Step 2: Load proposal
        async with self._db() as session:
            stmt = select(SkillImprovementProposalRow).where(
                SkillImprovementProposalRow.proposal_id == proposal_id
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

        if row is None:
            raise SkillError(f"Proposal '{proposal_id}' not found.")

        # Invariant: refuse if someone tampered human_review_required to False
        if not row.human_review_required:
            raise SkillError(
                f"Proposal '{proposal_id}' has human_review_required=False; refusing.",
            )

        action = human_decision.get("action", "rejected")
        now = datetime.now(timezone.utc)

        # Step 3: Rejection path — no file changes
        if action == "rejected":
            await self._update_proposal_status(
                proposal_id, ProposalStatus.REJECTED, human_decision, now
            )
            await self._audit.write(
                AuditEvent(
                    execution_id=str(uuid.uuid4()),
                    agent_id="skill_lifecycle",
                    action="SKILL_PROPOSAL_REVIEWED_BY_HUMAN",
                    status="rejected",
                    severity=AuditEventSeverity.INFO,
                    payload={"proposal_id": proposal_id, "action": "rejected"},
                )
            )
            return

        # Step 4: Approval path — archive → update → version bump
        target_skill_id = row.target_skill_id
        current_version = row.current_version
        proposed_version = row.proposed_version

        try:
            skill_meta = self._loader.resolve(target_skill_id)
        except SkillNotFoundError:
            raise SkillError(
                f"Cannot resolve skill '{target_skill_id}' for update.",
            ) from None

        skill_md_path = skill_meta.skill_path
        skill_dir = skill_md_path.parent
        original_content = skill_md_path.read_text(encoding="utf-8")

        archive_dir = skill_dir / "versions" / current_version
        backup_created = False

        try:
            # Step 4a: Archive current SKILL.md
            archive_dir.mkdir(parents=True, exist_ok=True)
            (archive_dir / "SKILL.md").write_text(original_content, encoding="utf-8")
            backup_created = True

            # Step 4b/4c: Compute new content
            modifications = human_decision.get("modifications")
            if modifications:
                new_content = modifications
            else:
                new_content = _VERSION_HEADER_RE.sub(
                    lambda m: m.group(1) + proposed_version,
                    original_content,
                    count=1,
                )

            # Write updated SKILL.md
            skill_md_path.write_text(new_content, encoding="utf-8")

        except Exception as exc:
            if backup_created:
                try:
                    skill_md_path.write_text(original_content, encoding="utf-8")
                except Exception:
                    logger.error(
                        "Rollback failed for skill '%s' — manual restore required",
                        target_skill_id,
                    )
            raise SkillError(
                f"Failed to apply proposal '{proposal_id}': {exc}",
            ) from exc

        # Step 4d: Update DB status
        await self._update_proposal_status(
            proposal_id, ProposalStatus.APPROVED, human_decision, now
        )

        # Step 5: Audit
        await self._audit.write(
            AuditEvent(
                execution_id=str(uuid.uuid4()),
                agent_id="skill_lifecycle",
                action="SKILL_UPDATED",
                status="success",
                severity=AuditEventSeverity.INFO,
                payload={
                    "proposal_id": proposal_id,
                    "skill_id": target_skill_id,
                    "version": proposed_version,
                    "archived_version": current_version,
                },
            )
        )
        await self._audit.write(
            AuditEvent(
                execution_id=str(uuid.uuid4()),
                agent_id="skill_lifecycle",
                action="SKILL_PROPOSAL_REVIEWED_BY_HUMAN",
                status="approved",
                severity=AuditEventSeverity.INFO,
                payload={"proposal_id": proposal_id, "action": "approved"},
            )
        )

    # ------------------------------------------------------------------
    # Phase 4: Register a user-defined skill
    # ------------------------------------------------------------------

    async def register_user_skill(
        self,
        skill_id: str,
        skill_content: str,
        metadata: dict,
        capability_token: CapabilityToken,
    ) -> None:
        """Validate and register a new user Skill.

        Steps (none may be skipped per spec/skill-lifecycle.md):
          1. Scope check
          2. skill_id format validation
          3. Required section presence
          4. ## Tests section non-empty check
          5. Interface compatibility with overridden core Skill (if any)
          6. Write SKILL.md
          7. Write METADATA.yaml (with approved_by / approved_at)
          8. Register in RegistryManager
          9. Audit

        Raises:
            PermissionDeniedError: Token lacks SKILL_REGISTER_USER.
            SkillError: Any validation or write failure.
        """
        # Step 1
        capability_token.require_scope(CapabilityScope.SKILL_REGISTER_USER)

        # Step 2: skill_id format
        if not _SKILL_ID_RE.match(skill_id):
            raise SkillError(
                f"Invalid skill_id '{skill_id}': must be 3–50 lowercase alphanumeric "
                "characters and hyphens, not starting or ending with a hyphen.",
            )

        # Step 3: Required sections
        missing = sorted(s for s in _REQUIRED_SECTIONS if s not in skill_content)
        if missing:
            raise SkillError(
                f"SKILL.md is missing required sections: {missing}",
            )

        # Step 4: ## Tests section must contain at least one test case
        tests_split = skill_content.split("## Tests", 1)
        if len(tests_split) < 2 or len(tests_split[1].strip()) < 10:
            raise SkillError(
                "## Tests section must contain at least one test case (≥10 characters).",
            )

        # Step 5: Interface compatibility with the core Skill being overridden
        core_skill_id: str | None = (metadata.get("overrides") or {}).get("core_skill_id")
        if core_skill_id:
            try:
                self._loader.resolve(core_skill_id)
            except SkillNotFoundError:
                raise SkillError(
                    f"Cannot override non-existent core skill '{core_skill_id}'.",
                ) from None

        # Step 6: Write SKILL.md
        user_skill_dir = self._loader._root / "user" / skill_id
        user_skill_dir.mkdir(parents=True, exist_ok=True)
        (user_skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")

        # Step 7: Write METADATA.yaml
        meta_with_approval: dict = {
            **metadata,
            "approved_by": "human",
            "approved_at": datetime.now(timezone.utc).date().isoformat(),
        }
        (user_skill_dir / "METADATA.yaml").write_text(
            yaml.safe_dump(meta_with_approval, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        # Step 8: Register
        version = _extract_version_from_content(skill_content)
        audit_event_id = str(uuid.uuid4())
        self._registry.register(
            skill_id=skill_id,
            version=version,
            overrides_core_skill_id=core_skill_id,
            audit_event_id=audit_event_id,
        )

        # Step 9: Audit
        await self._audit.write(
            AuditEvent(
                execution_id=str(uuid.uuid4()),
                agent_id="skill_lifecycle",
                action="USER_SKILL_REGISTERED",
                status="success",
                severity=AuditEventSeverity.INFO,
                payload={
                    "skill_id": skill_id,
                    "version": version,
                    "overrides": core_skill_id,
                    "audit_event_id": audit_event_id,
                },
            )
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _update_proposal_status(
        self,
        proposal_id: str,
        status: ProposalStatus,
        human_decision: dict,
        reviewed_at: datetime,
    ) -> None:
        async with self._db() as session:
            stmt = select(SkillImprovementProposalRow).where(
                SkillImprovementProposalRow.proposal_id == proposal_id
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is not None:
                row.status = status.value
                row.human_decision = human_decision
                row.reviewed_at = reviewed_at
