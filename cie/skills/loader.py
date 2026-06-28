"""CIE Platform — Skill loader.

Discovers SKILL.md files across the three namespaces (core/, meta/, user/)
and resolves them according to namespace priority: user/ > core/.
meta/ is infrastructure and is never returned by resolve().

ADR-0002 Principles 1–3.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from cie.core.exceptions import CIEError

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"#\s*Version:\s*(\S+)")


class SkillNamespace(str, Enum):
    """Three-namespace structure defined in ADR-0002 Principle 1."""

    CORE = "core"
    META = "meta"
    USER = "user"


@dataclass
class SkillMetadata:
    """Resolved metadata for a single SKILL.md entry."""

    skill_id: str
    namespace: SkillNamespace
    version: str
    skill_path: Path
    has_examples: bool
    has_tests: bool
    has_versions_dir: bool  # core/ only
    overrides: str | None   # overrides.core_skill_id from user/ METADATA.yaml


class SkillNotFoundError(CIEError):
    """Raised when a skill_id cannot be resolved in any eligible namespace."""

    error_code = "SKILL_NOT_FOUND"


class SkillLoader:
    """Discovers and resolves Skills from the skills/ directory tree."""

    NAMESPACE_PRIORITY: list[SkillNamespace] = [
        SkillNamespace.USER,
        SkillNamespace.CORE,
        # META is infrastructure; Orchestrator addresses it directly via resolve_meta()
    ]

    def __init__(self, skills_root: Path) -> None:
        """Args:
            skills_root: Absolute path to the project-level skills/ directory.
        """
        self._root = skills_root

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_version(self, skill_md: Path) -> str:
        """Read at most 20 lines of SKILL.md and return the version string."""
        try:
            with skill_md.open(encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if i >= 20:
                        break
                    match = _VERSION_RE.search(line)
                    if match:
                        return match.group(1)
        except OSError:
            pass
        return "0.0.0"

    def _core_meta(self, skill_md: Path) -> SkillMetadata:
        skill_dir = skill_md.parent
        skill_id = f"{skill_dir.parent.name}/{skill_dir.name}"
        return SkillMetadata(
            skill_id=skill_id,
            namespace=SkillNamespace.CORE,
            version=self._extract_version(skill_md),
            skill_path=skill_md,
            has_examples=(skill_dir / "examples").is_dir(),
            has_tests=(skill_dir / "tests").is_dir(),
            has_versions_dir=(skill_dir / "versions").is_dir(),
            overrides=None,
        )

    def _meta_meta(self, skill_md: Path) -> SkillMetadata:
        skill_dir = skill_md.parent
        return SkillMetadata(
            skill_id=skill_dir.name,
            namespace=SkillNamespace.META,
            version=self._extract_version(skill_md),
            skill_path=skill_md,
            has_examples=(skill_dir / "examples").is_dir(),
            has_tests=(skill_dir / "tests").is_dir(),
            has_versions_dir=False,
            overrides=None,
        )

    def _user_meta(self, skill_md: Path) -> SkillMetadata | None:
        """Return None if METADATA.yaml is present but unparseable (logged as warning)."""
        skill_dir = skill_md.parent
        overrides: str | None = None
        metadata_yaml = skill_dir / "METADATA.yaml"
        if metadata_yaml.is_file():
            try:
                with metadata_yaml.open(encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh) or {}
                overrides = (raw.get("overrides") or {}).get("core_skill_id")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping user skill %s — failed to parse METADATA.yaml: %s",
                    skill_dir.name,
                    exc,
                )
                return None

        # If the skill overrides a core skill, it inherits that skill_id so that
        # resolve() can compare them under the same key (ADR-0002 Principle 3).
        skill_id = overrides if overrides else skill_dir.name
        return SkillMetadata(
            skill_id=skill_id,
            namespace=SkillNamespace.USER,
            version=self._extract_version(skill_md),
            skill_path=skill_md,
            has_examples=(skill_dir / "examples").is_dir(),
            has_tests=(skill_dir / "tests").is_dir(),
            has_versions_dir=False,
            overrides=overrides,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover(self) -> dict[str, list[SkillMetadata]]:
        """Return {skill_id: [SkillMetadata, ...]} across all namespaces.

        meta/ entries are included in the result but will be excluded by
        resolve() since META is absent from NAMESPACE_PRIORITY.
        """
        result: dict[str, list[SkillMetadata]] = {}

        core_root = self._root / "core"
        if core_root.is_dir():
            for skill_md in sorted(core_root.glob("**/SKILL.md")):
                # Expect exactly: core/{domain}/{skill_name}/SKILL.md
                if len(skill_md.relative_to(core_root).parts) != 3:
                    continue
                entry = self._core_meta(skill_md)
                result.setdefault(entry.skill_id, []).append(entry)

        meta_root = self._root / "meta"
        if meta_root.is_dir():
            for skill_md in sorted(meta_root.glob("*/SKILL.md")):
                entry = self._meta_meta(skill_md)
                result.setdefault(entry.skill_id, []).append(entry)

        user_root = self._root / "user"
        if user_root.is_dir():
            for skill_md in sorted(user_root.glob("*/SKILL.md")):
                entry = self._user_meta(skill_md)
                if entry is None:
                    continue
                result.setdefault(entry.skill_id, []).append(entry)

        return result

    def resolve(self, skill_id: str) -> SkillMetadata:
        """Return the highest-priority SkillMetadata for skill_id.

        Raises:
            SkillNotFoundError: If skill_id is absent from all eligible namespaces.
        """
        candidates = self.discover().get(skill_id, [])
        for ns in self.NAMESPACE_PRIORITY:
            for candidate in candidates:
                if candidate.namespace == ns:
                    return candidate
        raise SkillNotFoundError(f"Skill '{skill_id}' not found in any namespace.")

    def resolve_meta(self, meta_skill_name: str) -> SkillMetadata:
        """Return SkillMetadata for a meta/ skill by its folder name.

        Raises:
            SkillNotFoundError: If the meta skill does not exist.
        """
        skill_md = self._root / "meta" / meta_skill_name / "SKILL.md"
        if not skill_md.is_file():
            raise SkillNotFoundError(f"Meta-Skill '{meta_skill_name}' not found.")
        return self._meta_meta(skill_md)

    def get_all_core_skills(self) -> list[SkillMetadata]:
        """Return all SkillMetadata entries from the core/ namespace."""
        return [
            m
            for metas in self.discover().values()
            for m in metas
            if m.namespace == SkillNamespace.CORE
        ]

    def get_all_user_skills(self) -> list[SkillMetadata]:
        """Return all SkillMetadata entries from the user/ namespace."""
        return [
            m
            for metas in self.discover().values()
            for m in metas
            if m.namespace == SkillNamespace.USER
        ]
