#!/usr/bin/env python3
"""
CIE Platform — Application Structure Validation

Validates that all MVP components are present, importable, and configured correctly
without requiring LLM API keys. This is the first step before running full test scenarios.

Usage:
    python3 validate_app_structure.py
"""

import sys
import importlib.util
import json
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ValidationResult:
    category: str
    check_name: str
    status: str  # "PASS", "FAIL", "WARN"
    message: str
    details: dict = None


def validate_imports() -> list[ValidationResult]:
    """Verify all core modules are importable."""
    results = []
    modules_to_test = [
        ("cie.core.config", "Configuration"),
        ("cie.core.database", "Database"),
        ("cie.core.llm_client", "LLM Client"),
        ("cie.agents.planner", "Planner Agent"),
        ("cie.agents.data_quality", "Data Quality Agent"),
        ("cie.agents.statistics", "Statistics Agent"),
        ("cie.workflow.orchestrator", "Workflow Orchestrator"),
        ("cie.security.pii_filter", "PII Filter"),
        ("cie.security.capability_token", "Capability Token Manager"),
        ("cie.ui.app", "Streamlit UI"),
    ]

    for module_name, display_name in modules_to_test:
        try:
            __import__(module_name)
            results.append(ValidationResult(
                category="Imports",
                check_name=display_name,
                status="PASS",
                message=f"✓ {display_name} module imported successfully",
            ))
        except ImportError as e:
            results.append(ValidationResult(
                category="Imports",
                check_name=display_name,
                status="FAIL",
                message=f"✗ Failed to import {display_name}: {e}",
                details={"error": str(e)}
            ))
        except Exception as e:
            results.append(ValidationResult(
                category="Imports",
                check_name=display_name,
                status="WARN",
                message=f"⚠ Warning importing {display_name}: {e}",
                details={"error": str(e)}
            ))

    return results


def validate_test_data() -> list[ValidationResult]:
    """Verify test dataset exists and is valid."""
    results = []
    test_data_path = Path("test_data/health_screening_japan.csv")

    # Check file exists
    if test_data_path.exists():
        results.append(ValidationResult(
            category="Test Data",
            check_name="File exists",
            status="PASS",
            message=f"✓ Test dataset found at {test_data_path}",
        ))
    else:
        results.append(ValidationResult(
            category="Test Data",
            check_name="File exists",
            status="FAIL",
            message=f"✗ Test dataset not found at {test_data_path}",
        ))
        return results

    # Check file is readable and has content
    try:
        import pandas as pd
        df = pd.read_csv(test_data_path)
        results.append(ValidationResult(
            category="Test Data",
            check_name="Data loading",
            status="PASS",
            message=f"✓ Test dataset loaded: {len(df)} rows, {len(df.columns)} columns",
            details={
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": list(df.columns)[:10] + (["..."] if len(df.columns) > 10 else [])
            }
        ))

        # Check required columns
        required_columns = ['患者ID', '施設コード', '検査年', '年齢', '性別']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if not missing_columns:
            results.append(ValidationResult(
                category="Test Data",
                check_name="Required columns",
                status="PASS",
                message=f"✓ All required columns present",
            ))
        else:
            results.append(ValidationResult(
                category="Test Data",
                check_name="Required columns",
                status="FAIL",
                message=f"✗ Missing columns: {missing_columns}",
            ))

        # Check for PII (患者氏名)
        if '患者氏名' in df.columns:
            results.append(ValidationResult(
                category="Test Data",
                check_name="PII (patient names)",
                status="PASS",
                message=f"✓ Patient names present (Layer 2 NLP detection can be tested)",
                details={"sample_names": df['患者氏名'].head(3).tolist()}
            ))
        else:
            results.append(ValidationResult(
                category="Test Data",
                check_name="PII (patient names)",
                status="WARN",
                message=f"⚠ Patient names column not found (PII detection testing limited)",
            ))

        # Check for missing data
        missing_rate = df.isnull().sum() / len(df)
        high_missing = missing_rate[missing_rate > 0.2]
        if len(high_missing) > 0:
            results.append(ValidationResult(
                category="Test Data",
                check_name="Data quality",
                status="WARN",
                message=f"⚠ Columns with >20% missing: {high_missing.index.tolist()}",
                details={"missing_rates": high_missing.to_dict()}
            ))
        else:
            results.append(ValidationResult(
                category="Test Data",
                check_name="Data quality",
                status="PASS",
                message=f"✓ No columns with excessive missing data",
            ))

    except Exception as e:
        results.append(ValidationResult(
            category="Test Data",
            check_name="Data loading",
            status="FAIL",
            message=f"✗ Failed to load test data: {e}",
            details={"error": str(e)}
        ))

    return results


def validate_configuration() -> list[ValidationResult]:
    """Verify configuration system is set up."""
    results = []

    try:
        from cie.core.config import CIEConfig
        config = CIEConfig()
        results.append(ValidationResult(
            category="Configuration",
            check_name="CIE Config loading",
            status="PASS",
            message=f"✓ Configuration loaded successfully",
            details={
                "database": str(config.database_filepath),
                "workspace": str(config.workspace_directory),
            }
        ))
    except Exception as e:
        results.append(ValidationResult(
            category="Configuration",
            check_name="CIE Config loading",
            status="FAIL",
            message=f"✗ Failed to load configuration: {e}",
            details={"error": str(e)}
        ))

    return results


