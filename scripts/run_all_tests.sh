#!/bin/bash
# CIE Platform — 全テスト実行スクリプト
# 使用法: ./scripts/run_all_tests.sh [--skip-dod]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "================================================"
echo "CIE Platform — Full Test Suite"
echo "================================================"

# ── [1/4] Definition of Done チェック ────────────────────────────────────
echo ""
echo "[1/4] Definition of Done チェック"
if [[ "${1}" == "--skip-dod" ]]; then
    echo "  (skipped)"
else
    python scripts/check_done.py
fi

# ── [2/4] Unit Tests ─────────────────────────────────────────────────────
echo ""
echo "[2/4] Unit Tests"
pytest tests/unit/ -v --tb=short \
  --cov=cie \
  --cov-report=term-missing \
  --cov-fail-under=80

# ── [3/4] Integration Tests ──────────────────────────────────────────────
echo ""
echo "[3/4] Integration Tests"
pytest tests/integration/ -v --tb=short

# ── [4/4] Schema Validation ──────────────────────────────────────────────
echo ""
echo "[4/4] Schema Validation"
python -c "
from pathlib import Path
from cie.schemas.validator import SchemaRegistry
registry = SchemaRegistry(schema_dir=Path('schemas'))
registry.load()
count = len(registry._schemas)
print(f'  ✅ {count} schemas loaded and validated')
"

echo ""
echo "================================================"
echo "✅ 全テスト完了"
echo "================================================"
