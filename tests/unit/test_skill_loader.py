"""Unit tests for SkillLoader and RegistryManager."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cie.skills.loader import SkillLoader, SkillNamespace, SkillNotFoundError
from cie.skills.registry_manager import RegistryManager, SkillAlreadyRegisteredError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill_md(path: Path, version: str = "1.0.0") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Version: {version}\n\n## Description\nTest skill.\n",
        encoding="utf-8",
    )


def _write_metadata_yaml(skill_dir: Path, core_skill_id: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "METADATA.yaml").write_text(
        yaml.safe_dump({"overrides": {"core_skill_id": core_skill_id}}),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# SkillLoader
# ---------------------------------------------------------------------------


class TestSkillLoader:
    def test_discover_core_skills(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        _write_skill_md(skills_root / "core" / "statistics" / "t-test" / "SKILL.md", "1.2.3")
        _write_skill_md(skills_root / "core" / "statistics" / "anova" / "SKILL.md", "2.0.0")

        loader = SkillLoader(skills_root)
        core_skills = loader.get_all_core_skills()

        skill_ids = {s.skill_id for s in core_skills}
        assert "statistics/t-test" in skill_ids
        assert "statistics/anova" in skill_ids
        assert all(s.namespace == SkillNamespace.CORE for s in core_skills)

    def test_discover_user_overrides(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        user_dir = skills_root / "user" / "my-t-test"
        _write_skill_md(user_dir / "SKILL.md", "0.1.0")
        _write_metadata_yaml(user_dir, "statistics/t-test")

        loader = SkillLoader(skills_root)
        user_skills = loader.get_all_user_skills()

        assert len(user_skills) == 1
        assert user_skills[0].overrides == "statistics/t-test"

    def test_resolve_user_over_core(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        _write_skill_md(skills_root / "core" / "statistics" / "t-test" / "SKILL.md", "1.0.0")

        user_dir = skills_root / "user" / "my-t-test"
        _write_skill_md(user_dir / "SKILL.md", "0.9.0")
        _write_metadata_yaml(user_dir, "statistics/t-test")

        loader = SkillLoader(skills_root)
        result = loader.resolve("statistics/t-test")

        assert result.namespace == SkillNamespace.USER

    def test_resolve_meta_separate(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        _write_skill_md(skills_root / "meta" / "skill-evaluator" / "SKILL.md", "1.0.0")

        loader = SkillLoader(skills_root)

        with pytest.raises(SkillNotFoundError):
            loader.resolve("skill-evaluator")

        meta = loader.resolve_meta("skill-evaluator")
        assert meta.namespace == SkillNamespace.META
        assert meta.skill_id == "skill-evaluator"

    def test_skill_not_found_error(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        skills_root.mkdir()

        loader = SkillLoader(skills_root)

        with pytest.raises(SkillNotFoundError):
            loader.resolve("statistics/nonexistent")

    def test_version_extracted_from_header(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        _write_skill_md(skills_root / "core" / "statistics" / "t-test" / "SKILL.md", "3.1.4")

        loader = SkillLoader(skills_root)
        result = loader.resolve("statistics/t-test")

        assert result.version == "3.1.4"

    def test_version_fallback_when_absent(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        skill_md = skills_root / "core" / "statistics" / "t-test" / "SKILL.md"
        skill_md.parent.mkdir(parents=True, exist_ok=True)
        skill_md.write_text("## Description\nNo version header.\n", encoding="utf-8")

        loader = SkillLoader(skills_root)
        result = loader.resolve("statistics/t-test")

        assert result.version == "0.0.0"

    def test_has_examples_and_tests_flags(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        skill_dir = skills_root / "core" / "statistics" / "t-test"
        _write_skill_md(skill_dir / "SKILL.md")
        (skill_dir / "examples").mkdir()
        (skill_dir / "tests").mkdir()
        (skill_dir / "versions").mkdir()

        loader = SkillLoader(skills_root)
        result = loader.resolve("statistics/t-test")

        assert result.has_examples is True
        assert result.has_tests is True
        assert result.has_versions_dir is True

    def test_bad_metadata_yaml_skips_skill(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        user_dir = skills_root / "user" / "broken-skill"
        _write_skill_md(user_dir / "SKILL.md")
        (user_dir / "METADATA.yaml").write_text("{ invalid yaml: [", encoding="utf-8")

        loader = SkillLoader(skills_root)
        # Broken METADATA.yaml must not crash the loader
        user_skills = loader.get_all_user_skills()
        assert all(s.skill_id != "broken-skill" for s in user_skills)

    def test_discover_empty_skills_root(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        skills_root.mkdir()

        loader = SkillLoader(skills_root)
        assert loader.discover() == {}


# ---------------------------------------------------------------------------
# RegistryManager
# ---------------------------------------------------------------------------


class TestRegistryManager:
    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        manager = RegistryManager(tmp_path / "REGISTRY.yaml")
        assert manager.load() == {"skills": []}

    def test_registry_register_and_get(self, tmp_path: Path) -> None:
        manager = RegistryManager(tmp_path / "REGISTRY.yaml")
        manager.register("statistics/t-test", "1.0.0", None, "audit-001")

        entry = manager.get("statistics/t-test")
        assert entry is not None
        assert entry["skill_id"] == "statistics/t-test"
        assert entry["version"] == "1.0.0"
        assert entry["status"] == "active"
        assert entry["approved_by"] == "human"
        assert entry["audit_event_id"] == "audit-001"

    def test_registry_duplicate_active_rejected(self, tmp_path: Path) -> None:
        manager = RegistryManager(tmp_path / "REGISTRY.yaml")
        manager.register("statistics/t-test", "1.0.0", None, "audit-001")

        with pytest.raises(SkillAlreadyRegisteredError):
            manager.register("statistics/t-test", "1.0.1", None, "audit-002")

    def test_register_with_overrides(self, tmp_path: Path) -> None:
        manager = RegistryManager(tmp_path / "REGISTRY.yaml")
        manager.register("my-t-test", "0.1.0", "statistics/t-test", "audit-010")

        entry = manager.get("my-t-test")
        assert entry is not None
        assert entry["overrides_core_skill_id"] == "statistics/t-test"

    def test_get_active_skills(self, tmp_path: Path) -> None:
        manager = RegistryManager(tmp_path / "REGISTRY.yaml")
        manager.register("statistics/t-test", "1.0.0", None, "audit-001")
        manager.register("reporting/table-one", "1.0.0", None, "audit-002")
        manager.suspend("reporting/table-one")

        active = manager.get_active_skills()
        active_ids = {e["skill_id"] for e in active}
        assert "statistics/t-test" in active_ids
        assert "reporting/table-one" not in active_ids

    def test_suspend_skill(self, tmp_path: Path) -> None:
        manager = RegistryManager(tmp_path / "REGISTRY.yaml")
        manager.register("statistics/t-test", "1.0.0", None, "audit-001")
        manager.suspend("statistics/t-test")

        entry = manager.get("statistics/t-test")
        assert entry is not None
        assert entry["status"] == "suspended"

    def test_get_nonexistent_returns_none(self, tmp_path: Path) -> None:
        manager = RegistryManager(tmp_path / "REGISTRY.yaml")
        assert manager.get("nonexistent/skill") is None

    def test_register_after_suspend_allowed(self, tmp_path: Path) -> None:
        manager = RegistryManager(tmp_path / "REGISTRY.yaml")
        manager.register("statistics/t-test", "1.0.0", None, "audit-001")
        manager.suspend("statistics/t-test")
        # Re-registration after suspension must succeed (no longer active)
        manager.register("statistics/t-test", "1.1.0", None, "audit-002")

        active = manager.get_active_skills()
        assert any(e["skill_id"] == "statistics/t-test" for e in active)
