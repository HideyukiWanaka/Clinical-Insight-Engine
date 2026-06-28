# SKILL: User Skill Scaffolder
# Skill ID: meta/skill-scaffolder
# Version: 1.0.0
# Namespace: meta
# Consumers: orchestrator (triggered by user request to add new Skill)
# Knowledge references:
#   - spec/skill-lifecycle.md (User Skill constraints, METADATA.yaml schema)
#   - skills/core/{reference_skill_id}/SKILL.md (template reference)
#   - PROJECT_RULES.md Section 11 (Skills never contain project-specific business logic)

## Overview

Generates a validated SKILL.md template and METADATA.yaml for a new User Skill.
Ensures the generated scaffold conforms to the SKILL interface standard and
does not violate PROJECT_RULES.md Section 11.

After scaffolding, the user fills in the Skill content.
meta/skill-validator/ then validates the completed Skill before
human approval and registration.

---

## Procedure

### Step 1 — Gather User Skill specification

```python
user_skill_spec = {
    # Required inputs from user
    "skill_id": user_input["skill_id"],          # e.g. "my-hospital-table-format"
    "description": user_input["description"],
    "overrides_core_skill_id": user_input.get("overrides"),  # e.g. "reporting/table-one"
    "override_reason": user_input.get("override_reason"),

    # Derived
    "namespace": "user",
    "version": "1.0.0"
}

# Validate skill_id format
import re
if not re.match(r'^[a-z0-9][a-z0-9\-]{2,49}$', user_skill_spec["skill_id"]):
    raise ValueError(
        "skill_id must be lowercase alphanumeric with hyphens, 3-50 characters. "
        f"Got: '{user_skill_spec['skill_id']}'"
    )
```

### Step 2 — Load reference Skill (if overriding a core Skill)

```python
def load_reference_skill(core_skill_id: str | None) -> dict | None:
    """
    If overriding a core Skill, load its interface definition as a template.
    This ensures the User Skill is interface-compatible.
    """
    if core_skill_id is None:
        return None

    core_path = resolve_skill_path(core_skill_id, "core")
    if not core_path.exists():
        raise ValueError(f"Core Skill '{core_skill_id}' not found in skills/core/")

    return parse_skill_sections(read_file(core_path / "SKILL.md"))
```

### Step 3 — Generate SKILL.md scaffold

```python
def generate_skill_md(spec: dict, reference: dict | None) -> str:
    """
    Generate a SKILL.md template.
    If reference is provided, preserve the Applies when / Validation Rules
    sections from the core Skill to maintain interface compatibility.
    """

    override_section = ""
    if spec["overrides_core_skill_id"]:
        override_section = f"""
## Override Declaration

This User Skill overrides `core/{spec['overrides_core_skill_id']}`.
The interface (input types and output schema) MUST remain compatible.
Override reason: {spec['override_reason']}
"""

    applies_when = ""
    if reference:
        # Preserve core Skill's "Applies when" to maintain compatibility
        applies_when = reference.get("applies_when", "")
    else:
        applies_when = "# TODO: Define when this Skill applies"

    validation_rules = ""
    if reference:
        # Preserve core Skill's validation rules as minimum requirements
        validation_rules = f"""
## Validation Rules (Minimum — inherited from core/{spec['overrides_core_skill_id']})

{reference.get('validation_rules', '')}

## Additional Validation Rules (User-defined)

# TODO: Add any additional validation rules specific to your use case
"""
    else:
        validation_rules = """
## Validation Rules

# TODO: Define validation rules for this Skill
"""

    return f"""# SKILL: {spec['description']}
# Skill ID: user/{spec['skill_id']}
# Version: {spec['version']}
# Namespace: user
# Created: {utc_date()}
# Override: {spec.get('overrides_core_skill_id', 'none')}
#
# IMPORTANT: This is a User Skill.
# - It must NOT contain project-specific business logic (PROJECT_RULES.md Section 11)
# - It must NOT access raw patient data
# - It must NOT modify workflow definitions
# - External network access is prohibited (Offline First: AP-012)
{override_section}
## Overview

{spec['description']}

{applies_when}

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
# Must conform to the expected_output_schema
skill_result <- list(
  skill_id = "user/{spec['skill_id']}",
  # TODO: Add output fields
)
```

