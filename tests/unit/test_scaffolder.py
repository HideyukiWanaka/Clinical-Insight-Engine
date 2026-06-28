"""Unit tests for SkillScaffolder (meta/skill-scaffolder)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cie.skills.loader import SkillLoader
from cie.skills.scaffolder import ScaffoldResult, SkillScaffolder


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_scaffolder(tmp_path: Path) -> SkillScaffolder:
    skills_root = tmp_path / "skills"
    skills_root.mkdir(exist_ok=True)
    loader = SkillLoader(skills_root)
    return SkillScaffolder(skills_root, loader)


def _write_core_skill(tmp_path: Path, domain: str, name: str, version: str = "1.0.0") -> Path:
    """Create a minimal core SKILL.md in tmp_path/skills/core/{domain}/{name}/."""
    skill_dir = tmp_path / "skills" / "core" / domain / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = (
        f"# SKILL: {name}\n"
        f"# Version: {version}\n\n"
        f"## Overview\n\nThe {name} skill.\n\n"
        f"## Applies when\n\nUse this skill when performing {name} analysis.\n\n"
        f"## Procedure\n\n### Step 1\n\nDo {name} analysis.\n\n"
        f"## Validation Rules\n\n- Output must include p_value.\n- Effect size required.\n\n"
        f"## Tests\n\n### TEST-{name.upper().replace('-', '')}-01\n\n"
        f"Run the test.\n"
    )
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")
    return skill_md


# ---------------------------------------------------------------------------
# test_scaffold_creates_files
# ---------------------------------------------------------------------------


def test_scaffold_creates_files(tmp_path: Path) -> None:
    """scaffold() must create exactly SKILL.md, METADATA.yaml, examples/example.md, tests/tests.md."""
    svc = _make_scaffolder(tmp_path)
    result = svc.scaffold("my-new-skill", "My new skill description")

    assert isinstance(result, ScaffoldResult)
    assert result.namespace == "user"
    assert set(result.files_created) == {
        "SKILL.md",
        "METADATA.yaml",
        "examples/example.md",
        "tests/tests.md",
    }

    draft = result.draft_path
    assert (draft / "SKILL.md").is_file()
    assert (draft / "METADATA.yaml").is_file()
    assert (draft / "examples" / "example.md").is_file()
    assert (draft / "tests" / "tests.md").is_file()


# ---------------------------------------------------------------------------
# test_invalid_skill_id_rejected
# ---------------------------------------------------------------------------


def test_invalid_skill_id_rejected(tmp_path: Path) -> None:
    """skill_ids with uppercase, underscores, or too short must raise ValueError."""
    svc = _make_scaffolder(tmp_path)

    for bad_id in ("My_Invalid", "UPPER", "ab", "a", "has space", "123_ABC"):
        with pytest.raises(ValueError, match="skill_id must be"):
            svc.scaffold(bad_id, "Description")


# ---------------------------------------------------------------------------
# test_nonexistent_override_rejected
# ---------------------------------------------------------------------------


def test_nonexistent_override_rejected(tmp_path: Path) -> None:
    """Attempting to override a non-existent core Skill must raise ValueError."""
    svc = _make_scaffolder(tmp_path)

    with pytest.raises(ValueError, match="Core Skill .* not found"):
        svc.scaffold(
            "my-extended-test",
            "Extended t-test",
            overrides_core_skill_id="statistics/nonexistent",
        )


# ---------------------------------------------------------------------------
# test_existing_skill_rejected
# ---------------------------------------------------------------------------


def test_existing_skill_rejected(tmp_path: Path) -> None:
    """Running scaffold() for an already-existing skill_id must raise ValueError."""
    svc = _make_scaffolder(tmp_path)
    svc.scaffold("my-skill", "First creation")

    with pytest.raises(ValueError, match="already exists"):
        svc.scaffold("my-skill", "Second attempt")


# ---------------------------------------------------------------------------
# test_core_validation_rules_inherited
# ---------------------------------------------------------------------------


def test_core_validation_rules_inherited(tmp_path: Path) -> None:
    """When overriding a core Skill, Validation Rules must be inherited into SKILL.md."""
    _write_core_skill(tmp_path, "statistics", "t-test")
    svc = _make_scaffolder(tmp_path)

    result = svc.scaffold(
        "extended-t-test",
        "Extended t-test for our hospital",
        overrides_core_skill_id="statistics/t-test",
        override_reason="AMA format required",
    )

    skill_md = (result.draft_path / "SKILL.md").read_text(encoding="utf-8")
    assert "inherited from core/statistics/t-test" in skill_md, (
        "SKILL.md must reference the inherited core Skill validation rules"
    )
    assert "p_value" in skill_md, "Inherited validation rule content must appear"


# ---------------------------------------------------------------------------
# test_project_rules_notice_in_header
# ---------------------------------------------------------------------------


def test_project_rules_notice_in_header(tmp_path: Path) -> None:
    """Generated SKILL.md must contain the PROJECT_RULES Section 11 notice block."""
    svc = _make_scaffolder(tmp_path)
    result = svc.scaffold("my-skill", "My skill")

    skill_md = (result.draft_path / "SKILL.md").read_text(encoding="utf-8")
    assert "IMPORTANT: This is a User Skill." in skill_md
    assert "project-specific business logic" in skill_md
    assert "raw patient data" in skill_md
    assert "workflow definitions" in skill_md
    assert "External network access is prohibited" in skill_md


# ---------------------------------------------------------------------------
# test_metadata_yaml_status_draft
# ---------------------------------------------------------------------------


def test_metadata_yaml_status_draft(tmp_path: Path) -> None:
    """METADATA.yaml must have status='draft' and approved_by=null."""
    svc = _make_scaffolder(tmp_path)
    result = svc.scaffold("my-skill", "My skill")

    raw = (result.draft_path / "METADATA.yaml").read_text(encoding="utf-8")
    # Strip comment lines before parsing
    yaml_lines = [l for l in raw.splitlines() if not l.strip().startswith("#")]
    data = yaml.safe_load("\n".join(yaml_lines))

    assert data["status"] == "draft"
    assert data["approved_by"] is None
    assert data["approved_at"] is None


# ---------------------------------------------------------------------------
# test_todo_placeholders_present
# ---------------------------------------------------------------------------


def test_todo_placeholders_present(tmp_path: Path) -> None:
    """Generated SKILL.md must contain TODO placeholders in every major section."""
    svc = _make_scaffolder(tmp_path)
    result = svc.scaffold("my-skill", "My skill")

    skill_md = (result.draft_path / "SKILL.md").read_text(encoding="utf-8")
    assert "# TODO:" in skill_md or "TODO:" in skill_md
    assert "## Procedure" in skill_md
    assert "## Overview" in skill_md
    assert "## Tests" in skill_md


# ---------------------------------------------------------------------------
# Extra: result fields are correct
# ---------------------------------------------------------------------------


def test_scaffold_result_fields(tmp_path: Path) -> None:
    """ScaffoldResult must have the correct skill_id, namespace, and next_step."""
    svc = _make_scaffolder(tmp_path)
    result = svc.scaffold("my-skill", "My skill")

    assert result.skill_id == "my-skill"
    assert result.namespace == "user"
    assert result.draft_path == tmp_path / "skills" / "user" / "my-skill"
    assert "validation" in result.next_step.lower() or "fill" in result.next_step.lower()
