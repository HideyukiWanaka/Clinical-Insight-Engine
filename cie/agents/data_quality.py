"""CIE Platform — Data Quality Agent.

Validates dataset structural metadata and statistical profiles before any
statistical analysis is permitted to proceed.  Operates exclusively on
aggregated metadata — never on raw patient record content (DQ-001).

Key guarantees:
  DQ-001  No raw patient record values enter this agent under any
          circumstances.  The capability_token scope (dataset.proxy_metadata)
          enforces this at the architecture level; this module adds an
          explicit metadata_type guard as defence-in-depth.

  DQ-002  quality_gate_passed=False when ANY critical issue exists.
          The Orchestrator must not advance to the Statistics Agent until
          all critical findings are resolved by a human reviewer.

  DQ-003  Missing value thresholds:
            >= 20% per variable → critical finding (pipeline blocked)
            >= 5% per variable  → advisory finding (imputation recommended)

  DQ-004  Clinical range violations → always critical.

  DQ-005  Output is a schema-conforming JSON object (report.schema.json).
          No prose, no speculative commentary.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.audit import AuditService
from cie.core.exceptions import AgentError
from cie.schemas.payloads import ColumnMetadata, DatasetMetadata
from cie.schemas.validator import SchemaRegistry
from cie.security.capability_token import CapabilityScope
from cie.security.pii_filter import PIIFilter
from cie.security.policy_engine import PolicyEngine

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (data-quality.yaml quality_gate_thresholds)
# ---------------------------------------------------------------------------

_CRITICAL_MISSING_PCT: float = 20.0
_WARNING_MISSING_PCT: float = 5.0
_SEVERE_MISSING_PCT: float = 50.0  # triggers variable exclusion recommendation


# ---------------------------------------------------------------------------
# Finding builders
# ---------------------------------------------------------------------------


def _make_finding(
    finding_id: str,
    severity: str,
    description: str,
    affected_component: str,
    *,
    resolution_required_before: str | None,
    human_resolution_required: bool,
) -> dict:
    """Construct a report.schema.json Finding dict."""
    return {
        "finding_id": finding_id,
        "severity": severity,  # "critical" or "advisory"
        "description": description,
        "affected_component": affected_component,
        "resolution_required_before": resolution_required_before,
        "human_resolution_required": human_resolution_required,
    }


# ---------------------------------------------------------------------------
# DataQualityAgent
# ---------------------------------------------------------------------------


class DataQualityAgent(BaseAgent):
    """Pre-analysis data integrity enforcement agent.

    Validates dataset structural metadata for missing values, clinical range
    violations, and PII signals.  Produces a :term:`quality_report` conforming
    to ``report.schema.json`` and sets ``gate_passed`` based solely on whether
    any critical findings were detected.

    Args:
        policy_engine: Enforces capability scope checks.
        schema_registry: Validates input and output payloads.
        audit_service: Records execution outcomes.
        pii_filter: Layer 1 + Layer 2 PII scanner.
    """

    CRITICAL_MISSING_THRESHOLD: float = _CRITICAL_MISSING_PCT
    WARNING_MISSING_THRESHOLD: float = _WARNING_MISSING_PCT

    def __init__(
        self,
        policy_engine: PolicyEngine,
        schema_registry: SchemaRegistry,
        audit_service: AuditService,
        pii_filter: PIIFilter,
    ) -> None:
        super().__init__(policy_engine, schema_registry, audit_service)
        self._pii_filter = pii_filter

    # ------------------------------------------------------------------
    # Abstract property implementations
    # ------------------------------------------------------------------

    @property
    def agent_id(self) -> str:
        # Underscore form matches the orchestration layer end-to-end:
        # spec/workflow.yaml (agent: data_quality), AGENT_ALLOWED_SCOPES,
        # and the token binding issued by the Orchestrator.
        return "data_quality"

    @property
    def input_schema_ref(self) -> str:
        return "cie://schemas/dataset.schema.json"

    @property
    def output_schema_ref(self) -> str:
        return "cie://schemas/report.schema.json"

    @property
    def required_scopes(self) -> list[CapabilityScope]:
        return [
            CapabilityScope.DATASET_PROXY_METADATA,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        ]

    # ------------------------------------------------------------------
    # Core execution
    # ------------------------------------------------------------------

    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        """Run all data quality checks and return a structured report.

        Steps:
          1. DQ-001 metadata_type guard — reject anything that is not
             proxy_metadata or validated_structural.
          2. Parse DatasetMetadata from the incoming payload.
          3. Missing value check (DQ-003) per column.
          4. Clinical range violation check (DQ-004) per column.
          5. PII detection (Layer 1 + Layer 2) per column.
          6. quality_gate_passed = critical_findings is empty (DQ-002).
          7. Assemble and return report.schema.json-conforming AgentOutput.
        """
        payload = agent_input.payload

        # Step 1 — DQ-001: enforce metadata_type whitelist
        metadata_type = payload.get("metadata_type")
        if metadata_type not in {"proxy_metadata", "validated_structural"}:
            raise AgentError(
                f"METADATA_PARSE_FAILED: metadata_type='{metadata_type}' is not "
                "permitted. DQ-001 requires proxy_metadata or validated_structural.",
                agent_id=self.agent_id,
            )

        # Step 2 — parse into typed model
        try:
            dataset_metadata = DatasetMetadata.model_validate(payload)
        except ValidationError as exc:
            raise AgentError(
                f"METADATA_PARSE_FAILED: {exc}",
                agent_id=self.agent_id,
            ) from exc

        columns: list[ColumnMetadata] = dataset_metadata.columns
        row_count: int = dataset_metadata.row_count
        var_n_alias_map: dict[str, str] = dataset_metadata.var_n_alias_map or {}

        critical_findings: list[dict] = []
        advisory_findings: list[dict] = []

        columns_with_critical_missing: int = 0
        columns_with_warning_missing: int = 0
        clinical_range_violations_count: int = 0
        finding_seq: int = 0

        for col in columns:

            # Step 3 — Missing value check (DQ-003)
            if col.missing_rate_pct >= self.CRITICAL_MISSING_THRESHOLD:
                columns_with_critical_missing += 1
                finding_seq += 1
                rec = (
                    "Variable exclusion recommended (severe missingness)."
                    if col.missing_rate_pct >= _SEVERE_MISSING_PCT
                    else "Resolve or obtain human waiver before pipeline advance."
                )
                critical_findings.append(
                    _make_finding(
                        finding_id=f"DQ-MISS-CRIT-{finding_seq:03d}",
                        severity="critical",
                        description=(
                            f"{col.var_n}: missing rate {col.missing_rate_pct:.1f}% "
                            f"exceeds critical threshold ({self.CRITICAL_MISSING_THRESHOLD}%). {rec}"
                        ),
                        affected_component=col.var_n,
                        resolution_required_before="statistics_node",
                        human_resolution_required=True,
                    )
                )
            elif col.missing_rate_pct >= self.WARNING_MISSING_THRESHOLD:
                columns_with_warning_missing += 1
                finding_seq += 1
                advisory_findings.append(
                    _make_finding(
                        finding_id=f"DQ-MISS-WARN-{finding_seq:03d}",
                        severity="advisory",
                        description=(
                            f"{col.var_n}: missing rate {col.missing_rate_pct:.1f}% "
                            f"(threshold {self.WARNING_MISSING_THRESHOLD}%). "
                            "Imputation strategy recommended."
                        ),
                        affected_component=col.var_n,
                        resolution_required_before=None,
                        human_resolution_required=False,
                    )
                )

            # Step 4 — Clinical range violation check (DQ-004)
            if col.clinical_range_violation:
                clinical_range_violations_count += 1
                finding_seq += 1
                critical_findings.append(
                    _make_finding(
                        finding_id=f"DQ-RANGE-CRIT-{finding_seq:03d}",
                        severity="critical",
                        description=(
                            f"{col.var_n}: values outside clinically plausible range. "
                            "Verify data integrity before analysis."
                        ),
                        affected_component=col.var_n,
                        resolution_required_before="statistics_node",
                        human_resolution_required=True,
                    )
                )

            # Step 5 — PII detection (architecture/security-pii-filter.md Timing 3)
            # Use the original column name from var_n_alias_map for Layer 1 regex;
            # fall back to var_n (which contains no PII signal) when not mapped.
            original_col_name: str = var_n_alias_map.get(col.var_n, col.var_n)
            pii_criticals, pii_warnings = self._pii_filter.run(
                col_name=original_col_name,
                col_meta=col,
                row_count=row_count,
            )

            for pii_f in pii_criticals:
                finding_seq += 1
                critical_findings.append(
                    _make_finding(
                        finding_id=f"DQ-PII-CRIT-{finding_seq:03d}",
                        severity="critical",
                        description=pii_f.description,
                        affected_component=col.var_n,
                        resolution_required_before="planner_node",
                        human_resolution_required=True,
                    )
                )

            for pii_f in pii_warnings:
                finding_seq += 1
                advisory_findings.append(
                    _make_finding(
                        finding_id=f"DQ-PII-WARN-{finding_seq:03d}",
                        severity="advisory",
                        description=pii_f.description,
                        affected_component=col.var_n,
                        resolution_required_before=None,
                        human_resolution_required=False,
                    )
                )

        # Step 6 — quality gate decision (DQ-002)
        quality_gate_passed: bool = len(critical_findings) == 0

        # Step 7 — assemble report.schema.json-conforming output_payload
        now_iso = datetime.now(timezone.utc).isoformat()
        output_payload: dict = {
            "report_id": str(uuid4()),
            "execution_id": agent_input.execution_id,
            "report_type": "quality_report",
            "produced_by_agent_id": "data_quality",
            "schema_version": "1.0",
            "gate_passed": quality_gate_passed,
            "critical_findings": critical_findings,
            "advisory_findings": advisory_findings,
            "quality_report_section": {
                "columns_evaluated": len(columns),
                "columns_with_critical_missing": columns_with_critical_missing,
                "columns_with_warning_missing": columns_with_warning_missing,
                "duplicate_record_count": 0,
                "duplicate_record_rate_pct": 0.0,
                "type_inconsistency_count": 0,
                "clinical_range_violations": clinical_range_violations_count,
                "recommended_exclusions": [],
            },
            "created_at": now_iso,
        }

        _log.info(
            "Data quality evaluation complete: execution_id=%s gate_passed=%s "
            "critical=%d advisory=%d",
            agent_input.execution_id,
            quality_gate_passed,
            len(critical_findings),
            len(advisory_findings),
        )

        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self.agent_id,
            status="success",
            output_payload=output_payload,
            output_schema_ref=self.output_schema_ref,
        )
