"""Unit tests for cie.security.pii_detector — Layer 1 (regex/dictionary).

Test matrix:
- test_jp_full_name_detected           — "氏名" → CRITICAL finding
- test_patient_id_detected             — "患者ID" → CRITICAL finding
- test_birth_date_detected             — "生年月日" → CRITICAL finding
- test_phone_column_detected           — "電話番号" → CRITICAL finding
- test_email_column_detected           — "メールアドレス" → CRITICAL finding
- test_free_text_warning               — "備考" → WARNING finding
- test_age_detail_warning              — "年齢詳細" → WARNING finding
- test_phone_value_detected            — phone-format value → CRITICAL, "[REDACTED]"
- test_email_value_detected            — email-format value → CRITICAL, "[REDACTED]"
- test_safe_column_passes              — "sbp_mmhg" → empty findings
- test_matched_text_redacted_for_values — category value match always "[REDACTED]"
"""

from __future__ import annotations

import pytest

from cie.security.pii_detector import PIIDetectorLayer1, PIIFinding


@pytest.fixture(scope="module")
def detector() -> PIIDetectorLayer1:
    """Shared detector instance (patterns compiled once)."""
    return PIIDetectorLayer1()


# ---------------------------------------------------------------------------
# Column name — CRITICAL patterns
# ---------------------------------------------------------------------------


def test_jp_full_name_detected(detector: PIIDetectorLayer1) -> None:
    findings = detector.detect_column_name("氏名")
    assert findings, "Expected CRITICAL finding for 氏名"
    assert any(f.severity == "CRITICAL" for f in findings)
    assert any(f.pattern_id == "jp_full_name" for f in findings)


def test_patient_id_detected(detector: PIIDetectorLayer1) -> None:
    findings = detector.detect_column_name("患者ID")
    assert findings, "Expected CRITICAL finding for 患者ID"
    assert any(f.severity == "CRITICAL" for f in findings)
    assert any(f.pattern_id == "patient_id" for f in findings)


def test_birth_date_detected(detector: PIIDetectorLayer1) -> None:
    findings = detector.detect_column_name("生年月日")
    assert findings, "Expected CRITICAL finding for 生年月日"
    assert any(f.severity == "CRITICAL" for f in findings)
    assert any(f.pattern_id == "birth_date" for f in findings)


def test_phone_column_detected(detector: PIIDetectorLayer1) -> None:
    findings = detector.detect_column_name("電話番号")
    assert findings, "Expected CRITICAL finding for 電話番号"
    assert any(f.severity == "CRITICAL" for f in findings)
    assert any(f.pattern_id == "phone_number" for f in findings)


def test_email_column_detected(detector: PIIDetectorLayer1) -> None:
    findings = detector.detect_column_name("メールアドレス")
    assert findings, "Expected CRITICAL finding for メールアドレス"
    assert any(f.severity == "CRITICAL" for f in findings)
    assert any(f.pattern_id == "email" for f in findings)


# ---------------------------------------------------------------------------
# Column name — WARNING patterns
# ---------------------------------------------------------------------------


def test_free_text_warning(detector: PIIDetectorLayer1) -> None:
    findings = detector.detect_column_name("備考")
    assert findings, "Expected WARNING finding for 備考"
    assert any(f.severity == "WARNING" for f in findings)
    assert any(f.pattern_id == "free_text" for f in findings)


def test_age_detail_warning(detector: PIIDetectorLayer1) -> None:
    findings = detector.detect_column_name("年齢詳細")
    assert findings, "Expected WARNING finding for 年齢詳細"
    assert any(f.severity == "WARNING" for f in findings)
    assert any(f.pattern_id == "age_detail" for f in findings)


# ---------------------------------------------------------------------------
# Category label — value patterns
# ---------------------------------------------------------------------------


def test_phone_value_detected(detector: PIIDetectorLayer1) -> None:
    categories = [{"label": "090-1234-5678", "count": 1}]
    findings = detector.detect_category_labels(categories)
    assert findings, "Expected CRITICAL finding for phone-format category label"
    assert all(f.severity == "CRITICAL" for f in findings)
    assert all(f.matched_text == "[REDACTED]" for f in findings)
    assert any(f.pattern_id == "value_phone_pattern" for f in findings)


def test_email_value_detected(detector: PIIDetectorLayer1) -> None:
    categories = [{"label": "taro.yamada@example.com", "count": 1}]
    findings = detector.detect_category_labels(categories)
    assert findings, "Expected CRITICAL finding for email-format category label"
    assert all(f.severity == "CRITICAL" for f in findings)
    assert all(f.matched_text == "[REDACTED]" for f in findings)
    assert any(f.pattern_id == "value_email_pattern" for f in findings)


# ---------------------------------------------------------------------------
# Safe column — no findings
# ---------------------------------------------------------------------------


def test_safe_column_passes(detector: PIIDetectorLayer1) -> None:
    findings = detector.detect("sbp_mmhg")
    assert findings == [], f"Expected no findings for sbp_mmhg, got {findings}"


# ---------------------------------------------------------------------------
# Invariant: category value matched_text must always be "[REDACTED]"
# ---------------------------------------------------------------------------


def test_matched_text_redacted_for_values(detector: PIIDetectorLayer1) -> None:
    """Regardless of which pattern fires, category label findings must redact the value."""
    categories = [
        {"label": "090-9876-5432", "count": 2},
        {"label": "hanako@clinic.jp", "count": 1},
    ]
    findings = detector.detect_category_labels(categories)
    assert findings, "Expected findings for phone/email category labels"
    for f in findings:
        assert f.matched_text == "[REDACTED]", (
            f"Category value finding must use '[REDACTED]', got '{f.matched_text}'"
        )
        assert f.target_type == "category_value"
