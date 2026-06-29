#!/usr/bin/env python3
"""CIE Platform — Definition of Done 自動チェッカー.

PROJECT_RULES.md Section 17 と MANIFEST.yaml で定義された全必須項目を検証します。

実行:
    python scripts/check_done.py [--project-root PATH]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_manifest(project_root: Path) -> dict:
    manifest_path = project_root / "MANIFEST.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"MANIFEST.yaml not found at {manifest_path}")
    with manifest_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# Check 1: MANIFEST.yaml 必須ファイルの存在
# ---------------------------------------------------------------------------


def check_manifest_files(project_root: Path) -> list[str]:
    """MANIFEST.yaml で定義された全必須ファイル・ディレクトリの存在を確認する."""
    failures: list[str] = []
    manifest = _load_manifest(project_root)
    repo = manifest.get("repository", {})

    # architecture/
    arch = repo.get("architecture", {})
    arch_root = project_root / arch.get("root", "architecture/")
    for fname in arch.get("required", []):
        p = arch_root / fname
        if not p.exists():
            failures.append(f"Missing: {p.relative_to(project_root)}")

    # spec/
    spec_section = repo.get("specification", {})
    spec_root = project_root / spec_section.get("root", "spec/")
    for fname in spec_section.get("required", []):
        p = spec_root / fname
        if not p.exists():
            failures.append(f"Missing: {p.relative_to(project_root)}")
    for subdir_name, subdir_cfg in spec_section.get("subdirectories", {}).items():
        subdir_path = spec_root / subdir_name
        for fname in subdir_cfg.get("required", []):
            p = subdir_path / fname
            if not p.exists():
                failures.append(f"Missing: {p.relative_to(project_root)}")

    # schemas/
    schema_section = repo.get("schemas", {})
    schema_root = project_root / schema_section.get("root", "schemas/")
    for fname in schema_section.get("required", []):
        p = schema_root / fname
        if not p.exists():
            failures.append(f"Missing: {p.relative_to(project_root)}")

    # agents/
    agent_section = repo.get("agents", {})
    agent_root = project_root / agent_section.get("root", "agents/")
    for fname in agent_section.get("required", []):
        p = agent_root / fname
        if not p.exists():
            failures.append(f"Missing: {p.relative_to(project_root)}")

    # decisions/
    decisions_section = repo.get("decisions", {})
    decisions_root = project_root / decisions_section.get("root", "decisions/")
    for fname in decisions_section.get("required", []):
        p = decisions_root / fname
        if not p.exists():
            failures.append(f"Missing: {p.relative_to(project_root)}")

    # evaluation/
    eval_section = repo.get("evaluation", {})
    eval_root = project_root / eval_section.get("root", "evaluation/")
    for fname in eval_section.get("required", []):
        p = eval_root / fname
        if not p.exists():
            failures.append(f"Missing: {p.relative_to(project_root)}")

    return failures


# ---------------------------------------------------------------------------
# Check 2: JSON スキーマ有効性
# ---------------------------------------------------------------------------


def check_schema_validity(project_root: Path) -> list[str]:
    """schemas/ 配下の全 JSON スキーマが有効な JSON Schema であること."""
    try:
        import jsonschema
        from jsonschema import Draft202012Validator
    except ImportError:
        return ["jsonschema package not installed — cannot validate schemas"]

    failures: list[str] = []
    schema_dir = project_root / "schemas"
    if not schema_dir.exists():
        return [f"Missing schemas/ directory at {schema_dir}"]

    for schema_file in sorted(schema_dir.glob("*.json")):
        try:
            with schema_file.open(encoding="utf-8") as fh:
                schema_data = json.load(fh)
        except json.JSONDecodeError as exc:
            failures.append(f"Invalid JSON in {schema_file.name}: {exc}")
            continue

        try:
            Draft202012Validator.check_schema(schema_data)
        except jsonschema.SchemaError as exc:
            failures.append(f"Schema error in {schema_file.name}: {exc.message}")

    return failures


# ---------------------------------------------------------------------------
# Check 3: ADR 存在確認
# ---------------------------------------------------------------------------


def check_adr_for_architecture_changes(project_root: Path) -> list[str]:
    """decisions/ に ADR-0001〜ADR-0003 が存在すること."""
    failures: list[str] = []
    decisions_dir = project_root / "decisions"
    required_adrs = ["ADR-0001.md", "ADR-0002.md", "ADR-0003.md"]
    for adr in required_adrs:
        if not (decisions_dir / adr).exists():
            failures.append(f"Missing: decisions/{adr}")
    return failures


# ---------------------------------------------------------------------------
# Check 4: Skill 名前空間構造
# ---------------------------------------------------------------------------


def check_skill_namespace_structure(project_root: Path) -> list[str]:
    """skills/core/, meta/, user/ の構造が MANIFEST 定義と一致すること."""
    failures: list[str] = []
    manifest = _load_manifest(project_root)
    namespaces = (
        manifest.get("repository", {})
        .get("skills", {})
        .get("namespaces", {})
    )

    # ── core/ ──────────────────────────────────────────────────────────
    core_cfg = namespaces.get("core", {})
    core_root = project_root / core_cfg.get("root", "skills/core/")
    for required_skill_path in core_cfg.get("required", []):
        skill_dir = core_root / required_skill_path.rstrip("/")
        if not skill_dir.exists():
            failures.append(f"Missing core skill: {skill_dir.relative_to(project_root)}")
            continue
        # Each core skill must have a versions/ directory (ADR-0002)
        versions_dir = skill_dir / "versions"
        if not versions_dir.exists():
            failures.append(
                f"Missing versions/ in core skill: "
                f"{skill_dir.relative_to(project_root)}/versions/"
            )

    # ── meta/ ──────────────────────────────────────────────────────────
    meta_cfg = namespaces.get("meta", {})
    meta_root = project_root / meta_cfg.get("root", "skills/meta/")
    for required_meta in meta_cfg.get("required", []):
        meta_dir = meta_root / required_meta.rstrip("/")
        if not meta_dir.exists():
            failures.append(
                f"Missing meta skill: {meta_dir.relative_to(project_root)}"
            )

    # ── user/ ──────────────────────────────────────────────────────────
    user_cfg = namespaces.get("user", {})
    registry_path_str = user_cfg.get("registry", "skills/user/REGISTRY.yaml")
    registry_path = project_root / registry_path_str
    if not registry_path.exists():
        # Also accept .yml extension as equivalent
        alt_path = registry_path.with_suffix(".yml")
        if not alt_path.exists():
            failures.append(f"Missing user Skill registry: {registry_path_str}")

    return failures


# ---------------------------------------------------------------------------
# Check 5: ADR-0001 実装確認（Planner に workflow_id_assignment 禁止）
# ---------------------------------------------------------------------------


def check_no_workflow_id_in_planner(project_root: Path) -> list[str]:
    """agents/planner.yaml に workflow_id_assignment が strictly_forbidden に含まれること."""
    failures: list[str] = []
    planner_yaml = project_root / "agents" / "planner.yaml"
    if not planner_yaml.exists():
        return ["Missing: agents/planner.yaml"]

    with planner_yaml.open(encoding="utf-8") as fh:
        planner_cfg = yaml.safe_load(fh)

    forbidden: list = (
        planner_cfg.get("responsibility_boundaries", {}).get("strictly_forbidden", [])
    )
    if "workflow_id_assignment" not in forbidden:
        failures.append(
            "agents/planner.yaml: 'workflow_id_assignment' not in strictly_forbidden "
            "(ADR-0001 Principle 2)"
        )
    return failures


# ---------------------------------------------------------------------------
# Check 6: ADR-0002 実装確認（spec/skill-lifecycle.md の存在）
# ---------------------------------------------------------------------------


def check_skill_lifecycle_spec_exists(project_root: Path) -> list[str]:
    """spec/skill-lifecycle.md が存在すること (ADR-0002)."""
    spec_file = project_root / "spec" / "skill-lifecycle.md"
    if not spec_file.exists():
        return ["Missing: spec/skill-lifecycle.md (required by ADR-0002)"]
    return []


# ---------------------------------------------------------------------------
# Check 7: ADR-0002 実装確認（spec/permissions.yaml に skill_lifecycle エージェント）
# ---------------------------------------------------------------------------


def check_permissions_yaml_skill_lifecycle(project_root: Path) -> list[str]:
    """spec/permissions.yaml に skill_lifecycle エージェントが定義されていること."""
    perm_yaml = project_root / "spec" / "permissions.yaml"
    if not perm_yaml.exists():
        return ["Missing: spec/permissions.yaml"]

    with perm_yaml.open(encoding="utf-8") as fh:
        perm_cfg = yaml.safe_load(fh)

    matrix: dict = perm_cfg.get("agent_permission_matrix", {})
    if "skill_lifecycle" not in matrix:
        return [
            "spec/permissions.yaml: 'skill_lifecycle' agent not in "
            "agent_permission_matrix (ADR-0002)"
        ]
    return []


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_checks(project_root: Path) -> dict[str, list[str]]:
    """全チェックを実行してカテゴリ別の結果を返す."""
    checks = [
        ("必須ファイルの存在", check_manifest_files),
        ("スキーマ有効性", check_schema_validity),
        ("ADR 存在確認", check_adr_for_architecture_changes),
        ("Skill 名前空間構造", check_skill_namespace_structure),
        ("ADR-0001 実装確認", check_no_workflow_id_in_planner),
        ("ADR-0002 実装確認(spec)", check_skill_lifecycle_spec_exists),
        ("ADR-0002 実装確認(permissions)", check_permissions_yaml_skill_lifecycle),
    ]
    results: dict[str, list[str]] = {}
    for name, fn in checks:
        results[name] = fn(project_root)
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="CIE Platform — Definition of Done チェッカー"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).parent.parent,
        help="Project root directory (default: parent of scripts/)",
    )
    args = parser.parse_args(argv)

    project_root: Path = args.project_root.resolve()
    print(f"Project root: {project_root}\n")

    results = run_checks(project_root)

    total_failures = 0
    for category, failures in results.items():
        if failures:
            print(f"❌ {category}")
            for f in failures:
                print(f"   - {f}")
            total_failures += len(failures)
        else:
            print(f"✅ {category}")

    print(f"\n{'=' * 50}")
    if total_failures == 0:
        print("✅ Definition of Done: 全項目クリア")
        return 0
    else:
        print(f"❌ Definition of Done: {total_failures} 件の問題が残っています")
        return 1


if __name__ == "__main__":
    sys.exit(main())
