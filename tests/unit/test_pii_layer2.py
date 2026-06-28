"""Unit tests for cie.security.pii_detector_layer2 and cie.security.pii_filter.

Test matrix:
- test_high_uniqueness_text_detected       — unique_count/row_count=0.98, text → CRITICAL
- test_date_type_warning                   — inferred_type=date → WARNING
- test_fixed_length_numeric_detected       — 10-digit numeric categories ×3 → CRITICAL
- test_low_uniqueness_passes               — ratio=0.5 → empty findings
- test_row_count_zero_safe                 — row_count=0 → no error, empty list
- test_none_summary_stats_safe             — summary_stats=None → L2-HIGH-UNIQUENESS skipped
- test_continuous_high_uniqueness_warning  — continuous, ratio>0.99 → WARNING
- test_pii_filter_run_integration          — Layer 1+2 combined run
"""

from __future__ import annotations

import pytest

from cie.schemas.payloads import ColumnMetadata
from cie.security.pii_detector import PIIFinding
from cie.security.pii_detector_layer2 import PIIDetectorLayer2
from cie.security.pii_filter import PIIFilter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _col(
    var_n: str = "var_1",
    inferred_type: str = "text",
    missing_count: int = 0,
    missing_rate_pct: float = 0.0,
    summary_stats: dict | None = None,
) -> ColumnMetadata:
    return ColumnMetadata(
        var_n=var_n,
        inferred_type=inferred_type,
        missing_count=missing_count,
        missing_rate_pct=missing_rate_pct,
        summary_stats=summary_stats,
    )


@pytest.fixture(scope="module")
def layer2() -> PIIDetectorLayer2:
    return PIIDetectorLayer2()


# ---------------------------------------------------------------------------
# Signal 1: L2-HIGH-UNIQUENESS
# ---------------------------------------------------------------------------


def test_high_uniqueness_text_detected(layer2: PIIDetectorLayer2) -> None:
    col = _col(
        inferred_type="text",
        summary_stats={"unique_count": 98, "top_categories": []},
    )
    findings = layer2.detect(col, row_count=100)
    assert any(f.signal_id == "L2-HIGH-UNIQUENESS" for f in findings)
    assert any(f.severity == "CRITICAL" for f in findings)


def test_low_uniqueness_passes(layer2: PIIDetectorLayer2) -> None:
    col = _col(
        inferred_type="text",
        summary_stats={"unique_count": 50, "top_categories": []},
    )
    findings = layer2.detect(col, row_count=100)
    l2_hu = [f for f in findings if f.signal_id == "L2-HIGH-UNIQUENESS"]
    assert not l2_hu, "Uniqueness ratio 0.5 must not trigger L2-HIGH-UNIQUENESS"


# ---------------------------------------------------------------------------
# Signal 2: L2-DATE-TYPE
# ---------------------------------------------------------------------------


def test_date_type_warning(layer2: PIIDetectorLayer2) -> None:
    col = _col(inferred_type="date")
    findings = layer2.detect(col, row_count=100)
    assert any(f.signal_id == "L2-DATE-TYPE" for f in findings)
    assert any(f.severity == "WARNING" for f in findings)


# ---------------------------------------------------------------------------
# Signal 3: L2-FIXED-LENGTH-NUMERIC
# ---------------------------------------------------------------------------


def test_fixed_length_numeric_detected(layer2: PIIDetectorLayer2) -> None:
    col = _col(
        inferred_type="categorical_nominal",
        summary_stats={
            "unique_count": 200,
            "top_categories": [
                {"label": "1234567890", "count": 3},
                {"label": "9876543210", "count": 2},
                {"label": "1111111111", "count": 1},
            ],
        },
    )
    findings = layer2.detect(col, row_count=200)
    assert any(f.signal_id == "L2-FIXED-LENGTH-NUMERIC" for f in findings)
    assert any(f.severity == "CRITICAL" for f in findings)


# ---------------------------------------------------------------------------
# Signal 4: L2-HIGH-UNIQUENESS-CONTINUOUS
# ---------------------------------------------------------------------------


def test_continuous_high_uniqueness_warning(layer2: PIIDetectorLayer2) -> None:
    col = _col(
        inferred_type="continuous",
        summary_stats={"unique_count": 999, "top_categories": []},
    )
    findings = layer2.detect(col, row_count=1000)
    assert any(f.signal_id == "L2-HIGH-UNIQUENESS-CONTINUOUS" for f in findings)
    assert any(f.severity == "WARNING" for f in findings)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_row_count_zero_safe(layer2: PIIDetectorLayer2) -> None:
    col = _col(
        inferred_type="text",
        summary_stats={"unique_count": 10, "top_categories": []},
    )
    findings = layer2.detect(col, row_count=0)
    assert findings == [], "row_count=0 must return empty list without error"


def test_none_summary_stats_safe(layer2: PIIDetectorLayer2) -> None:
    col = _col(inferred_type="text", summary_stats=None)
    findings = layer2.detect(col, row_count=100)
    l2_hu = [f for f in findings if f.signal_id == "L2-HIGH-UNIQUENESS"]
    assert not l2_hu, "L2-HIGH-UNIQUENESS must be skipped when summary_stats is None"


# ---------------------------------------------------------------------------
# Integration: PIIFilter (Layer 1 + Layer 2)
# ---------------------------------------------------------------------------


def test_pii_filter_run_integration() -> None:
    """PIIFilter.run() correctly partitions critical and warning findings."""
    pii_filter = PIIFilter(enable_layer2=True)

    # Column named "患者ID" (Layer 1 CRITICAL) + high uniqueness (Layer 2 CRITICAL)
    col = _col(
        var_n="var_1",
        inferred_type="text",
        summary_stats={"unique_count": 99, "top_categories": []},
    )
    critical, warnings = pii_filter.run("患者ID", col, row_count=100)

    assert critical, "Expected at least one CRITICAL finding"
    assert all(f.severity == "CRITICAL" for f in critical)
    assert all(f.severity == "WARNING" for f in warnings)

    signal_ids = {f.signal_id for f in critical}
    pattern_ids = {f.pattern_id for f in critical}
    assert "patient_id" in pattern_ids or "L2-HIGH-UNIQUENESS" in signal_ids, (
        "Expected Layer 1 patient_id pattern or Layer 2 L2-HIGH-UNIQUENESS signal"
    )
