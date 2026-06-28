"""CIE Platform — Security & Privacy Compliance Evaluator.

Implements the Security evaluation dimension (weight_pct=15).
Checks SEC-001 through SEC-006 as defined in evaluation/security.yaml.

Critical design constraint (security.yaml §breach_override_policy):
  If security_report_section.breach_events > 0, the entire score is
  forced to zero regardless of all other dimension results.
  This is implemented in _apply_breach_override().

Architecture note:
  SEC-001: var_n alias enforcement — any column name NOT matching the
  pattern "var_[0-9]+" in the R script is treated as a potential
  original column name exposure. Japanese/non-ASCII identifiers used
  as column names fail immediately (per prompt constraint).
"""

from __future__ import annotations

import re

from cie.evaluation.base import (
    BaseEvaluator,
    CheckResult,
    DimensionScore,
    EvaluationDimension,
)

# Pattern for valid var_n aliases: var_1, var_12, var_999, etc.
_VAR_N_PATTERN = re.compile(r"\bvar_[0-9]+\b")

# R column accessor patterns that might reference original column names
# e.g.  df$colname,  df[["colname"]],  df[, "colname"]
_R_COLUMN_ACCESS_PATTERNS = [
    re.compile(r'\$([A-Za-z_\u3000-\u9fff][A-Za-z0-9_\u3000-\u9fff]*)'),  # df$colname
    re.compile(r'\[\["([^"]+)"\]\]'),   # df[["colname"]]
    re.compile(r'\[,\s*"([^"]+)"\]'),   # df[, "colname"]
    re.compile(r'\[,\s*\'([^\']+)\'\]'),# df[, 'colname']
]

# Forbidden R functions (runtime isolation, security.yaml SEC-003-B)
_FORBIDDEN_R_FUNCTIONS = frozenset({
    "system",
    "system2",
    "shell",
    "Sys.setenv",
    "download.file",
    "readLines",   # external URL reads
})


