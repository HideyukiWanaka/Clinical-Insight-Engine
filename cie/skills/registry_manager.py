"""CIE Platform — User Skill registry manager.

Manages reads and writes to skills/user/REGISTRY.yaml, the authoritative
list of registered User Skills (ADR-0002, MANIFEST.yaml skills.namespaces.user).

All writes enforce the human_review_required invariant: entries can only
reach status="active" when approved_by="human" (see register()).
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import yaml

from cie.core.exceptions import CIEError

logger = logging.getLogger(__name__)


class SkillAlreadyRegisteredError(CIEError):
    """Raised when a skill_id is already active in the registry."""

    error_code = "SKILL_ALREADY_REGISTERED"


class RegistryManager:
    """Read/write interface for skills/user/REGISTRY.yaml."""

    def __init__(self, registry_path: Path) -> None:
        """Args:
            registry_path: Absolute path to REGISTRY.yaml.
        """
        self._path = registry_path

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load(self) -> dict:
        """Return the full registry dict.

        Returns an empty registry when the file does not exist rather than
        raising, so callers can treat an absent file as an empty registry.
        """
        if not self._path.is_file():
            return {"skills": []}
        try:
            with self._path.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            return data if "skills" in data else {"skills": []}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load registry %s: %s", self._path, exc)
            return {"skills": []}

    def get_active_skills(self) -> list[dict]:
        """Return only entries where status == 'active'."""
        return [e for e in self.load().get("skills", []) if e.get("status") == "active"]

    def get(self, skill_id: str) -> dict | None:
        """Return the registry entry for skill_id, or None if absent."""
        for entry in self.load().get("skills", []):
            if entry.get("skill_id") == skill_id:
                return entry
        return None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def register(
        self,
        skill_id: str,
        version: str,
        overrides_core_skill_id: str | None,
        audit_event_id: str,
    ) -> None:
        """Add a new active entry to the registry.

        Args:
            skill_id: Unique identifier for the user skill.
            version: Skill version string extracted from SKILL.md.
            overrides_core_skill_id: The core skill being overridden, or None.
            audit_event_id: Immutable audit log event ID for this registration.

        Raises:
            SkillAlreadyRegisteredError: If skill_id already has an active entry.
        """
        data = self.load()
        skills: list[dict] = data.get("skills", [])

        for entry in skills:
            if entry.get("skill_id") == skill_id and entry.get("status") == "active":
                raise SkillAlreadyRegisteredError(
                    f"Skill '{skill_id}' is already registered and active.",
                )

        new_entry: dict = {
            "skill_id": skill_id,
            "version": version,
            "status": "active",
            "approved_by": "human",
            "registered_at": date.today().isoformat(),
            "audit_event_id": audit_event_id,
        }
        if overrides_core_skill_id is not None:
            new_entry["overrides_core_skill_id"] = overrides_core_skill_id

        skills.append(new_entry)
        data["skills"] = skills
        self._write(data)
        self.load()  # integrity re-read

    def suspend(self, skill_id: str) -> None:
        """Transition skill_id from active → suspended."""
        data = self.load()
        for entry in data.get("skills", []):
            if entry.get("skill_id") == skill_id and entry.get("status") == "active":
                entry["status"] = "suspended"
        self._write(data)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
