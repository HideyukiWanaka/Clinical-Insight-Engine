"""Unit tests for Phase 5: Format Selection UI propagation.

Tests the pure-logic helpers that wire the format selection panel to the
reporting agent, without touching Streamlit widgets or the LLM.

Coverage:
  - _build_format_context (app.py) — context dict built from user selections
  - ReportingAgent skill-id plumbing — reporting_skill_id from payload honoured
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# _build_format_context
# ---------------------------------------------------------------------------

from cie.reporting.format_context import build_format_context


class TestBuildFormatContext:
    def test_defaults_return_apa(self):
        ctx = build_format_context()
        assert ctx["target_journal_style"] == "APA"

    def test_no_checklist_by_default(self):
        ctx = build_format_context()
        assert "reporting_checklist_id" not in ctx

    def test_no_skill_by_default(self):
        ctx = build_format_context()
        assert "reporting_skill_id" not in ctx

    def test_checklist_propagated(self):
        ctx = build_format_context(checklist_id="CONSORT")
        assert ctx["reporting_checklist_id"] == "CONSORT"

    def test_all_supported_checklists(self):
        for cl in ("CONSORT", "STROBE", "TRIPOD", "PRISMA", "STARD"):
            ctx = build_format_context(checklist_id=cl)
            assert ctx["reporting_checklist_id"] == cl

    def test_journal_style_ama(self):
        ctx = build_format_context(journal_style="AMA")
        assert ctx["target_journal_style"] == "AMA"

    def test_journal_style_vancouver(self):
        ctx = build_format_context(journal_style="Vancouver")
        assert ctx["target_journal_style"] == "Vancouver"

    def test_none_journal_style_falls_back_to_apa(self):
        ctx = build_format_context(journal_style=None)  # type: ignore[arg-type]
        assert ctx["target_journal_style"] == "APA"

    def test_skill_id_propagated(self):
        ctx = build_format_context(skill_id="my-hospital-style")
        assert ctx["reporting_skill_id"] == "my-hospital-style"

    def test_none_skill_id_not_in_ctx(self):
        ctx = build_format_context(skill_id=None)
        assert "reporting_skill_id" not in ctx

    def test_all_keys_together(self):
        ctx = build_format_context(
            checklist_id="STROBE",
            journal_style="Vancouver",
            skill_id="inst/reporting-v2",
        )
        assert ctx == {
            "target_journal_style": "Vancouver",
            "reporting_checklist_id": "STROBE",
            "reporting_skill_id": "inst/reporting-v2",
        }


# ---------------------------------------------------------------------------
# ReportingAgent — reporting_skill_id from payload
# ---------------------------------------------------------------------------

import asyncio
from unittest.mock import AsyncMock, MagicMock

from cie.agents.base import AgentInput
from cie.agents.reporting import ReportingAgent


def _make_agent(skill_loader=None) -> ReportingAgent:
    """Return a ReportingAgent wired with stub dependencies (no LLM)."""
    policy_engine = MagicMock()
    policy_engine.check_policy = MagicMock(return_value=None)

    schema_registry = MagicMock()
    schema_registry.validate = MagicMock(return_value=None)

    audit_service = MagicMock()
    audit_service.write = AsyncMock(return_value=None)

    return ReportingAgent(
        policy_engine=policy_engine,
        schema_registry=schema_registry,
        audit_service=audit_service,
        llm_client=None,        # template fallback — no LLM calls
        reference_library=None,
        skill_loader=skill_loader,
    )


def _make_input(extra_payload: dict | None = None) -> AgentInput:
    payload = {
        "statistical_results": {
            "method_id": "independent_samples_t_test",
            "test_name": "Independent Samples t-test",
            "test_statistic": 3.45,
            "df": 98,
            "p_value": 0.0008,
            "effect_size": 0.69,
            "effect_size_measure": "cohen_d",
            "ci_lower": 0.30,
            "ci_upper": 1.08,
            "sample_size": 100,
            "group_summaries": {
                "treatment": {"mean": 5.2, "sd": 1.1, "n": 50},
                "control":   {"mean": 4.1, "sd": 1.3, "n": 50},
            },
        },
        "intent_object": {
            "study_design": "randomized_controlled_trial",
            "objective": "between_group_comparison",
        },
    }
    if extra_payload:
        payload.update(extra_payload)

    token = MagicMock()
    return AgentInput(
        execution_id="test-exec-001",
        node_id="reporting_node",
        capability_token=token,
        payload=payload,
        input_schema_ref="cie://schemas/task-context.schema.json",
    )


class TestReportingAgentFormatPropagation:
    """Verify that format context keys are correctly read by ReportingAgent._execute."""

    def _run(self, agent: ReportingAgent, agent_input: AgentInput):
        return asyncio.run(agent._execute(agent_input))

    def test_journal_style_apa_default(self):
        agent = _make_agent()
        out = self._run(agent, _make_input())
        assert out.output_payload["journal_style"] == "APA"

    def test_journal_style_ama_from_payload(self):
        agent = _make_agent()
        out = self._run(agent, _make_input({"target_journal_style": "AMA"}))
        assert out.output_payload["journal_style"] == "AMA"

    def test_journal_style_vancouver_from_payload(self):
        agent = _make_agent()
        out = self._run(agent, _make_input({"target_journal_style": "Vancouver"}))
        assert out.output_payload["journal_style"] == "VANCOUVER"

    def test_checklist_explicit_from_payload(self):
        agent = _make_agent()
        out = self._run(agent, _make_input({"reporting_checklist_id": "STROBE"}))
        status = out.output_payload["reporting_checklist_status"]
        assert status["checklist_id"] == "STROBE"
        assert status["checklist_inferred"] is False

    def test_checklist_inferred_from_study_design(self):
        """RCT study_design → CONSORT inferred when no explicit checklist given."""
        agent = _make_agent()
        out = self._run(agent, _make_input())
        status = out.output_payload["reporting_checklist_status"]
        assert status["checklist_id"] == "CONSORT"
        assert status["checklist_inferred"] is True

    def test_skill_id_in_payload_is_passed_to_llm_path(self):
        """When reporting_skill_id is set, skill_loader.get_skill_prompt_block
        is called with that ID instead of the default."""
        skill_loader = MagicMock()
        skill_loader.get_skill_prompt_block = MagicMock(return_value="")
        # Wire a stub LLM that returns a valid JSON manuscript
        import json
        _sections = {
            "title_draft": "Test Title",
            "abstract": {"background": "bg", "objective": "obj",
                         "methods": "m", "results": "r [TRACE: statistical_results.p_value]",
                         "conclusions": "c"},
            "introduction": {"clinical_problem": "prob", "evidence_gap": "[UNRESOLVED]",
                             "objective_statement": "obj"},
            "methods": {"study_design": "RCT",
                        "statistical_analysis": "t-test [TRACE: statistical_results.method_id]"},
            "results": {"sample_description": "n=100 [TRACE: statistical_results.sample_size]",
                        "primary_outcome": "p < .001 [TRACE: statistical_results.p_value]"},
            "discussion": {"principal_findings": "sig", "literature_comparison": "[UNRESOLVED]",
                           "limitations": "none"},
            "conclusions": "Concluded.",
            "unresolved_items_additions": [],
        }
        llm_client = MagicMock()
        llm_client.provider = "stub"
        llm_client.model = "stub"
        llm_client.complete = AsyncMock(
            return_value=f"```json\n{json.dumps(_sections)}\n```"
        )

        policy_engine = MagicMock()
        policy_engine.check_policy = MagicMock(return_value=None)
        schema_registry = MagicMock()
        schema_registry.validate = MagicMock(return_value=None)
        audit_service = MagicMock()
        audit_service.write = AsyncMock(return_value=None)

        agent = ReportingAgent(
            policy_engine=policy_engine,
            schema_registry=schema_registry,
            audit_service=audit_service,
            llm_client=llm_client,
            reference_library=None,
            skill_loader=skill_loader,
        )
        inp = _make_input({"reporting_skill_id": "user/my-style"})
        asyncio.run(agent._execute(inp))
        skill_loader.get_skill_prompt_block.assert_called_with("user/my-style")

    def test_default_skill_id_used_when_none_in_payload(self):
        """Without reporting_skill_id in payload, falls back to reporting/manuscript-section."""
        import json
        _sections = {
            "title_draft": "T", "abstract": {},
            "introduction": {}, "methods": {}, "results": {},
            "discussion": {}, "conclusions": "C",
            "unresolved_items_additions": [],
        }
        skill_loader = MagicMock()
        skill_loader.get_skill_prompt_block = MagicMock(return_value="")
        llm_client = MagicMock()
        llm_client.provider = "stub"
        llm_client.model = "stub"
        llm_client.complete = AsyncMock(
            return_value=f"```json\n{json.dumps(_sections)}\n```"
        )
        policy_engine = MagicMock()
        policy_engine.check_policy = MagicMock(return_value=None)
        schema_registry = MagicMock()
        schema_registry.validate = MagicMock(return_value=None)
        audit_service = MagicMock()
        audit_service.write = AsyncMock(return_value=None)

        agent = ReportingAgent(
            policy_engine=policy_engine,
            schema_registry=schema_registry,
            audit_service=audit_service,
            llm_client=llm_client,
            reference_library=None,
            skill_loader=skill_loader,
        )
        asyncio.run(agent._execute(_make_input()))
        skill_loader.get_skill_prompt_block.assert_called_with("reporting/manuscript-section")
