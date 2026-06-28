"""Unit tests for cie.evaluation.security.SecurityEvaluator.

Tests cover SEC-001 through SEC-006 and the breach override policy.
Run with: pytest tests/unit/test_security_evaluator.py -v
"""

from __future__ import annotations

import pytest

from cie.evaluation.base import EvaluationDimension
from cie.evaluation.security import SecurityEvaluator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def evaluator() -> SecurityEvaluator:
    return SecurityEvaluator()


def _make_artifacts(
    *,
    r_script: str = "set.seed(42)\nresult <- t.test(df$var_1, df$var_2)",
    pii_checks_performed: bool = True,
    audit_events: list | None = None,
    context_payloads: list | None = None,
    breach_events: int = 0,
    report_content: str = "The mean age was 65.2 years (SD 10.1).",
) -> dict:
    """Build a minimal valid artifact dict for SecurityEvaluator tests."""
    if audit_events is None:
        audit_events = [
            {"action": "token_issued", "token_id": "tok-001", "severity": "INFO"},
            {"action": "token_revoked", "token_id": "tok-001", "severity": "INFO"},
        ]
    if context_payloads is None:
        context_payloads = [{"intent_object": {"objective": "comparison"}}]

    return {
        "r_script_content": r_script,
        "quality_report": {
            "pii_checks_performed": pii_checks_performed,
        },
        "audit_events": audit_events,
        "context_payloads": context_payloads,
        "security_report": {
            "breach_events": breach_events,
        },
        "report_content": report_content,
    }


# ---------------------------------------------------------------------------
# Evaluator metadata
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_dimension(self, evaluator: SecurityEvaluator) -> None:
        assert evaluator.dimension == EvaluationDimension.SECURITY

    def test_weight_pct(self, evaluator: SecurityEvaluator) -> None:
        """Weight must be 15 per evaluation/security.yaml."""
        assert evaluator.weight_pct == 15


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestCleanExecution:
    def test_clean_execution_passes_all_sec_checks(
        self, evaluator: SecurityEvaluator
    ) -> None:
        """Clean execution with no violations passes all checks."""
        result = evaluator.evaluate(_make_artifacts())

        # Filter out the optional breach-override synthetic check
        real_checks = [c for c in result.check_results if c.check_id != "SEC-BREACH-OVERRIDE"]
        assert all(c.passed for c in real_checks)
        assert result.score > 0.0
        assert result.critical_failure is False


# ---------------------------------------------------------------------------
# SEC-001: var_n alias enforcement
# ---------------------------------------------------------------------------

class TestSEC001:
    def test_original_colname_in_script_fails_sec001(
        self, evaluator: SecurityEvaluator
    ) -> None:
        """R script using df$original_age must fail SEC-001."""
        r_script = 'set.seed(42)\nresult <- t.test(df$original_age, df$group)'
        artifacts = _make_artifacts(r_script=r_script)
        result = evaluator.evaluate(artifacts)

        sec001 = next(r for r in result.check_results if r.check_id == "SEC-001")
        assert sec001.passed is False
        assert sec001.severity == "critical"

    def test_var_n_aliases_pass_sec001(self, evaluator: SecurityEvaluator) -> None:
        r_script = 'set.seed(42)\nresult <- t.test(df$var_1 ~ df$var_2)'
        artifacts = _make_artifacts(r_script=r_script)
        result = evaluator.evaluate(artifacts)

        sec001 = next(r for r in result.check_results if r.check_id == "SEC-001")
        assert sec001.passed is True

    def test_double_bracket_access_detected(
        self, evaluator: SecurityEvaluator
    ) -> None:
        """df[["original_name"]] must also be detected."""
        r_script = 'set.seed(42)\nx <- df[["patient_id"]]'
        artifacts = _make_artifacts(r_script=r_script)
        result = evaluator.evaluate(artifacts)

        sec001 = next(r for r in result.check_results if r.check_id == "SEC-001")
        assert sec001.passed is False

    def test_empty_script_fails_sec001(self, evaluator: SecurityEvaluator) -> None:
        artifacts = _make_artifacts(r_script="")
        result = evaluator.evaluate(artifacts)
        sec001 = next(r for r in result.check_results if r.check_id == "SEC-001")
        assert sec001.passed is False


# ---------------------------------------------------------------------------
# SEC-002: PII detection filter
# ---------------------------------------------------------------------------

