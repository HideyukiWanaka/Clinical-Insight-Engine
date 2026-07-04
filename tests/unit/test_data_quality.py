"""Unit tests for cie.agents.data_quality.DataQualityAgent.

Test matrix:
- test_high_missing_rate_critical           — 25% missing → critical finding
- test_moderate_missing_rate_warning        — 10% missing → advisory finding
- test_low_missing_rate_passes              — 3% missing  → no findings
- test_pii_column_name_detected             — "患者ID" original name → critical PII finding
- test_quality_gate_false_when_critical     — critical findings present → gate_passed=False
- test_quality_gate_true_when_only_warnings — only advisory findings → gate_passed=True
- test_raw_data_not_accessed                — DQ-001: metadata_type guard rejects invalid types
- test_output_conforms_to_schema            — real SchemaRegistry validates report.schema.json
- test_clinical_range_violation_critical    — DQ-004: range violation → critical finding
- test_multiple_columns_counted             — quality_report_section counts are correct
- test_pii_warning_goes_to_advisory         — WARNING PII finding → advisory, gate still passes
- test_missing_critical_threshold_exact     — exactly 20.0% → critical (boundary)
- test_missing_warning_threshold_exact      — exactly 5.0% → advisory (boundary)
- test_agent_id_and_scopes                  — canonical agent_id and required scopes
- test_var_n_alias_map_used_for_pii_scan    — original col name from map is passed to pii_filter
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from cie.agents.base import AgentInput, AgentOutput
from cie.agents.data_quality import DataQualityAgent
from cie.core.exceptions import AgentError
from cie.schemas.validator import SchemaRegistry, load_registry
from cie.security.capability_token import CapabilityScope, CapabilityToken
from cie.security.pii_detector import PIIFinding

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXEC_ID = str(uuid.uuid4())
NODE_ID = "data_quality_node"
INPUT_SCHEMA = "cie://schemas/dataset.schema.json"
OUTPUT_SCHEMA = "cie://schemas/report.schema.json"

_NOW_ISO = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _col(
    var_n: str,
    missing_pct: float,
    inferred_type: str = "continuous",
    summary_stats: dict | None = None,
    clinical_range_violation: bool | None = None,
) -> dict:
    """Build a ColumnMetadata dict."""
    d: dict[str, Any] = {
        "var_n": var_n,
        "inferred_type": inferred_type,
        "missing_count": int(100 * missing_pct / 100),
        "missing_rate_pct": missing_pct,
    }
    if summary_stats is not None:
        d["summary_stats"] = summary_stats
    if clinical_range_violation is not None:
        d["clinical_range_violation"] = clinical_range_violation
    return d


def _dataset_payload(
    columns: list[dict],
    *,
    metadata_type: str = "proxy_metadata",
    row_count: int = 100,
    var_n_alias_map: dict | None = None,
) -> dict:
    """Build a DatasetMetadata dict ready to use as AgentInput.payload."""
    payload: dict[str, Any] = {
        "dataset_id": str(uuid.uuid4()),
        "execution_id": EXEC_ID,
        "metadata_type": metadata_type,
        "row_count": row_count,
        "column_count": len(columns),
        "columns": columns,
        "created_at": _NOW_ISO,
    }
    if var_n_alias_map is not None:
        payload["var_n_alias_map"] = var_n_alias_map
    return payload


def _pii_finding(
    severity: str = "CRITICAL",
    description: str = "患者・症例識別子を示す列名パターン",
) -> PIIFinding:
    return PIIFinding(
        layer=1,
        severity=severity,  # type: ignore[arg-type]
        target_type="column_name",
        matched_text="[COL_NAME]",
        description=description,
        pattern_id="patient_id",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_policy_engine() -> MagicMock:
    pe = MagicMock()
    pe.enforce_multi = AsyncMock()
    return pe


@pytest.fixture
def mock_schema_registry() -> MagicMock:
    sr = MagicMock()
    sr.validate = MagicMock()  # synchronous no-op
    return sr


@pytest.fixture
def mock_audit() -> MagicMock:
    svc = MagicMock()
    svc.write = AsyncMock()
    return svc


@pytest.fixture
def mock_pii_filter() -> MagicMock:
    pf = MagicMock()
    pf.run = MagicMock(return_value=([], []))  # no PII by default
    return pf


@pytest.fixture
def agent(
    mock_policy_engine: MagicMock,
    mock_schema_registry: MagicMock,
    mock_audit: MagicMock,
    mock_pii_filter: MagicMock,
) -> DataQualityAgent:
    return DataQualityAgent(
        policy_engine=mock_policy_engine,
        schema_registry=mock_schema_registry,
        audit_service=mock_audit,
        pii_filter=mock_pii_filter,
    )


@pytest.fixture
def dq_token() -> CapabilityToken:
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id="data_quality",
        bound_step_id=NODE_ID,
        granted_scopes=frozenset({
            CapabilityScope.DATASET_PROXY_METADATA,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        }),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=300),
    )


def _make_input(
    payload: dict,
    token: CapabilityToken,
    input_schema: str = INPUT_SCHEMA,
) -> AgentInput:
    return AgentInput(
        execution_id=EXEC_ID,
        node_id=NODE_ID,
        capability_token=token,
        payload=payload,
        input_schema_ref=input_schema,
    )


# ---------------------------------------------------------------------------
# Identity tests
# ---------------------------------------------------------------------------


class TestAgentIdentity:

    def test_agent_id_and_scopes(self, agent: DataQualityAgent) -> None:
        """agent_id must be 'data_quality'; required scopes are PROXY_METADATA + AUDIT."""
        assert agent.agent_id == "data_quality"
        assert CapabilityScope.DATASET_PROXY_METADATA in agent.required_scopes
        assert CapabilityScope.AUDIT_WRITE_ENTRY in agent.required_scopes

    def test_schema_refs(self, agent: DataQualityAgent) -> None:
        assert agent.input_schema_ref == "cie://schemas/dataset.schema.json"
        assert agent.output_schema_ref == "cie://schemas/report.schema.json"


# ---------------------------------------------------------------------------
# Missing value threshold tests (DQ-003)
# ---------------------------------------------------------------------------


class TestMissingValueThresholds:

    async def test_high_missing_rate_critical(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """25% missing rate → critical_finding in output; gate_passed=False."""
        payload = _dataset_payload([_col("var_1", missing_pct=25.0)])
        result = await agent.run(_make_input(payload, dq_token))

        assert result.status == "success"
        assert result.output_payload["gate_passed"] is False
        critical = result.output_payload["critical_findings"]
        assert len(critical) == 1
        assert critical[0]["severity"] == "critical"
        assert "var_1" in critical[0]["affected_component"]
        assert "25.0%" in critical[0]["description"]

    async def test_moderate_missing_rate_warning(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """10% missing rate → advisory_finding; gate_passed=True (no critical)."""
        payload = _dataset_payload([_col("var_1", missing_pct=10.0)])
        result = await agent.run(_make_input(payload, dq_token))

        assert result.status == "success"
        assert result.output_payload["gate_passed"] is True
        assert len(result.output_payload["critical_findings"]) == 0
        advisory = result.output_payload["advisory_findings"]
        assert len(advisory) == 1
        assert advisory[0]["severity"] == "advisory"
        assert "var_1" in advisory[0]["affected_component"]

    async def test_low_missing_rate_passes(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """3% missing rate → no findings at all; gate_passed=True."""
        payload = _dataset_payload([_col("var_1", missing_pct=3.0)])
        result = await agent.run(_make_input(payload, dq_token))

        assert result.status == "success"
        assert result.output_payload["gate_passed"] is True
        assert result.output_payload["critical_findings"] == []
        assert result.output_payload["advisory_findings"] == []

    async def test_missing_critical_threshold_exact(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """Exactly 20.0% missing → triggers critical threshold (boundary check)."""
        payload = _dataset_payload([_col("var_1", missing_pct=20.0)])
        result = await agent.run(_make_input(payload, dq_token))

        critical = result.output_payload["critical_findings"]
        assert len(critical) >= 1
        assert result.output_payload["gate_passed"] is False

    async def test_missing_warning_threshold_exact(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """Exactly 5.0% missing → triggers warning threshold (boundary check)."""
        payload = _dataset_payload([_col("var_1", missing_pct=5.0)])
        result = await agent.run(_make_input(payload, dq_token))

        advisory = result.output_payload["advisory_findings"]
        assert len(advisory) >= 1
        assert result.output_payload["gate_passed"] is True


# ---------------------------------------------------------------------------
# Quality gate tests (DQ-002)
# ---------------------------------------------------------------------------


class TestQualityGate:

    async def test_quality_gate_false_when_critical(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """gate_passed=False when ANY critical finding exists (DQ-002)."""
        payload = _dataset_payload([_col("var_1", missing_pct=30.0)])
        result = await agent.run(_make_input(payload, dq_token))

        assert result.output_payload["gate_passed"] is False
        assert len(result.output_payload["critical_findings"]) > 0

    async def test_quality_gate_true_when_only_warnings(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """gate_passed=True when only advisory findings exist — no blocking issues."""
        payload = _dataset_payload([_col("var_1", missing_pct=10.0)])
        result = await agent.run(_make_input(payload, dq_token))

        assert result.output_payload["gate_passed"] is True
        assert result.output_payload["advisory_findings"] != []
        assert result.output_payload["critical_findings"] == []


# ---------------------------------------------------------------------------
# PII detection tests
# ---------------------------------------------------------------------------


class TestPIIDetection:

    async def test_pii_column_name_detected(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
        mock_pii_filter: MagicMock,
    ) -> None:
        """'患者ID' original column name detected as critical PII → critical finding."""
        # Provide var_n_alias_map so the original name is passed to the PII filter
        payload = _dataset_payload(
            [_col("var_1", missing_pct=0.0)],
            var_n_alias_map={"var_1": "患者ID"},
        )
        # Mock the PII filter to return a CRITICAL finding for this column
        mock_pii_filter.run.return_value = ([_pii_finding("CRITICAL")], [])

        result = await agent.run(_make_input(payload, dq_token))

        assert result.output_payload["gate_passed"] is False
        pii_criticals = [
            f for f in result.output_payload["critical_findings"]
            if f["finding_id"].startswith("DQ-PII-CRIT")
        ]
        assert len(pii_criticals) >= 1
        assert pii_criticals[0]["severity"] == "critical"
        assert pii_criticals[0]["human_resolution_required"] is True

    async def test_pii_warning_goes_to_advisory(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
        mock_pii_filter: MagicMock,
    ) -> None:
        """WARNING PII finding → advisory_finding; gate still passes."""
        payload = _dataset_payload(
            [_col("var_1", missing_pct=0.0, inferred_type="date")],
            var_n_alias_map={"var_1": "visit_date"},
        )
        mock_pii_filter.run.return_value = ([], [_pii_finding("WARNING", "日付型列")])

        result = await agent.run(_make_input(payload, dq_token))

        assert result.output_payload["gate_passed"] is True
        pii_advisories = [
            f for f in result.output_payload["advisory_findings"]
            if f["finding_id"].startswith("DQ-PII-WARN")
        ]
        assert len(pii_advisories) >= 1

    async def test_var_n_alias_map_used_for_pii_scan(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
        mock_pii_filter: MagicMock,
    ) -> None:
        """Original column name from var_n_alias_map must be passed to pii_filter.run."""
        payload = _dataset_payload(
            [_col("var_1", missing_pct=0.0)],
            var_n_alias_map={"var_1": "氏名"},
        )
        await agent.run(_make_input(payload, dq_token))

        # Check that pii_filter.run was called with the original name "氏名"
        actual_col_name = mock_pii_filter.run.call_args[1]["col_name"]
        assert actual_col_name == "氏名"


# ---------------------------------------------------------------------------
# DQ-001: raw data access guard
# ---------------------------------------------------------------------------


class TestDQ001RawDataGuard:

    async def test_raw_data_not_accessed(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """DQ-001: metadata_type outside the whitelist → status='failed'.

        Even with schema validation mocked (bypass), the agent itself
        refuses to process non-proxy payloads as a defence-in-depth measure.
        """
        payload = _dataset_payload(
            [_col("var_1", missing_pct=0.0)],
            metadata_type="raw_data",  # forbidden
        )
        result = await agent.run(_make_input(payload, dq_token))

        assert result.status == "failed"
        # AgentError wraps the METADATA_PARSE_FAILED message
        assert result.error_code in {"AGENT_ERROR", "METADATA_PARSE_FAILED"}
        assert "METADATA_PARSE_FAILED" in (result.error_message or "")

    async def test_missing_metadata_type_rejected(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """A payload without metadata_type fails the DQ-001 guard."""
        payload = _dataset_payload([_col("var_1", missing_pct=0.0)])
        payload.pop("metadata_type")  # remove entirely

        result = await agent.run(_make_input(payload, dq_token))

        assert result.status == "failed"
        assert "METADATA_PARSE_FAILED" in (result.error_message or "")


# ---------------------------------------------------------------------------
# Clinical range violation (DQ-004)
# ---------------------------------------------------------------------------


class TestClinicalRangeViolation:

    async def test_clinical_range_violation_critical(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """DQ-004: clinical_range_violation=True → critical finding regardless of missing rate."""
        payload = _dataset_payload(
            [_col("var_1", missing_pct=0.0, clinical_range_violation=True)]
        )
        result = await agent.run(_make_input(payload, dq_token))

        assert result.output_payload["gate_passed"] is False
        range_criticals = [
            f for f in result.output_payload["critical_findings"]
            if f["finding_id"].startswith("DQ-RANGE-CRIT")
        ]
        assert len(range_criticals) == 1
        assert range_criticals[0]["severity"] == "critical"


# ---------------------------------------------------------------------------
# quality_report_section counts
# ---------------------------------------------------------------------------


class TestReportSectionCounts:

    async def test_multiple_columns_counted(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """quality_report_section counts must accurately reflect evaluated columns."""
        payload = _dataset_payload([
            _col("var_1", missing_pct=25.0),  # critical missing
            _col("var_2", missing_pct=10.0),  # warning missing
            _col("var_3", missing_pct=1.0),   # ok
        ])
        result = await agent.run(_make_input(payload, dq_token))

        section = result.output_payload["quality_report_section"]
        assert section["columns_evaluated"] == 3
        assert section["columns_with_critical_missing"] == 1
        assert section["columns_with_warning_missing"] == 1

    async def test_clinical_violations_count(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """clinical_range_violations count reflects actual violation columns."""
        payload = _dataset_payload([
            _col("var_1", missing_pct=0.0, clinical_range_violation=True),
            _col("var_2", missing_pct=0.0, clinical_range_violation=True),
            _col("var_3", missing_pct=0.0),
        ])
        result = await agent.run(_make_input(payload, dq_token))

        section = result.output_payload["quality_report_section"]
        assert section["clinical_range_violations"] == 2


# ---------------------------------------------------------------------------
# Schema conformance (DQ-005)
# ---------------------------------------------------------------------------


class TestSchemaConformance:

    async def test_output_conforms_to_schema(
        self,
        mock_policy_engine: MagicMock,
        mock_audit: MagicMock,
        mock_pii_filter: MagicMock,
        dq_token: CapabilityToken,
    ) -> None:
        """DQ-005: output_payload must satisfy report.schema.json (real validator)."""
        real_registry = load_registry()
        agent = DataQualityAgent(
            policy_engine=mock_policy_engine,
            schema_registry=real_registry,
            audit_service=mock_audit,
            pii_filter=mock_pii_filter,
        )

        payload = _dataset_payload([
            _col("var_1", missing_pct=5.5),
            _col("var_2", missing_pct=0.0),
        ])
        agent_input = _make_input(payload, dq_token)

        result = await agent.run(agent_input)

        # The real SchemaRegistry validated input against dataset.schema.json and
        # output against report.schema.json without raising — confirmed by status.
        assert result.status == "success", (
            f"Schema validation failed: {result.error_message}"
        )
        assert result.output_payload["report_type"] == "quality_report"
        assert result.output_payload["produced_by_agent_id"] == "data_quality"

    async def test_finding_ids_are_unique(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """Every Finding must have a unique finding_id within the report."""
        payload = _dataset_payload([
            _col("var_1", missing_pct=25.0),  # critical
            _col("var_2", missing_pct=10.0),  # advisory
            _col("var_3", missing_pct=25.0),  # critical
        ])
        result = await agent.run(_make_input(payload, dq_token))

        all_findings = (
            result.output_payload["critical_findings"]
            + result.output_payload["advisory_findings"]
        )
        ids = [f["finding_id"] for f in all_findings]
        assert len(ids) == len(set(ids)), "Duplicate finding_ids detected"

    async def test_output_payload_has_required_report_fields(
        self,
        agent: DataQualityAgent,
        dq_token: CapabilityToken,
    ) -> None:
        """report.schema.json required fields must all be present in output_payload."""
        payload = _dataset_payload([_col("var_1", missing_pct=0.0)])
        result = await agent.run(_make_input(payload, dq_token))

        op = result.output_payload
        for field in ("report_id", "execution_id", "report_type",
                      "produced_by_agent_id", "schema_version", "created_at"):
            assert field in op, f"Missing required field: {field}"
