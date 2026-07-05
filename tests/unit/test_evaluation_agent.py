"""Unit tests for cie.agents.evaluation.EvaluationAgent (Phase 6).

Covers:
- agent identity / scopes / registration prerequisites
- context → evaluator artifact adaptation (statistical_results reshaping,
  manuscript list handling, Cohen's d interpretation derivation)
- evaluation report structure and completion_status semantics
- evaluator weight validation
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from cie.agents.base import AgentInput
from cie.agents.evaluation import EvaluationAgent
from cie.evaluation.base import EvaluationDimension
from cie.security.capability_token import (
    CapabilityScope,
    CapabilityToken,
    CapabilityTokenManager,
)

_EXEC_ID = "eval-agent-test-001"

_GOOD_STATS = {
    "method_id": "independent_samples_t_test",
    "test_name": "Independent Samples t-test",
    "test_statistic": 8.547,
    "df": 98.0,
    "p_value": 2.1e-13,
    "effect_size": 1.04,
    "effect_size_measure": "cohens_d",
    "ci_lower": 10.25,
    "ci_upper": 16.73,
    "sample_size": 100,
}

_R_SCRIPT = 'set.seed(42)\ndata <- read.csv(file.path(Sys.getenv("WORKSPACE_DIR"), "dataset.csv"))\n'

_MANUSCRIPT_LIST = [
    {"section_id": "methods", "content": "M " * 150, "llm_generated": True},
    {"section_id": "results", "content": "t(98) = 8.55, p < .001", "llm_generated": True},
]


def _make_agent(evaluators=None) -> EvaluationAgent:
    policy = MagicMock()
    policy.enforce_multi = AsyncMock()
    schema = MagicMock()
    schema.validate = MagicMock()
    audit = MagicMock()
    audit.write = AsyncMock()
    return EvaluationAgent(policy, schema, audit, evaluators=evaluators)


def _make_input(payload: dict) -> AgentInput:
    now = datetime.now(timezone.utc)
    token = CapabilityToken(
        token_id="tok-eval-test",
        bound_execution_id=_EXEC_ID,
        bound_agent_id="evaluation",
        bound_step_id="evaluation",
        granted_scopes=frozenset({
            CapabilityScope.WORKFLOW_STATE_READ,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        }),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=300),
    )
    return AgentInput(
        execution_id=_EXEC_ID,
        node_id="evaluation",
        capability_token=token,
        payload=payload,
        input_schema_ref="cie://schemas/task-context.schema.json",
    )


class TestIdentity:

    def test_agent_id(self) -> None:
        assert _make_agent().agent_id == "evaluation"

    def test_registered_in_allowed_scopes(self) -> None:
        # Orchestrator token issuance requires the agent in the matrix
        assert "evaluation" in CapabilityTokenManager.AGENT_ALLOWED_SCOPES

    def test_required_scopes_granted_by_matrix(self) -> None:
        allowed = CapabilityTokenManager.AGENT_ALLOWED_SCOPES["evaluation"]
        for scope in _make_agent().required_scopes:
            assert scope in allowed

    def test_weights_must_sum_to_100(self) -> None:
        bad = MagicMock()
        bad.weight_pct = 60
        with pytest.raises(ValueError):
            _make_agent(evaluators=[bad])


class TestExecution:

    async def test_full_context_produces_report(self) -> None:
        agent = _make_agent()
        payload = {
            "statistical_results": _GOOD_STATS,
            "r_script": _R_SCRIPT,
            "analysis_plan": {"method_id": "independent_samples_t_test"},
            "selected_methods": [{"justification": "Continuous outcome, two groups."}],
            "manuscript_sections": _MANUSCRIPT_LIST,
            "figure_manifest": [{"figure_id": "fig1", "actual_path": "/tmp/fig1.png"}],
            "data_quality_report": {"quality_gate_passed": True, "pii_checks_performed": True},
        }
        output = await agent.run(_make_input(payload))

        assert output.status == "success"
        op = output.output_payload
        assert op["completion_status"] in {"passed", "failed"}
        assert isinstance(op["evaluation_score"], float)
        report = op["evaluation_report"]
        assert set(report["dimension_scores"]) == {
            d.value
            for d in (
                EvaluationDimension.CORRECTNESS,
                EvaluationDimension.STATISTICAL,
                EvaluationDimension.SECURITY,
                EvaluationDimension.USABILITY,
            )
        }
        weights = [
            d["weight_pct"] for d in report["dimension_scores"].values()
        ]
        assert sum(weights) == 100

    async def test_reproducibility_report_flags(self) -> None:
        agent = _make_agent()
        payload = {"statistical_results": _GOOD_STATS, "r_script": _R_SCRIPT}
        output = await agent.run(_make_input(payload))
        rr = output.output_payload["reproducibility_report"]
        assert rr["r_script_present"] is True
        assert rr["set_seed_present"] is True
        assert rr["statistical_results_present"] is True

    async def test_missing_stats_fails_correctness_critically(self) -> None:
        agent = _make_agent()
        output = await agent.run(_make_input({}))
        assert output.status == "success"  # the node itself succeeds
        op = output.output_payload
        assert op["completion_status"] == "failed"
        assert op["evaluation_passed"] is False
        correctness = op["evaluation_report"]["dimension_scores"]["correctness"]
        assert correctness["critical_failure"] is True
        assert correctness["score"] == 0.0


class TestArtifactAdapter:

    def test_statistical_results_reshaped(self) -> None:
        agent = _make_agent()
        artifacts = agent._build_artifacts({"statistical_results": _GOOD_STATS})
        primary = artifacts["execution_result"]["primary_result"]
        assert primary["p_value"] == _GOOD_STATS["p_value"]
        assert primary["ci_lower"] == _GOOD_STATS["ci_lower"]
        assert primary["n_observations"] == 100
        assert artifacts["execution_result"]["method_used"] == "independent_samples_t_test"

    def test_cohens_d_interpretation_derived(self) -> None:
        agent = _make_agent()
        artifacts = agent._build_artifacts({"statistical_results": _GOOD_STATS})
        effect = artifacts["execution_result"]["effect_size"]
        assert effect["value"] == pytest.approx(1.04)
        assert effect["interpretation"] == "large"

    def test_non_cohen_measure_gets_no_interpretation(self) -> None:
        agent = _make_agent()
        stats = {**_GOOD_STATS, "effect_size_measure": "odds_ratio", "effect_size": 2.4}
        artifacts = agent._build_artifacts({"statistical_results": stats})
        effect = artifacts["execution_result"]["effect_size"]
        assert effect["value"] == pytest.approx(2.4)
        assert effect["interpretation"] is None

    def test_negative_effect_size_uses_magnitude(self) -> None:
        agent = _make_agent()
        stats = {**_GOOD_STATS, "effect_size": -0.6}
        artifacts = agent._build_artifacts({"statistical_results": stats})
        effect = artifacts["execution_result"]["effect_size"]
        assert effect["value"] == pytest.approx(0.6)
        assert effect["interpretation"] == "medium"

    def test_manuscript_list_adapted_for_usability(self) -> None:
        agent = _make_agent()
        artifacts = agent._build_artifacts({"manuscript_sections": _MANUSCRIPT_LIST})
        manuscript = artifacts["manuscript_sections"]
        assert manuscript["word_count"] > 0
        assert manuscript["methods_text"].startswith("M ")
        assert "p < .001" in artifacts["report_content"]

    def test_method_justification_lifted_into_review_report(self) -> None:
        agent = _make_agent()
        artifacts = agent._build_artifacts(
            {"selected_methods": [{"justification": "because reasons"}]}
        )
        assert artifacts["review_report"]["method_justification"] == "because reasons"

    def test_pii_flag_derived_from_dq_evidence(self) -> None:
        agent = _make_agent()
        # quality_report_section in context == DataQualityAgent completed,
        # and its _execute always runs the PII scan.
        artifacts = agent._build_artifacts({
            "data_quality_report": {"quality_gate_passed": True},
            "quality_report_section": {"columns_evaluated": 4},
        })
        assert artifacts["quality_report"]["pii_checks_performed"] is True

    def test_pii_flag_not_invented_without_evidence(self) -> None:
        agent = _make_agent()
        artifacts = agent._build_artifacts(
            {"data_quality_report": {"quality_gate_passed": True}}
        )
        assert "pii_checks_performed" not in artifacts["quality_report"]
