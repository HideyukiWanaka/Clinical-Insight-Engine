"""tests/integration/test_definition_of_done.py

PROMPT 10-3: Definition of Done 自動検証テスト。

scripts/check_done.py の各チェック関数を pytest から呼び出し、
PROJECT_RULES.md Section 17 の全項目が満たされていることを検証する。

全テストがパスすることが Phase 10 完了の必要条件。
"""

from __future__ import annotations

from pathlib import Path

import pytest

# scripts/ は Python パッケージではないため直接 import する
import importlib.util
import sys

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
_CHECK_DONE_PATH = _SCRIPTS_DIR / "check_done.py"

# check_done モジュールを動的ロード
_spec = importlib.util.spec_from_file_location("check_done", _CHECK_DONE_PATH)
_check_done = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_check_done)  # type: ignore[union-attr]

PROJECT_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt(failures: list[str]) -> str:
    """Format failure list for pytest assertion messages."""
    if not failures:
        return ""
    lines = "\n  ".join(failures)
    return f"\nFound {len(failures)} issue(s):\n  {lines}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_manifest_files_exist():
    """MANIFEST.yaml で定義された全必須ファイル・ディレクトリが存在すること.

    PROJECT_RULES.md Section 17 — "Architecture remains consistent"
    """
    failures = _check_done.check_manifest_files(PROJECT_ROOT)
    assert failures == [], _fmt(failures)


def test_schemas_valid():
    """schemas/ 配下の全 JSON スキーマが有効な Draft-2020-12 JSON Schema であること.

    PROJECT_RULES.md Section 17 — "Schemas validate"
    """
    failures = _check_done.check_schema_validity(PROJECT_ROOT)
    assert failures == [], _fmt(failures)


def test_adr_exists():
    """ADR-0001〜ADR-0003 が decisions/ に存在すること.

    PROJECT_RULES.md Section 17 — "Affected ADR created if architecture changed"
    """
    failures = _check_done.check_adr_for_architecture_changes(PROJECT_ROOT)
    assert failures == [], _fmt(failures)


def test_skill_namespace_correct():
    """skills/ の 3 名前空間（core/meta/user）の構造が MANIFEST 定義と一致すること.

    PROJECT_RULES.md Section 17 — "Skill lifecycle process followed if any Skill was updated"
    ADR-0002 — core/ skills must have versions/ directory; meta/ includes knowledge-extractor/
    """
    failures = _check_done.check_skill_namespace_structure(PROJECT_ROOT)
    assert failures == [], _fmt(failures)


def test_no_workflow_id_in_planner():
    """agents/planner.yaml の strictly_forbidden に workflow_id_assignment が含まれること.

    ADR-0001 Principle 2: Orchestrator-Planner Responsibility Boundary.
    Planner は workflow_id を設定できない。
    """
    failures = _check_done.check_no_workflow_id_in_planner(PROJECT_ROOT)
    assert failures == [], _fmt(failures)


def test_skill_lifecycle_spec():
    """spec/skill-lifecycle.md が存在すること.

    ADR-0002 — Skill Lifecycle フローが仕様として定義されていること。
    """
    failures = _check_done.check_skill_lifecycle_spec_exists(PROJECT_ROOT)
    assert failures == [], _fmt(failures)


def test_permissions_yaml_has_skill_lifecycle_agent():
    """spec/permissions.yaml に skill_lifecycle エージェントが定義されていること.

    ADR-0002 — skill_lifecycle agent は skill.update_core / skill.register_user
    スコープを保持する唯一のエージェント（SP-003 Separation of Duties）。
    """
    failures = _check_done.check_permissions_yaml_skill_lifecycle(PROJECT_ROOT)
    assert failures == [], _fmt(failures)


# ---------------------------------------------------------------------------
# Composite: all checks pass in a single test (for CI gate use)
# ---------------------------------------------------------------------------


def test_all_dod_checks_pass():
    """Definition of Done の全 7 項目がクリアされていること.

    PROJECT_RULES.md Section 17: A task is complete only when ALL conditions are met.
    このテストが CI ゲートの主要チェックポイントとなる。
    """
    results = _check_done.run_checks(PROJECT_ROOT)
    all_failures: list[str] = []
    for category, failures in results.items():
        for failure in failures:
            all_failures.append(f"[{category}] {failure}")

    assert all_failures == [], (
        f"Definition of Done is NOT complete. "
        f"{len(all_failures)} issue(s) remain:{_fmt(all_failures)}"
    )