class TestSEC002:
    def test_pii_check_not_performed_fails_sec002(
        self, evaluator: SecurityEvaluator
    ) -> None:
        """pii_checks_performed=False must trigger SEC-002 critical failure."""
        artifacts = _make_artifacts(pii_checks_performed=False)
        result = evaluator.evaluate(artifacts)

        sec002 = next(r for r in result.check_results if r.check_id == "SEC-002")
        assert sec002.passed is False
        assert sec002.severity == "critical"

    def test_pii_check_performed_passes(self, evaluator: SecurityEvaluator) -> None:
        artifacts = _make_artifacts(pii_checks_performed=True)
        result = evaluator.evaluate(artifacts)

        sec002 = next(r for r in result.check_results if r.check_id == "SEC-002")
        assert sec002.passed is True

    def test_pii_check_none_fails(self, evaluator: SecurityEvaluator) -> None:
        artifacts = _make_artifacts(pii_checks_performed=None)
        result = evaluator.evaluate(artifacts)

        sec002 = next(r for r in result.check_results if r.check_id == "SEC-002")
        assert sec002.passed is False


# ---------------------------------------------------------------------------
# SEC-003: BREACH events in audit log
# ---------------------------------------------------------------------------

class TestSEC003:
    def test_breach_event_fails_sec003(self, evaluator: SecurityEvaluator) -> None:
        """BREACH-severity event in audit log must fail SEC-003."""
        breach_events = [
            {"action": "token_issued", "token_id": "tok-001", "severity": "INFO"},
            {"action": "BREACH_ATTEMPT", "token_id": "tok-002", "severity": "BREACH"},
        ]
        artifacts = _make_artifacts(audit_events=breach_events)
        result = evaluator.evaluate(artifacts)

        sec003 = next(r for r in result.check_results if r.check_id == "SEC-003")
        assert sec003.passed is False
        assert sec003.severity == "critical"

    def test_no_breach_events_passes(self, evaluator: SecurityEvaluator) -> None:
        artifacts = _make_artifacts(
            audit_events=[{"action": "workflow_started", "severity": "INFO"}]
        )
        result = evaluator.evaluate(artifacts)

        sec003 = next(r for r in result.check_results if r.check_id == "SEC-003")
        assert sec003.passed is True

    def test_empty_audit_log_passes(self, evaluator: SecurityEvaluator) -> None:
        artifacts = _make_artifacts(audit_events=[])
        result = evaluator.evaluate(artifacts)

        sec003 = next(r for r in result.check_results if r.check_id == "SEC-003")
        assert sec003.passed is True


# ---------------------------------------------------------------------------
# SEC-004: raw_data_rows injection check
# ---------------------------------------------------------------------------

class TestSEC004:
    def test_raw_data_rows_in_context_fails_sec004(
        self, evaluator: SecurityEvaluator
    ) -> None:
        """Context payload containing raw_data_rows must fail SEC-004."""
        context_payloads = [
            {"intent_object": {}},
            {"raw_data_rows": [{"id": 1, "name": "Patient A"}]},  # violation
        ]
        artifacts = _make_artifacts(context_payloads=context_payloads)
        result = evaluator.evaluate(artifacts)

        sec004 = next(r for r in result.check_results if r.check_id == "SEC-004")
        assert sec004.passed is False
        assert sec004.severity == "critical"

    def test_clean_context_passes(self, evaluator: SecurityEvaluator) -> None:
        context_payloads = [
            {"intent_object": {"objective": "comparison"}},
            {"analysis_plan": {}},
        ]
        artifacts = _make_artifacts(context_payloads=context_payloads)
        result = evaluator.evaluate(artifacts)

        sec004 = next(r for r in result.check_results if r.check_id == "SEC-004")
        assert sec004.passed is True

    def test_empty_payloads_passes(self, evaluator: SecurityEvaluator) -> None:
        artifacts = _make_artifacts(context_payloads=[])
        result = evaluator.evaluate(artifacts)

        sec004 = next(r for r in result.check_results if r.check_id == "SEC-004")
        assert sec004.passed is True


# ---------------------------------------------------------------------------
# SEC-005: Token pair balance (advisory)
# ---------------------------------------------------------------------------

