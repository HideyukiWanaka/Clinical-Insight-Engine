"""Unit tests — フェーズ4: Skill適用層

検証マトリクス:
- test_skill_loader_get_skill_prompt_block_core         — core SKILL.md のブロックが返る
- test_skill_loader_get_skill_prompt_block_user_priority — user/ が core/ より優先される
- test_skill_loader_get_skill_prompt_block_missing       — 未知スキルIDで空文字列を返す
- test_statistics_agent_no_skill_loader_baseline        — skill_loader=None でスキル未注入
- test_statistics_agent_with_skill_loader               — skill_loader ありでプロンプトに注入
- test_visualization_agent_with_skill_loader            — VizAgent: skill_block がプロンプトに乗る
- test_reporting_agent_with_skill_loader                — ReportingAgent: skill_block が乗る
- test_user_skill_overrides_core_in_statistics          — user/ 上書きで別コンテンツが採用される
- test_method_to_skill_id_mapping_coverage              — 全 method_id にマッピングが存在する
- test_chart_to_skill_id_mapping_coverage               — 全 chart_key にマッピングが存在する
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cie.agents.base import AgentInput
from cie.agents.reporting import ReportingAgent
from cie.agents.statistics import StatisticsAgent, _METHOD_TO_SKILL_ID, _METHODS
from cie.agents.visualization import VisualizationAgent, _CHART_TO_SKILL_ID, _CHART_SPECS
from cie.security.capability_token import CapabilityScope, CapabilityToken
from cie.skills.loader import SkillLoader

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXEC_ID = str(uuid.uuid4())

_BASE_STAT_PAYLOAD = {
    "execution_id": EXEC_ID,
    "intent_object": {
        "objective": "between_group_comparison",
        "outcome_type": "continuous",
        "study_design": "randomized_controlled_trial",
        "n_groups_estimate": 2,
        "paired": False,
        "distribution_assumptions": "assumed_normal",
        "outcome_variables": [],
        "predictor_variables": [],
    },
    "data_quality_report": {"quality_gate_passed": True},
    "dataset_structural_metadata": {},
}

_BASE_VIZ_PAYLOAD = {
    "execution_id": EXEC_ID,
    "intent_object": {
        "objective": "between_group_comparison",
        "outcome_type": "continuous",
        "paired": False,
    },
    "statistical_results": {
        "method_id": "independent_samples_t_test",
        "p_value": 0.034,
        "effect_size": 0.52,
        "sample_size": 120,
    },
}

_BASE_REPORT_PAYLOAD = {
    "execution_id": EXEC_ID,
    "intent_object": {
        "objective": "between_group_comparison",
        "outcome_type": "continuous",
        "study_design": "randomized_controlled_trial",
    },
    "statistical_results": {
        "method_id": "independent_samples_t_test",
        "p_value": 0.034,
        "effect_size": 0.52,
        "sample_size": 120,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(scopes: list[CapabilityScope], agent_id: str = "statistics") -> CapabilityToken:
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id=agent_id,
        bound_step_id=f"{agent_id}_node",
        granted_scopes=frozenset(scopes),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def _mock_policy() -> MagicMock:
    pe = MagicMock()
    pe.enforce_multi = AsyncMock()
    return pe


def _mock_schema() -> MagicMock:
    sr = MagicMock()
    sr.validate = MagicMock()
    return sr


def _mock_audit() -> MagicMock:
    svc = MagicMock()
    svc.write = AsyncMock()
    return svc


def _agent_input(payload: dict, agent_id: str = "statistics") -> AgentInput:
    scopes = [
        CapabilityScope.DATASET_READ_VALIDATED,
        CapabilityScope.R_CODE_GENERATE_TEMPLATE,
        CapabilityScope.AUDIT_WRITE_ENTRY,
        CapabilityScope.REPORT_COMPILE_MANUSCRIPT,
        CapabilityScope.RUNTIME_INVOKE_EXECUTION,
    ]
    return AgentInput(
        execution_id=EXEC_ID,
        node_id=f"{agent_id}_node",
        payload=payload,
        capability_token=_make_token(scopes, agent_id=agent_id),
        input_schema_ref="cie://schemas/task-context.schema.json",
    )


def _write_skill_md(path: Path, content: str = "# Version: 1.0.0\n\n## Test\nUse extra step X.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# SkillLoader.get_skill_prompt_block
# ---------------------------------------------------------------------------


class TestSkillLoaderPromptBlock:
    def test_core_skill_returns_block(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        _write_skill_md(skills_root / "core" / "statistics" / "t-test" / "SKILL.md")
        loader = SkillLoader(skills_root)

        block = loader.get_skill_prompt_block("statistics/t-test")

        assert "=== SKILL INSTRUCTIONS" in block
        assert "statistics/t-test" in block
        assert "core" in block
        assert "=== END SKILL INSTRUCTIONS ===" in block
        assert "Use extra step X." in block

    def test_user_skill_overrides_core(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        _write_skill_md(
            skills_root / "core" / "statistics" / "t-test" / "SKILL.md",
            "# Version: 1.0.0\n\n## Core instructions.\n",
        )
        user_dir = skills_root / "user" / "my-t-test"
        _write_skill_md(
            user_dir / "SKILL.md",
            "# Version: 0.1.0\n\n## USER OVERRIDE: different instructions.\n",
        )
        (user_dir / "METADATA.yaml").write_text(
            "overrides:\n  core_skill_id: statistics/t-test\n", encoding="utf-8"
        )
        loader = SkillLoader(skills_root)

        block = loader.get_skill_prompt_block("statistics/t-test")

        assert "USER OVERRIDE" in block
        assert "Core instructions" not in block
        assert "user" in block

    def test_missing_skill_returns_empty_string(self, tmp_path: Path) -> None:
        loader = SkillLoader(tmp_path / "skills")
        assert loader.get_skill_prompt_block("statistics/nonexistent") == ""

    def test_read_skill_content_returns_text(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        _write_skill_md(skills_root / "core" / "reporting" / "manuscript-section" / "SKILL.md",
                        "# Version: 2.0.0\n\n## Always add word count.\n")
        loader = SkillLoader(skills_root)
        content = loader.read_skill_content("reporting/manuscript-section")
        assert content is not None
        assert "Always add word count." in content

    def test_read_skill_content_missing_returns_none(self, tmp_path: Path) -> None:
        loader = SkillLoader(tmp_path / "skills")
        assert loader.read_skill_content("reporting/nonexistent") is None


# ---------------------------------------------------------------------------
# StatisticsAgent: skill injection into system prompt
# ---------------------------------------------------------------------------


class TestStatisticsAgentSkillInjection:
    @pytest.mark.asyncio
    async def test_no_skill_loader_uses_base_prompt(self) -> None:
        """With skill_loader=None the base system prompt is used unchanged."""
        captured: list[str] = []

        mock_llm = MagicMock()
        mock_llm.provider = "stub"
        mock_llm.model = "stub-model"
        mock_llm.complete = AsyncMock(side_effect=lambda sys, usr, **_kw: captured.append(sys) or "```r\ncat('ok')\n```")

        agent = StatisticsAgent(
            _mock_policy(), _mock_schema(), _mock_audit(),
            llm_client=mock_llm,
            skill_loader=None,
        )
        await agent._execute(_agent_input(_BASE_STAT_PAYLOAD))

        assert captured, "LLM was not called"
        assert "=== SKILL INSTRUCTIONS" not in captured[0]

    @pytest.mark.asyncio
    async def test_skill_loader_injects_block(self, tmp_path: Path) -> None:
        """With a skill_loader that finds statistics/t-test, the block is appended."""
        skills_root = tmp_path / "skills"
        _write_skill_md(
            skills_root / "core" / "statistics" / "t-test" / "SKILL.md",
            "# Version: 1.0.0\n\n## PHASE4_MARKER: inject this.\n",
        )
        loader = SkillLoader(skills_root)

        captured: list[str] = []
        mock_llm = MagicMock()
        mock_llm.provider = "stub"
        mock_llm.model = "stub-model"
        mock_llm.complete = AsyncMock(side_effect=lambda sys, usr, **_kw: captured.append(sys) or "```r\ncat('ok')\n```")

        agent = StatisticsAgent(
            _mock_policy(), _mock_schema(), _mock_audit(),
            llm_client=mock_llm,
            skill_loader=loader,
        )
        await agent._execute(_agent_input(_BASE_STAT_PAYLOAD))

        assert captured, "LLM was not called"
        assert "PHASE4_MARKER" in captured[0]
        assert "=== SKILL INSTRUCTIONS" in captured[0]

    @pytest.mark.asyncio
    async def test_user_skill_override_in_statistics(self, tmp_path: Path) -> None:
        """user/ SKILL.md overrides core/ — LLM sees user content, not core."""
        skills_root = tmp_path / "skills"
        _write_skill_md(
            skills_root / "core" / "statistics" / "t-test" / "SKILL.md",
            "# Version: 1.0.0\n\n## CORE_CONTENT\n",
        )
        user_dir = skills_root / "user" / "my-ttest"
        _write_skill_md(user_dir / "SKILL.md", "# Version: 0.1.0\n\n## USER_CONTENT\n")
        (user_dir / "METADATA.yaml").write_text(
            "overrides:\n  core_skill_id: statistics/t-test\n", encoding="utf-8"
        )
        loader = SkillLoader(skills_root)

        captured: list[str] = []
        mock_llm = MagicMock()
        mock_llm.provider = "stub"
        mock_llm.model = "stub-model"
        mock_llm.complete = AsyncMock(side_effect=lambda sys, usr, **_kw: captured.append(sys) or "```r\ncat('ok')\n```")

        agent = StatisticsAgent(
            _mock_policy(), _mock_schema(), _mock_audit(),
            llm_client=mock_llm,
            skill_loader=loader,
        )
        await agent._execute(_agent_input(_BASE_STAT_PAYLOAD))

        assert captured
        assert "USER_CONTENT" in captured[0]
        assert "CORE_CONTENT" not in captured[0]


# ---------------------------------------------------------------------------
# VisualizationAgent: skill injection
# ---------------------------------------------------------------------------


class TestVisualizationAgentSkillInjection:
    @pytest.mark.asyncio
    async def test_skill_loader_injects_into_viz_prompt(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        _write_skill_md(
            skills_root / "core" / "visualization" / "group-comparison" / "SKILL.md",
            "# Version: 1.0.0\n\n## VIZ_PHASE4_MARKER: add stat annotation.\n",
        )
        loader = SkillLoader(skills_root)

        captured: list[str] = []
        mock_llm = MagicMock()
        mock_llm.provider = "stub"
        mock_llm.model = "stub-model"
        mock_llm.complete = AsyncMock(
            side_effect=lambda sys, usr, **_kw: captured.append(sys)
            or "```r\nggsave(file.path(Sys.getenv('OUTPUT_DIR'),'figure_fig_box_plot_with_jitter_001.png'))\n```"
        )

        agent = VisualizationAgent(
            _mock_policy(), _mock_schema(), _mock_audit(),
            llm_client=mock_llm,
            skill_loader=loader,
        )
        inp = _agent_input(_BASE_VIZ_PAYLOAD, agent_id="visualization")
        await agent._execute(inp)

        assert captured
        assert "VIZ_PHASE4_MARKER" in captured[0]


# ---------------------------------------------------------------------------
# ReportingAgent: skill injection
# ---------------------------------------------------------------------------


class TestReportingAgentSkillInjection:
    @pytest.mark.asyncio
    async def test_skill_loader_injects_into_reporting_prompt(self, tmp_path: Path) -> None:
        skills_root = tmp_path / "skills"
        _write_skill_md(
            skills_root / "core" / "reporting" / "manuscript-section" / "SKILL.md",
            "# Version: 1.0.0\n\n## REPORT_PHASE4_MARKER: include all CONSORT items.\n",
        )
        loader = SkillLoader(skills_root)

        captured: list[str] = []

        import json
        _stub_json = json.dumps({
            "title_draft": "T",
            "abstract": {"background": "B", "objective": "O", "methods": "M",
                         "results": "R", "conclusions": "C"},
            "introduction": {"clinical_problem": "P",
                             "evidence_gap": "[UNRESOLVED_ITEM: x]",
                             "objective_statement": "S"},
            "methods": {"study_design": "D", "statistical_analysis": "A [TRACE: statistical_results.method_id]"},
            "results": {"sample_description": "n=120 [TRACE: statistical_results.sample_size]",
                        "primary_outcome": "p=0.034 [TRACE: statistical_results.p_value]"},
            "discussion": {"principal_findings": "F", "literature_comparison": "[UNRESOLVED_ITEM: y]",
                           "limitations": "L"},
            "conclusions": "Conc.",
            "unresolved_items_additions": [],
        })

        mock_llm = MagicMock()
        mock_llm.provider = "stub"
        mock_llm.model = "stub-model"
        mock_llm.complete = AsyncMock(
            side_effect=lambda sys, usr, **_kw: captured.append(sys) or f"```json\n{_stub_json}\n```"
        )

        agent = ReportingAgent(
            _mock_policy(), _mock_schema(), _mock_audit(),
            llm_client=mock_llm,
            skill_loader=loader,
        )
        inp = _agent_input(_BASE_REPORT_PAYLOAD, agent_id="reporting")
        await agent._execute(inp)

        assert captured
        assert "REPORT_PHASE4_MARKER" in captured[0]


# ---------------------------------------------------------------------------
# Mapping coverage: all method_ids and chart_keys have entries
# ---------------------------------------------------------------------------


class TestMappingCoverage:
    def test_all_method_ids_mapped(self) -> None:
        for method_id in _METHODS:
            assert method_id in _METHOD_TO_SKILL_ID, (
                f"method_id '{method_id}' has no entry in _METHOD_TO_SKILL_ID"
            )

    def test_all_chart_keys_mapped(self) -> None:
        for chart_key in _CHART_SPECS:
            assert chart_key in _CHART_TO_SKILL_ID, (
                f"chart_key '{chart_key}' has no entry in _CHART_TO_SKILL_ID"
            )

    def test_skill_ids_reference_valid_domains(self) -> None:
        valid_stat_skills = {"statistics/t-test", "statistics/anova",
                             "statistics/correlation", "statistics/regression",
                             "statistics/survival"}
        for skill_id in _METHOD_TO_SKILL_ID.values():
            assert skill_id in valid_stat_skills, f"Unknown skill_id: {skill_id}"

    def test_viz_skill_ids_reference_valid_domains(self) -> None:
        valid_viz_skills = {"visualization/group-comparison", "visualization/survival"}
        for skill_id in _CHART_TO_SKILL_ID.values():
            assert skill_id in valid_viz_skills, f"Unknown viz skill_id: {skill_id}"