def validate_schemas() -> list[ValidationResult]:
    """Verify schema files exist and are valid."""
    results = []
    schemas_dir = Path("cie/schemas")

    if not schemas_dir.exists():
        results.append(ValidationResult(
            category="Schemas",
            check_name="Schema directory",
            status="FAIL",
            message=f"✗ Schema directory not found at {schemas_dir}",
        ))
        return results

    schema_files = list(schemas_dir.glob("*.json")) + list(schemas_dir.glob("*.yaml"))
    if schema_files:
        results.append(ValidationResult(
            category="Schemas",
            check_name="Schema files",
            status="PASS",
            message=f"✓ Found {len(schema_files)} schema files",
            details={"schemas": [f.name for f in schema_files[:10]]}
        ))
    else:
        results.append(ValidationResult(
            category="Schemas",
            check_name="Schema files",
            status="WARN",
            message=f"⚠ No schema files found in {schemas_dir}",
        ))

    return results


def validate_knowledge_base() -> list[ValidationResult]:
    """Verify knowledge base structure."""
    results = []
    knowledge_root = Path("knowledge")

    required_dirs = ["official", "institutional", "pending"]
    for dir_name in required_dirs:
        knowledge_dir = knowledge_root / dir_name
        if knowledge_dir.exists():
            results.append(ValidationResult(
                category="Knowledge Base",
                check_name=f"{dir_name} directory",
                status="PASS",
                message=f"✓ Knowledge {dir_name} directory exists",
            ))
        else:
            results.append(ValidationResult(
                category="Knowledge Base",
                check_name=f"{dir_name} directory",
                status="WARN",
                message=f"⚠ Knowledge {dir_name} directory not found (will be created at runtime)",
            ))

    return results


def validate_decisions() -> list[ValidationResult]:
    """Verify Architecture Decision Records are in place."""
    results = []
    decisions_dir = Path("decisions")

    if not decisions_dir.exists():
        results.append(ValidationResult(
            category="Decisions",
            check_name="Decision directory",
            status="FAIL",
            message=f"✗ Decisions directory not found",
        ))
        return results

    required_decisions = [
        "ADR-0001.md",  # Planner responsibility
        "ADR-0002.md",  # Meta-Skills
        "ADR-0003.md",  # Knowledge ingestion
    ]

    for decision_file in required_decisions:
        decision_path = decisions_dir / decision_file
        if decision_path.exists():
            results.append(ValidationResult(
                category="Decisions",
                check_name=decision_file,
                status="PASS",
                message=f"✓ {decision_file} present",
            ))
        else:
            results.append(ValidationResult(
                category="Decisions",
                check_name=decision_file,
                status="WARN",
                message=f"⚠ {decision_file} not found",
            ))

    return results


def validate_skills() -> list[ValidationResult]:
    """Verify skill definitions exist."""
    results = []
    skills_dir = Path("cie/skills")

    if not skills_dir.exists():
        results.append(ValidationResult(
            category="Skills",
            check_name="Skills directory",
            status="FAIL",
            message=f"✗ Skills directory not found",
        ))
        return results

    skill_files = list(skills_dir.glob("*.py"))
    if skill_files:
        results.append(ValidationResult(
            category="Skills",
            check_name="Skill modules",
            status="PASS",
            message=f"✓ Found {len(skill_files)} skill modules",
            details={"skills": [f.stem for f in skill_files]}
        ))
    else:
        results.append(ValidationResult(
            category="Skills",
            check_name="Skill modules",
            status="WARN",
            message=f"⚠ No skill modules found",
        ))

    return results


def main() -> int:
    """Run all validation checks."""
    print("=" * 80)
    print("CIE Platform — Application Structure Validation")
    print("=" * 80)
    print()

    all_results = []
    all_results.extend(validate_imports())
    all_results.extend(validate_test_data())
    all_results.extend(validate_configuration())
    all_results.extend(validate_schemas())
    all_results.extend(validate_knowledge_base())
    all_results.extend(validate_decisions())
    all_results.extend(validate_skills())

    # Organize by category
    by_category = {}
    for result in all_results:
        if result.category not in by_category:
            by_category[result.category] = []
        by_category[result.category].append(result)

    # Print results
    for category in sorted(by_category.keys()):
        print(f"\n📋 {category}")
        print("-" * 80)
        for result in by_category[category]:
            print(f"  {result.message}")
            if result.details:
                for key, value in result.details.items():
                    if isinstance(value, list) and len(value) > 3:
                        print(f"     {key}: {value[:3]} + {len(value)-3} more")
                    else:
                        print(f"     {key}: {value}")

    # Summary
    print("\n" + "=" * 80)
    pass_count = sum(1 for r in all_results if r.status == "PASS")
    fail_count = sum(1 for r in all_results if r.status == "FAIL")
    warn_count = sum(1 for r in all_results if r.status == "WARN")
    total = len(all_results)

    print(f"Summary: {pass_count}/{total} checks passed")
    if warn_count > 0:
        print(f"         {warn_count} warnings")
    if fail_count > 0:
        print(f"         {fail_count} failures")
    print()

    if fail_count > 0:
        print("⚠️  Some critical components are missing or not working.")
        print("    App cannot be run until failures are resolved.")
        return 1
    else:
        print("✅ All critical components are present and ready.")
        print("    App structure validation passed.")
        if warn_count > 0:
            print("    (Some non-critical warnings exist.)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
