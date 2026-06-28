"""CIE Platform — User Skill Scaffolder.

Implements the meta/skill-scaffolder SKILL.md procedure.
Generates a draft SKILL.md template and METADATA.yaml for a new User Skill
so that the user can fill in the content before validation and registration.

Key invariants (PROJECT_RULES.md Section 11 / ADR-0002):
  - Generated SKILL.md contains only TODO placeholders — no business logic.
  - METADATA.yaml is created with status="draft" and approved_by=null.
  - Registration is performed later by LifecycleService.register_user_skill().
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from cie.skills.loader import SkillLoader, SkillNotFoundError


# Matches the pattern defined in meta/skill-scaffolder/SKILL.md Step 1.
SKILL_ID_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9\-]{2,49}$")

_SECTION_RE = re.compile(r"^## (.+)$", re.MULTILINE)

_PROJECT_RULES_NOTICE = """\
# IMPORTANT: This is a User Skill.
# - It must NOT contain project-specific business logic (PROJECT_RULES.md Section 11)
# - It must NOT access raw patient data
# - It must NOT modify workflow definitions
# - External network access is prohibited (Offline First: AP-012)"""


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class ScaffoldResult:
    """Outcome of a successful scaffold() call."""

    skill_id: str
    namespace: str  # always "user"
    draft_path: Path
    files_created: list[str] = field(default_factory=list)
    next_step: str = "Fill in SKILL.md, then run validation"


# ---------------------------------------------------------------------------
# Scaffolder
# ---------------------------------------------------------------------------