class TestSEC005:
    def test_unrevoked_token_fails_sec005(self, evaluator: SecurityEvaluator) -> None:
        audit_events = [
            {"action": "token_issued", "token_id": "tok-001"},
            {"action": "token_issued", "token_id": "tok-002"},
            {"action": "token_revoked", "token_id": "tok-001"},
            # tok-002 not revoked
        ]
        artifacts = _make_artifacts(audit_events=audit_events)
        result = evaluator.evaluate(artifacts)

        sec005 = next(r for r in result.check_results if r.check_id == "SEC-005")
        assert sec005.passed is False
        assert sec005.severity == "advisory"
        # advisory only — score > 0
        assert result.critical_failure is False

    def test_balanced_tokens_passes(self, evaluator: SecurityEvaluator) -> None:
        audit_events = [
            {"action": "token_issued", "token_id": "tok-001"},
            {"action": "token_revoked", "token_id": "tok-001"},
            {"action": "token_issued", "token_id": "tok-002"},
            {"action": "token_revoked", "token_id": "tok-002"},
        ]
        artifacts = _make_artifacts(audit_events=audit_events)
        result = evaluator.evaluate(artifacts)

        sec005 = next(r for r in result.check_results if r.check_id == "SEC-005")
        assert sec005.passed is True


# ---------------------------------------------------------------------------
# Breach override policy (security.yaml §breach_override_policy)
# ---------------------------------------------------------------------------

class TestBreachOverride:
    def test_breach_events_forces_score_zero(
        self, evaluator: SecurityEvaluator
    ) -> None:
        """breach_events > 0 must force total score to 0.0 regardless of checks."""
        # All other checks would pass, but breach_events=1 overrides
        artifacts = _make_artifacts(breach_events=1)
        result = evaluator.evaluate(artifacts)

        assert result.score == 0.0
        assert result.critical_failure is True

    def test_zero_breach_events_no_override(self, evaluator: SecurityEvaluator) -> None:
        artifacts = _make_artifacts(breach_events=0)
        result = evaluator.evaluate(artifacts)

        # With no violations, score should be > 0
        assert result.score > 0.0

    def test_breach_override_adds_synthetic_check(
        self, evaluator: SecurityEvaluator
    ) -> None:
        """Breach override must add a SEC-BREACH-OVERRIDE check for traceability."""
        artifacts = _make_artifacts(breach_events=2)
        result = evaluator.evaluate(artifacts)

        override_check = next(
            (r for r in result.check_results if r.check_id == "SEC-BREACH-OVERRIDE"),
            None,
        )
        assert override_check is not None
        assert override_check.passed is False
        assert "2" in override_check.message  # breach count in message


# ---------------------------------------------------------------------------
# SEC-006: var_n aliases in final report
# ---------------------------------------------------------------------------

class TestSEC006:
    def test_var_n_in_report_fails_sec006(self, evaluator: SecurityEvaluator) -> None:
        """Report containing var_1 etc. indicates failed restore → SEC-006 fails."""
        report = "The variable var_1 showed significant difference (p=0.03)."
        artifacts = _make_artifacts(report_content=report)
        result = evaluator.evaluate(artifacts)

        sec006 = next(r for r in result.check_results if r.check_id == "SEC-006")
        assert sec006.passed is False
        assert sec006.severity == "critical"

    def test_clean_report_passes_sec006(self, evaluator: SecurityEvaluator) -> None:
        report = "Age showed significant difference between groups (p=0.03, d=0.45)."
        artifacts = _make_artifacts(report_content=report)
        result = evaluator.evaluate(artifacts)

        sec006 = next(r for r in result.check_results if r.check_id == "SEC-006")
        assert sec006.passed is True

    def test_empty_report_skips_check(self, evaluator: SecurityEvaluator) -> None:
        artifacts = _make_artifacts(report_content="")
        result = evaluator.evaluate(artifacts)

        sec006 = next(r for r in result.check_results if r.check_id == "SEC-006")
        assert sec006.passed is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_artifacts_no_exception(self, evaluator: SecurityEvaluator) -> None:
        result = evaluator.evaluate({})
        # Should not raise; SEC-001 and SEC-002 will fail → score = 0
        assert result.score == 0.0

    def test_weight_is_15(self, evaluator: SecurityEvaluator) -> None:
        result = evaluator.evaluate(_make_artifacts())
        assert result.weight_pct == 15