class SecurityEvaluator(BaseEvaluator):
    """Security and privacy compliance evaluator.

    Dimension: SECURITY (weight_pct = 15).

    Runs checks SEC-001 through SEC-006.

    Critical override: if breach_events > 0 in the security report,
    score is forced to 0.0 regardless of individual check results.

    Expected artifact keys:
        - "r_script_content" (str): R script text.
        - "quality_report" (dict): From Data Quality Agent.
            Must contain: pii_checks_performed (bool).
        - "audit_events" (list[dict]): From AuditService.
            Each event: {"action": str, "severity": str | None, ...}.
        - "context_payloads" (list[dict]): Agent context payloads
            from Orchestrator. Used to verify raw_data_rows absence.
        - "security_report" (dict): From Security Agent.
            May contain: breach_events (int).
        - "report_content" (str): Final manuscript/report text.
            Used for SEC-006 (column name in report check).
    """

    @property
    def dimension(self) -> EvaluationDimension:
        """Returns SECURITY."""
        return EvaluationDimension.SECURITY

    @property
    def weight_pct(self) -> int:
        """Weight 15% per evaluation/security.yaml."""
        return 15

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def evaluate(self, artifacts: dict) -> DimensionScore:
        """Run SEC-001 through SEC-006 and return a DimensionScore.

        Breach override: if breach_events > 0, score is forced to 0.0.

        Args:
            artifacts: Artifact dict with security-relevant keys.

        Returns:
            DimensionScore with score in [0.0, 100.0].
        """
        r_script: str = artifacts.get("r_script_content") or ""
        quality_report: dict = artifacts.get("quality_report") or {}
        audit_events: list[dict] = artifacts.get("audit_events") or []
        context_payloads: list[dict] = artifacts.get("context_payloads") or []
        security_report: dict = artifacts.get("security_report") or {}
        report_content: str = artifacts.get("report_content") or ""

        checks: list[CheckResult] = [
            self._check_sec001(r_script),
            self._check_sec002(quality_report),
            self._check_sec003(audit_events),
            self._check_sec004(context_payloads),
            self._check_sec005(audit_events),
            self._check_sec006(report_content),
        ]

        # Breach override: security.yaml §breach_override_policy
        score = self._apply_breach_override(security_report, checks)
        critical_failure = score == 0.0

        return DimensionScore(
            dimension=self.dimension,
            score=score,
            weight_pct=self.weight_pct,
            check_results=checks,
            critical_failure=critical_failure,
        )

    # ------------------------------------------------------------------
    # Breach override (security.yaml §breach_override_policy)
    # ------------------------------------------------------------------

    def _apply_breach_override(
        self,
        security_report: dict,
        checks: list[CheckResult],
    ) -> float:
        """Force score to 0.0 if breach_events > 0.

        This override cannot be waived by any agent (security.yaml).

        Args:
            security_report: security_report_section dict.
            checks: All individual check results.

        Returns:
            Score (0.0 if breach override triggered, else _pass_score result).
        """
        breach_events = security_report.get("breach_events", 0)
        try:
            breach_count = int(breach_events)
        except (TypeError, ValueError):
            breach_count = 0

        if breach_count > 0:
            # Append a synthetic breach-override check for traceability
            checks.append(
                CheckResult(
                    check_id="SEC-BREACH-OVERRIDE",
                    dimension=self.dimension,
                    passed=False,
                    severity="critical",
                    message=(
                        f"SEC-BREACH-OVERRIDE: {breach_count} breach event(s) detected. "
                        "Score forced to 0.0 per security.yaml breach_override_policy. "
                        "Human escalation is mandatory."
                    ),
                    actual_value=str(breach_count),
                    expected_value="0",
                )
            )
            return 0.0

        return self._pass_score(checks)

    # ------------------------------------------------------------------
    # Individual checks (SEC-001 … SEC-006)
    # ------------------------------------------------------------------

    def _check_sec001(self, r_script: str) -> CheckResult:
        """SEC-001 (critical): R script must use var_n aliases only.

        No original column names (including Japanese/non-ASCII identifiers)
        may appear as column references in the R script.

        Source: security.yaml SEC-002-B (var_n alias enforcement).
        Prompt constraint: "日本語列名が1文字でもあればfailure".
        """
        if not r_script:
            return CheckResult(
                check_id="SEC-001",
                dimension=self.dimension,
                passed=False,
                severity="critical",
                message="SEC-001: r_script_content is empty; cannot verify column name compliance.",
            )

        violations: list[str] = []

        for pattern in _R_COLUMN_ACCESS_PATTERNS:
            for match in pattern.finditer(r_script):
                col_name = match.group(1)
                # Allow var_N pattern (valid alias) and common R meta-names
                if _VAR_N_PATTERN.fullmatch(col_name):
                    continue
                # Allow standard R data frame meta-columns
                if col_name in {"row.names", "rownames", "."}:
                    continue
                violations.append(col_name)

        # Additional check: any non-ASCII characters in column position = fail
        # (Japanese column names used as identifiers)
        non_ascii_cols = re.findall(
            r'\$([^\s\d\W]\w*[\u0080-\uffff]\w*)',
            r_script,
        )
        violations.extend(non_ascii_cols)

        violations = list(dict.fromkeys(violations))  # deduplicate, preserve order

        passed = len(violations) == 0
        message = (
            "SEC-001: All column references use var_n aliases only."
            if passed
            else (
                f"SEC-001: Non-var_n column name(s) detected in R script: "
                f"{violations[:5]}{'...' if len(violations) > 5 else ''}. "
                "Original column names must not appear in executed R code."
            )
        )

        return CheckResult(
            check_id="SEC-001",
            dimension=self.dimension,
            passed=passed,
            severity="critical",
            message=message,
            actual_value=str(violations[:5]) if violations else "none",
            expected_value="var_n aliases only",
        )

    def _check_sec002(self, quality_report: dict) -> CheckResult:
        """SEC-002 (critical): PII detection filter must have been executed.

        Source: security.yaml SEC-002-A (no raw patient record in logs).
        Prompt spec: SEC-002.
        """
        pii_checks_performed = quality_report.get("pii_checks_performed")

        passed = pii_checks_performed is True
        message = (
            "SEC-002: PII detection filter was confirmed to have run."
            if passed
            else (
                "SEC-002: pii_checks_performed is not True in quality_report. "
                "PII detection must be executed before any analysis proceeds."
            )
        )

        return CheckResult(
            check_id="SEC-002",
            dimension=self.dimension,
            passed=passed,
            severity="critical",
            message=message,
            actual_value=str(pii_checks_performed),
            expected_value="True",
        )

    def _check_sec003(self, audit_events: list[dict]) -> CheckResult:
        """SEC-003 (critical): no BREACH-severity events in audit log.

        Source: security.yaml §breach_override_policy + SEC-004-A.
        Prompt spec: SEC-003.
        """
        breach_events = [
            e for e in audit_events
            if str(e.get("severity", "")).upper() == "BREACH"
            or str(e.get("action", "")).startswith("BREACH")
        ]

        passed = len(breach_events) == 0
        message = (
            "SEC-003: No BREACH events found in audit log."
            if passed
            else (
                f"SEC-003: {len(breach_events)} BREACH event(s) detected in audit log. "
                "Security violation has occurred. Human escalation required."
            )
        )

        return CheckResult(
            check_id="SEC-003",
            dimension=self.dimension,
            passed=passed,
            severity="critical",
            message=message,
            actual_value=f"{len(breach_events)} breach events",
            expected_value="0 breach events",
        )

    def _check_sec004(self, context_payloads: list[dict]) -> CheckResult:
        """SEC-004 (critical): raw_data_rows must not appear in context payloads.

        Source: architecture/security-pii-filter.md, agent.schema.json const: false.
        Prompt spec: SEC-004.
        """
        violations = [
            i for i, payload in enumerate(context_payloads)
            if "raw_data_rows" in payload
        ]

        passed = len(violations) == 0
        message = (
            "SEC-004: raw_data_rows not found in any context payload."
            if passed
            else (
                f"SEC-004: raw_data_rows detected in context payload(s) at index(es) "
                f"{violations}. This is a critical security violation — "
                "patient record rows must never be injected into agent context."
            )
        )

        return CheckResult(
            check_id="SEC-004",
            dimension=self.dimension,
            passed=passed,
            severity="critical",
            message=message,
            actual_value=f"violations at payload indices: {violations}",
            expected_value="raw_data_rows absent from all payloads",
        )

    def _check_sec005(self, audit_events: list[dict]) -> CheckResult:
        """SEC-005 (advisory): capability tokens must be paired (issued + revoked).

        Source: security.yaml SEC-001-C (tokens revoked upon node completion).
        Prompt spec: SEC-005.
        """
        issued = {
            e.get("token_id")
            for e in audit_events
            if e.get("action") == "token_issued" and e.get("token_id")
        }
        revoked = {
            e.get("token_id")
            for e in audit_events
            if e.get("action") == "token_revoked" and e.get("token_id")
        }

        if not issued:
            return CheckResult(
                check_id="SEC-005",
                dimension=self.dimension,
                passed=True,
                severity="advisory",
                message="SEC-005: No token_issued events found in audit log; check skipped.",
            )

        unrevoked = issued - revoked
        passed = len(unrevoked) == 0
        message = (
            f"SEC-005: All {len(issued)} issued token(s) were revoked."
            if passed
            else (
                f"SEC-005: {len(unrevoked)} token(s) were issued but not revoked: "
                f"{list(unrevoked)[:5]}. "
                "All capability tokens must be revoked upon node completion or failure."
            )
        )

        return CheckResult(
            check_id="SEC-005",
            dimension=self.dimension,
            passed=passed,
            severity="advisory",
            message=message,
            actual_value=f"issued={len(issued)}, revoked={len(revoked)}, unrevoked={len(unrevoked)}",
            expected_value="issued == revoked",
        )

    def _check_sec006(self, report_content: str) -> CheckResult:
        """SEC-006 (critical): final report must not contain original column names.

        After Security Agent restore, report should contain human-readable
        original column names (that's fine), but non-var_n technical identifiers
        that look like var_n patterns mixed with original names should be clean.

        Practical check: the report must not contain raw var_n aliases that were
        NOT restored back to human-readable form (indicates Security Agent
        restore step was skipped).

        Source: security.yaml SEC-002-B.
        Prompt spec: SEC-006.
        """
        if not report_content:
            return CheckResult(
                check_id="SEC-006",
                dimension=self.dimension,
                passed=True,
                severity="critical",
                message="SEC-006: report_content is empty; column name check skipped.",
            )

        # Check: var_n aliases should NOT appear in the final report
        # (they should have been restored to human-readable names by Security Agent)
        unreplaced_aliases = _VAR_N_PATTERN.findall(report_content)
        unreplaced_unique = list(dict.fromkeys(unreplaced_aliases))

        passed = len(unreplaced_unique) == 0
        message = (
            "SEC-006: Final report contains no unreplaced var_n aliases. "
            "Security Agent restore completed successfully."
            if passed
            else (
                f"SEC-006: {len(unreplaced_unique)} unreplaced var_n alias(es) found "
                f"in final report: {unreplaced_unique[:5]}. "
                "Security Agent restore_variables step may not have completed."
            )
        )

        return CheckResult(
            check_id="SEC-006",
            dimension=self.dimension,
            passed=passed,
            severity="critical",
            message=message,
            actual_value=str(unreplaced_unique[:5]) if unreplaced_unique else "none",
            expected_value="no var_n aliases in final report",
        )
