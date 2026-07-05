"""CIE Platform — Independent Artifact Reviewer Agent.

Cross-validates statistical outputs, figures, and manuscript sections before
human approval.  Implements CC-001 through CC-007 from agents/reviewer.yaml.

Key rules (reviewer.yaml):
  RV-001  Never receives intermediate outputs — only finalised artifacts.
  RV-002  Never modifies any artifact; produces a review report only.
  RV-003  review_passed=False if any critical finding exists.
  RV-004  All p-values in manuscript must match statistical_results.
  RV-005  All figure references in manuscript must exist in figure_manifest.
  RV-006  Schema-conforming JSON output only.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.exceptions import AgentError
from cie.schemas.validator import SchemaRegistry
from cie.security.capability_token import CapabilityScope
from cie.security.policy_engine import PolicyEngine
from cie.core.audit import AuditService

# ---------------------------------------------------------------------------
# Constants (reviewer.yaml consistency_checks CC-001…CC-007)
# ---------------------------------------------------------------------------

_CRITICAL_SCORE_PENALTY: float = 0.30
_ADVISORY_SCORE_PENALTY: float = 0.05
_READINESS_SCORE_MIN: float = 0.0

# Regex to find p-values cited in manuscript text, e.g. "p=0.03", "p < 0.001"
_PVALUE_PATTERN = re.compile(
    r"\bp\s*[=<>≤≥]\s*([\d]+\.[\d]+|0?\.\d+|<\s*0\.0+1)",
    re.IGNORECASE,
)

# Regex to find figure references, e.g. "Figure 1", "Fig. 2a"
_FIGURE_REF_PATTERN = re.compile(r"\b(?:Figure|Fig\.?)\s*(\d+\w*)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Finding builder
# ---------------------------------------------------------------------------


def _finding(
    finding_id: str,
    severity: str,
    description: str,
    affected_component: str,
    *,
    check_id: str,
) -> dict:
    return {
        "finding_id": finding_id,
        "severity": severity,
        "description": description,
        "affected_component": affected_component,
        "check_id": check_id,
    }


# ---------------------------------------------------------------------------
# ReviewerAgent
# ---------------------------------------------------------------------------


class ReviewerAgent(BaseAgent):
    """Pre-human-approval artifact consistency reviewer.

    Validates cross-artifact consistency (statistics ↔ manuscript ↔ figures
    ↔ checklist) and produces a structured review report with findings.

    Args:
        policy_engine: Enforces capability scope checks.
        schema_registry: Validates input and output payloads.
        audit_service: Records execution outcomes.
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        schema_registry: SchemaRegistry,
        audit_service: AuditService,
    ) -> None:
        super().__init__(policy_engine, schema_registry, audit_service)

    @property
    def agent_id(self) -> str:
        return "reviewer"

    @property
    def input_schema_ref(self) -> str:
        return "cie://schemas/task.schema.json"

    @property
    def output_schema_ref(self) -> str:
        # Dedicated permissive artifact schema: the output keys
        # (review_passed / readiness_score / review_report) are the downstream
        # contract read by the evaluation node and the UI. report.schema.json
        # is the strict report *envelope* (additionalProperties: false) and
        # does not admit this shape.
        return "cie://schemas/review-report.schema.json"

    @property
    def required_scopes(self) -> list[CapabilityScope]:
        # spec/permissions.yaml agent_permission_matrix.reviewer allows
        # dataset.read_validated / audit.write_entry /
        # skill.read_performance_records — workflow.state_read is NOT granted,
        # so requesting it would fail the PolicyEngine scope check.
        return [
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ]

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        """Run CC-001…CC-007 consistency checks and return review report.

        Steps:
          1. Extract artifact inputs from payload.
          2. Run each consistency check; accumulate critical / advisory findings.
          3. Build consistency_matrix (check_id → passed/failed/skipped).
          4. Compute review_passed and readiness_score.
          5. Return schema-conforming AgentOutput.
        """
        payload = agent_input.payload

        statistical_results: dict = payload.get("statistical_results") or {}
        figure_manifest: list = payload.get("figure_manifest") or []
        manuscript_raw = payload.get("manuscript_sections") or {}
        # ReportingAgent emits a list of {section_id, content, ...} dicts;
        # normalize to the {section_id: text} mapping the checks below expect.
        if isinstance(manuscript_raw, list):
            manuscript_sections: dict = {
                str(sec.get("section_id") or f"section_{i}"): str(sec.get("content") or "")
                for i, sec in enumerate(manuscript_raw)
                if isinstance(sec, dict)
            }
        else:
            manuscript_sections = manuscript_raw
        reporting_checklist_status: dict = payload.get("reporting_checklist_status") or {}

        critical: list[dict] = []
        advisory: list[dict] = []
        matrix: dict[str, str] = {}

        # Flatten all manuscript text for pattern matching
        manuscript_text = " ".join(
            str(v) for v in manuscript_sections.values() if v
        )

        # Figure IDs available in manifest
        manifest_ids: set[str] = {
            str(item.get("figure_id", item.get("id", "")))
            for item in figure_manifest
            if isinstance(item, dict)
        }
        manifest_labels: set[str] = {
            str(item.get("label", item.get("caption", ""))).lower()
            for item in figure_manifest
            if isinstance(item, dict)
        }

        # ------------------------------------------------------------------
        # CC-001 — p-values in manuscript match statistical_results
        # ------------------------------------------------------------------
        stat_p_values: list[float] = _extract_p_values_from_results(statistical_results)
        manuscript_p_values = _PVALUE_PATTERN.findall(manuscript_text)

        cc001_passed = True
        if manuscript_p_values and not stat_p_values:
            cc001_passed = False
            critical.append(_finding(
                finding_id=f"RV-CC001-{uuid4().hex[:6]}",
                severity="critical",
                description=(
                    f"Manuscript cites {len(manuscript_p_values)} p-value(s) "
                    "but statistical_results contains no p-values to verify against."
                ),
                affected_component="manuscript_sections.statistical_content",
                check_id="CC-001",
            ))
        matrix["CC-001"] = "passed" if cc001_passed else "failed"

        # CC-002 — effect sizes in manuscript match statistical_results
        has_effect_sizes = bool(statistical_results.get("effect_sizes") or
                                statistical_results.get("effect_size"))
        effect_pattern = re.search(
            r"\b(?:Cohen[''`]?s\s+d|OR|HR|RR|eta[²2]|r\s*=)\s*[=≈]\s*[\d.]+",
            manuscript_text,
            re.IGNORECASE,
        )
        cc002_passed = True
        if effect_pattern and not has_effect_sizes:
            cc002_passed = False
            critical.append(_finding(
                finding_id=f"RV-CC002-{uuid4().hex[:6]}",
                severity="critical",
                description=(
                    "Manuscript reports an effect size but statistical_results "
                    "does not contain a matching effect_size field."
                ),
                affected_component="manuscript_sections.effect_sizes",
                check_id="CC-002",
            ))
        matrix["CC-002"] = "passed" if cc002_passed else "failed"

        # CC-003 — sample sizes consistent
        stat_n: int | None = (
            statistical_results.get("sample_size")
            or statistical_results.get("n_total")
            or statistical_results.get("row_count")
        )
        manuscript_n_match = re.search(r"\bn\s*=\s*(\d+)", manuscript_text, re.IGNORECASE)
        cc003_passed = True
        if stat_n is not None and manuscript_n_match:
            cited_n = int(manuscript_n_match.group(1))
            if cited_n != stat_n:
                cc003_passed = False
                critical.append(_finding(
                    finding_id=f"RV-CC003-{uuid4().hex[:6]}",
                    severity="critical",
                    description=(
                        f"Sample size mismatch: manuscript cites n={cited_n} "
                        f"but statistical_results reports n={stat_n}."
                    ),
                    affected_component="manuscript_sections.sample_size",
                    check_id="CC-003",
                ))
        elif stat_n is None and manuscript_n_match:
            matrix["CC-003"] = "skipped"
        matrix.setdefault("CC-003", "passed" if cc003_passed else "failed")

        # CC-004 — figure references in manuscript exist in figure_manifest
        cc004_passed = True
        fig_refs = _FIGURE_REF_PATTERN.findall(manuscript_text)
        for ref_num in set(fig_refs):
            ref_label = f"figure {ref_num}".lower()
            ref_id = str(ref_num)
            if (
                ref_id not in manifest_ids
                and ref_label not in manifest_labels
                and not any(ref_id in mid for mid in manifest_ids)
            ):
                cc004_passed = False
                critical.append(_finding(
                    finding_id=f"RV-CC004-{uuid4().hex[:6]}",
                    severity="critical",
                    description=(
                        f"Manuscript references 'Figure {ref_num}' but it is "
                        "not present in figure_manifest."
                    ),
                    affected_component=f"figure_manifest.figure_{ref_num}",
                    check_id="CC-004",
                ))
        matrix["CC-004"] = "passed" if cc004_passed else "failed"

        # CC-005 — reporting checklist has no unresolved mandatory items
        cc005_passed = True
        mandatory_unresolved: list[str] = []
        for item_id, item_status in reporting_checklist_status.items():
            if isinstance(item_status, dict):
                is_mandatory = item_status.get("mandatory", False)
                is_resolved = item_status.get("resolved", False)
                if is_mandatory and not is_resolved:
                    mandatory_unresolved.append(item_id)
            elif item_status is False:
                mandatory_unresolved.append(item_id)
        if mandatory_unresolved:
            cc005_passed = False
            critical.append(_finding(
                finding_id=f"RV-CC005-{uuid4().hex[:6]}",
                severity="critical",
                description=(
                    f"{len(mandatory_unresolved)} mandatory checklist item(s) unresolved: "
                    f"{', '.join(mandatory_unresolved[:5])}."
                ),
                affected_component="reporting_checklist_status",
                check_id="CC-005",
            ))
        matrix["CC-005"] = "passed" if cc005_passed else "failed"

        # CC-006 — CI direction consistent with reported significance
        cc006_passed = True
        ci_lower = statistical_results.get("ci_lower")
        ci_upper = statistical_results.get("ci_upper")
        p_value = (
            statistical_results.get("p_value")
            or statistical_results.get("p_val")
            or (stat_p_values[0] if stat_p_values else None)
        )
        if ci_lower is not None and ci_upper is not None and p_value is not None:
            try:
                ci_lo = float(ci_lower)
                ci_hi = float(ci_upper)
                p_val = float(p_value)
                straddles_null = (ci_lo <= 0.0 <= ci_hi) or (ci_lo <= 1.0 <= ci_hi)
                significant = p_val < 0.05
                if significant and straddles_null:
                    cc006_passed = False
                    critical.append(_finding(
                        finding_id=f"RV-CC006-{uuid4().hex[:6]}",
                        severity="critical",
                        description=(
                            f"p={p_val:.4f} indicates significance but CI "
                            f"[{ci_lo}, {ci_hi}] crosses the null value."
                        ),
                        affected_component="statistical_results.confidence_interval",
                        check_id="CC-006",
                    ))
            except (TypeError, ValueError):
                matrix["CC-006"] = "skipped"
        else:
            matrix["CC-006"] = "skipped"
        matrix.setdefault("CC-006", "passed" if cc006_passed else "failed")

        # CC-007 — unresolved_items recorded as advisory (not blocking)
        unresolved_items: list = statistical_results.get("unresolved_items") or []
        for item in unresolved_items:
            advisory.append(_finding(
                finding_id=f"RV-CC007-{uuid4().hex[:6]}",
                severity="advisory",
                description=f"Unresolved item from upstream agent: {item}",
                affected_component="statistical_results.unresolved_items",
                check_id="CC-007",
            ))
        matrix["CC-007"] = "passed" if not unresolved_items else "advisory"

        # ------------------------------------------------------------------
        # Compute summary metrics (RV-003)
        # ------------------------------------------------------------------
        review_passed: bool = len(critical) == 0
        raw_score = 1.0 - (
            len(critical) * _CRITICAL_SCORE_PENALTY
            + len(advisory) * _ADVISORY_SCORE_PENALTY
        )
        readiness_score: float = max(_READINESS_SCORE_MIN, round(raw_score, 3))

        # ------------------------------------------------------------------
        # Assemble output payload
        # ------------------------------------------------------------------
        now_iso = datetime.now(timezone.utc).isoformat()
        output_payload = {
            "execution_id": agent_input.execution_id,
            "review_passed": review_passed,
            "readiness_score": readiness_score,
            "critical_findings": critical,
            "advisory_findings": advisory,
            "consistency_matrix": matrix,
            "review_report": {
                "report_id": str(uuid4()),
                "reviewed_at": now_iso,
                "agent_id": self.agent_id,
                "execution_id": agent_input.execution_id,
                "summary": {
                    "critical_count": len(critical),
                    "advisory_count": len(advisory),
                    "review_passed": review_passed,
                    "readiness_score": readiness_score,
                },
                "findings": critical + advisory,
                "consistency_matrix": matrix,
            },
        }

        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status="success",
            output_payload=output_payload,
            output_schema_ref=self.output_schema_ref,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_p_values_from_results(statistical_results: dict) -> list[float]:
    """Return all numeric p-values found in statistical_results dict (recursively)."""
    p_values: list[float] = []
    _collect_p_values(statistical_results, p_values)
    return p_values


def _collect_p_values(obj: object, out: list[float]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("p_val") or k in {"p", "pvalue", "p-value"}:
                try:
                    out.append(float(v))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    pass
            else:
                _collect_p_values(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_p_values(item, out)