class SkillScaffolder:
    """Generates draft User Skill scaffolds.

    Follows the procedure in skills/meta/skill-scaffolder/SKILL.md.
    Does NOT register the skill (that requires LifecycleService.register_user_skill()).
    """

    SKILL_ID_PATTERN: re.Pattern[str] = SKILL_ID_PATTERN

    def __init__(self, skills_root: Path, skill_loader: SkillLoader) -> None:
        """Args:
            skills_root: Absolute path to the project-level skills/ directory.
            skill_loader: Used to validate overrides and load core Skill sections.
        """
        self._root = skills_root
        self._loader = skill_loader

    def scaffold(
        self,
        skill_id: str,
        description: str,
        overrides_core_skill_id: str | None = None,
        override_reason: str | None = None,
    ) -> ScaffoldResult:
        """Generate a draft User Skill directory at skills/user/{skill_id}/.

        Args:
            skill_id: Lowercase alphanumeric + hyphens, 3–50 chars.
            description: Human-readable description for the SKILL.md header.
            overrides_core_skill_id: Optional fully-qualified core skill ID to override
                (e.g. ``"statistics/t-test"``).
            override_reason: Reason for the override (required when overriding).

        Returns:
            ScaffoldResult with draft_path and list of created files.

        Raises:
            ValueError: skill_id format invalid, core Skill not found, or
                draft directory already exists.
        """
        # Step 1: Validate skill_id format
        if not self.SKILL_ID_PATTERN.match(skill_id):
            raise ValueError(
                f"skill_id must be lowercase alphanumeric with hyphens, 3-50 characters. "
                f"Got: '{skill_id}'"
            )

        # Step 2: Verify override target exists
        core_skill_sections: dict | None = None
        if overrides_core_skill_id is not None:
            try:
                core_meta = self._loader.resolve(overrides_core_skill_id)
            except SkillNotFoundError:
                raise ValueError(
                    f"Core Skill '{overrides_core_skill_id}' not found in skills/core/"
                )
            core_skill_sections = self._parse_core_skill_sections(core_meta.skill_path)

        # Step 3: Draft path must not already exist
        draft_path = self._root / "user" / skill_id
        if draft_path.exists():
            raise ValueError(
                f"User Skill '{skill_id}' already exists at {draft_path}"
            )

        # Step 4: Generate SKILL.md
        skill_md_content = self._generate_skill_md(
            skill_id,
            description,
            overrides_core_skill_id,
            override_reason,
            core_skill_sections,
        )

        # Step 5: Generate METADATA.yaml
        metadata_content = self._generate_metadata_yaml(
            skill_id, overrides_core_skill_id, override_reason
        )

        # Step 6: Write all files
        draft_path.mkdir(parents=True, exist_ok=True)
        (draft_path / "SKILL.md").write_text(skill_md_content, encoding="utf-8")
        (draft_path / "METADATA.yaml").write_text(metadata_content, encoding="utf-8")

        examples_dir = draft_path / "examples"
        tests_dir = draft_path / "tests"
        examples_dir.mkdir(exist_ok=True)
        tests_dir.mkdir(exist_ok=True)
        (examples_dir / "example.md").write_text(
            "# Example\n# TODO: Add examples\n", encoding="utf-8"
        )
        (tests_dir / "tests.md").write_text(
            "# Tests\n# See SKILL.md — Tests section\n", encoding="utf-8"
        )

        files_created = [
            "SKILL.md",
            "METADATA.yaml",
            "examples/example.md",
            "tests/tests.md",
        ]

        # Step 7: Return result
        return ScaffoldResult(
            skill_id=skill_id,
            namespace="user",
            draft_path=draft_path,
            files_created=files_created,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_skill_md(
        self,
        skill_id: str,
        description: str,
        overrides_core_skill_id: str | None,
        override_reason: str | None,
        core_skill_sections: dict | None,
    ) -> str:
        """Build SKILL.md content following the scaffolder SKILL.md Step 3 template."""
        today = datetime.now(timezone.utc).date().isoformat()

        override_section = ""
        if overrides_core_skill_id:
            override_section = (
                f"\n## Override Declaration\n\n"
                f"This User Skill overrides `core/{overrides_core_skill_id}`.\n"
                f"The interface (input types and output schema) MUST remain compatible.\n"
                f"Override reason: {override_reason or '(not specified)'}\n"
            )

        if core_skill_sections is not None:
            applies_when = core_skill_sections.get("applies_when", "")
            if applies_when:
                applies_when_block = f"## Applies when\n\n{applies_when}"
            else:
                applies_when_block = "## Applies when\n\n# TODO: Define when this Skill applies"
        else:
            applies_when_block = "## Applies when\n\n# TODO: Define when this Skill applies"

        if core_skill_sections is not None and overrides_core_skill_id:
            inherited = core_skill_sections.get("validation_rules", "")
            validation_rules_block = (
                f"## Validation Rules (Minimum — inherited from core/{overrides_core_skill_id})\n\n"
                f"{inherited}\n\n"
                f"## Additional Validation Rules (User-defined)\n\n"
                f"# TODO: Add any additional validation rules specific to your use case"
            )
        else:
            validation_rules_block = (
                "## Validation Rules\n\n"
                "# TODO: Define validation rules for this Skill"
            )

        return f"""\
# SKILL: {description}
# Skill ID: user/{skill_id}
# Version: 1.0.0
# Namespace: user
# Created: {today}
# Override: {overrides_core_skill_id or 'none'}
#
{_PROJECT_RULES_NOTICE}
{override_section}
## Overview

{description}

{applies_when_block}

---

## Procedure

### Step 1 — [TODO: First step name]

```r
# TODO: Implement Step 1
# Use var_n aliases throughout (never original column names)
# Write outputs to file.path(Sys.getenv("OUTPUT_DIR"), "...")
```

### Step 2 — [TODO: Second step name]

```r
# TODO: Implement Step 2
```

### Step N — Structure output

```r
# TODO: Define the output structure
skill_result <- list(
  skill_id = "user/{skill_id}",
  # TODO: Add output fields
)
```

---

{validation_rules_block}

---

## Examples

### Example 1 — [TODO: Example name]

```
# TODO: Add an example showing:
# - Input (intent_object or statistical_results)
# - Expected output
```

---

## Tests

### TEST-U01: [TODO: Test name]

```r
# TODO: Minimum 1 test is required for registration
# stopifnot(...)
```
"""

    def _generate_metadata_yaml(
        self,
        skill_id: str,
        overrides_core_skill_id: str | None,
        override_reason: str | None,
    ) -> str:
        """Build METADATA.yaml content following the scaffolder SKILL.md Step 4 template."""
        today = datetime.now(timezone.utc).date().isoformat()
        interface_compatible = overrides_core_skill_id is not None

        data: dict = {
            "skill_id": skill_id,
            "namespace": "user",
            "version": "1.0.0",
            "overrides": {
                "core_skill_id": overrides_core_skill_id,
                "override_reason": override_reason,
            },
            "created_by": "user",
            "created_at": today,
            "approved_at": None,
            "approved_by": None,
            "validation": {
                "interface_compatible": interface_compatible,
                "tests_passed": False,
                "minimum_test_count": 1,
            },
            "status": "draft",
        }
        header = (
            f"# skills/user/{skill_id}/METADATA.yaml\n"
            f"# Generated by meta/skill-scaffolder v1.0.0\n\n"
        )
        return header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

    def _parse_core_skill_sections(self, skill_md_path: Path) -> dict:
        """Parse a SKILL.md file into a dict of section_name → content.

        Keys are normalised to lowercase snake_case (e.g. "Validation Rules" → "validation_rules").
        """
        content = skill_md_path.read_text(encoding="utf-8")
        sections: dict[str, str] = {}

        parts = _SECTION_RE.split(content)
        # parts: [preamble, "Section Name", "body", "Section Name", "body", ...]
        it = iter(parts)
        next(it)  # skip preamble before first ##
        for header in it:
            body = next(it, "")
            key = header.strip().lower().replace(" ", "_")
            sections[key] = body.strip()

        return sections