---
{validation_rules}
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
```

### Step 4 — Generate METADATA.yaml

```python
def generate_metadata_yaml(spec: dict, reference: dict | None) -> str:
    interface_compatible = reference is not None  # will be verified by skill-validator

    return f"""# skills/user/{spec['skill_id']}/METADATA.yaml
# Generated by meta/skill-scaffolder v1.0.0

skill_id: "{spec['skill_id']}"
namespace: "user"
version: "{spec['version']}"

overrides:
  core_skill_id: {f'"{spec["overrides_core_skill_id"]}"' if spec.get("overrides_core_skill_id") else "null"}
  override_reason: {f'"{spec.get("override_reason", "")}"' if spec.get("override_reason") else "null"}

created_by: "user"
created_at: "{utc_date()}"
approved_at: null        # To be filled after human approval
approved_by: null        # Always "human" after approval

validation:
  interface_compatible: {str(interface_compatible).lower()}  # Verified by meta/skill-validator
  tests_passed: false    # To be verified by meta/skill-validator
  minimum_test_count: 1

status: "draft"          # draft → pending_review → active
"""
```

### Step 5 — Write scaffold files (to draft location)

```python
draft_path = Path(f"skills/user/{spec['skill_id']}")
draft_path.mkdir(parents=True, exist_ok=True)
(draft_path / "SKILL.md").write_text(skill_md_content)
(draft_path / "METADATA.yaml").write_text(metadata_yaml_content)
(draft_path / "examples").mkdir(exist_ok=True)
(draft_path / "tests").mkdir(exist_ok=True)

# Generate placeholder files
(draft_path / "examples" / "example.md").write_text(
    "# Example\n# TODO: Add examples\n"
)
(draft_path / "tests" / "tests.md").write_text(
    "# Tests\n# See SKILL.md — Tests section\n"
)

scaffold_result = {
    "skill_id": spec["skill_id"],
    "namespace": "user",
    "draft_path": str(draft_path),
    "files_created": [
        "SKILL.md", "METADATA.yaml",
        "examples/example.md", "tests/tests.md"
    ],
    "next_step": "Fill in SKILL.md, then run meta/skill-validator"
}
```

---

## Validation Rules

- `skill_id` は lowercase + hyphens のみ、3〜50文字
- coreSkillをオーバーライドする場合、`overrides_core_skill_id` は実在するcore Skillでなければならない
- 生成されたSKILL.mdは `#TODO` プレースホルダーを含む（完成はユーザーが担う）
- Scaffolderはdraftの書き込みのみ行う。登録はmeta/skill-validatorとHuman承認後

---

## Tests

### TEST-SC01: 有効なskill_idで正常にscaffoldが生成される

```python
result = scaffold_user_skill({
    "skill_id": "my-hospital-format",
    "description": "Custom table format for our hospital",
    "overrides": "reporting/table-one",
    "override_reason": "AMA format required"
})
assert "SKILL.md" in result["files_created"]
assert "METADATA.yaml" in result["files_created"]
assert result["namespace"] == "user"
```

### TEST-SC02: 無効なskill_idはエラーを返す

```python
with pytest.raises(ValueError, match="skill_id must be lowercase"):
    scaffold_user_skill({"skill_id": "My_Invalid_ID", ...})
```

### TEST-SC03: 存在しないcoreSkillのオーバーライドはエラーを返す

```python
with pytest.raises(ValueError, match="Core Skill .* not found"):
    scaffold_user_skill({"overrides": "statistics/nonexistent", ...})
```

### TEST-SC04: coreSkillのValidation Rulesが継承される

```python
result_content = scaffold_user_skill({
    "skill_id": "extended-t-test",
    "overrides": "statistics/t-test"
})
skill_md = read_file(result_content["draft_path"] + "/SKILL.md")
assert "inherited from core/statistics/t-test" in skill_md
```
