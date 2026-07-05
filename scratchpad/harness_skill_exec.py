#!/usr/bin/env python3
"""フェーズ4 Skill適用層 — 検証ハーネス

目的:
  同じ解析で user/ Skill が core/ Skill より優先され、LLM へのシステムプロンプトが
  実際に変わることを確認する（捏造なし・API不要のスタブ LLM で実行）。

実行:
  python3 scratchpad/harness_skill_exec.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# プロジェクトルートを sys.path に追加
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from cie.agents.statistics import StatisticsAgent
from cie.agents.visualization import VisualizationAgent
from cie.agents.reporting import ReportingAgent
from cie.agents.base import AgentInput
from cie.security.capability_token import CapabilityScope, CapabilityToken
from cie.skills.loader import SkillLoader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXEC_ID = str(uuid.uuid4())


def _make_token(agent_id: str) -> CapabilityToken:
    now = datetime.now(timezone.utc)
    return CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id=EXEC_ID,
        bound_agent_id=agent_id,
        bound_step_id=f"{agent_id}_node",
        granted_scopes=frozenset([
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.R_CODE_GENERATE_TEMPLATE,
            CapabilityScope.AUDIT_WRITE_ENTRY,
            CapabilityScope.REPORT_COMPILE_MANUSCRIPT,
            CapabilityScope.RUNTIME_INVOKE_EXECUTION,
        ]),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def _make_agent_input(payload: dict, agent_id: str) -> AgentInput:
    return AgentInput(
        execution_id=EXEC_ID,
        node_id=f"{agent_id}_node",
        payload=payload,
        capability_token=_make_token(agent_id),
        input_schema_ref="cie://schemas/task-context.schema.json",
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


def _stub_llm(captured: list[str]) -> MagicMock:
    """スタブ LLM — システムプロンプトを recorded してダミー R を返す。"""
    llm = MagicMock()
    llm.provider = "stub"
    llm.model = "stub-model"
    llm.complete = AsyncMock(
        side_effect=lambda sys_prompt, user_msg: (
            captured.append(sys_prompt)
            or "```r\ncat('harness ok')\n```"
        )
    )
    return llm


def _write_skill(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


_STAT_PAYLOAD = {
    "execution_id": EXEC_ID,
    "intent_object": {
        "objective": "between_group_comparison",
        "outcome_type": "continuous",
        "study_design": "randomized_controlled_trial",
        "n_groups_estimate": 2,
        "paired": False,
        "distribution_assumptions": "assumed_normal",
        "outcome_variables": ["score"],
        "predictor_variables": ["group"],
    },
    "data_quality_report": {"quality_gate_passed": True},
    "dataset_structural_metadata": {
        "score": {"dtype": "float64"},
        "group": {"dtype": "object"},
    },
}

_VIZ_PAYLOAD = {
    "execution_id": EXEC_ID,
    "intent_object": {
        "objective": "between_group_comparison",
        "outcome_type": "continuous",
        "paired": False,
    },
    "statistical_results": {
        "method_id": "independent_samples_t_test",
        "p_value": 0.021,
        "effect_size": 0.68,
        "effect_size_measure": "Cohen's d",
        "sample_size": 60,
    },
}


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


async def test_statistics_no_skill() -> None:
    print("\n[TEST 1] StatisticsAgent — no SkillLoader → no injection")
    captured: list[str] = []
    agent = StatisticsAgent(
        _mock_policy(), _mock_schema(), _mock_audit(),
        llm_client=_stub_llm(captured),
        skill_loader=None,
    )
    await agent._execute(_make_agent_input(_STAT_PAYLOAD, "statistics"))
    assert captured, "LLM not called"
    assert "=== SKILL INSTRUCTIONS" not in captured[0], "Unexpected skill block in prompt"
    print("  PASSED — no skill block in prompt")


async def test_statistics_core_skill(tmp_path: Path) -> None:
    print("\n[TEST 2] StatisticsAgent — core/ SkillLoader → injection")
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root / "core" / "statistics" / "t-test" / "SKILL.md",
        "# Version: 1.0.0\n\n## HARNESS_CORE_SKILL: add normality check.\n",
    )
    loader = SkillLoader(skills_root)

    captured: list[str] = []
    agent = StatisticsAgent(
        _mock_policy(), _mock_schema(), _mock_audit(),
        llm_client=_stub_llm(captured),
        skill_loader=loader,
    )
    await agent._execute(_make_agent_input(_STAT_PAYLOAD, "statistics"))
    assert captured
    assert "HARNESS_CORE_SKILL" in captured[0], "Core skill not injected"
    assert "=== SKILL INSTRUCTIONS" in captured[0]
    assert "core" in captured[0]
    print("  PASSED — core skill block found in prompt")
    print(f"  Skill block excerpt: {captured[0][-300:].strip()!r}")


async def test_statistics_user_overrides_core(tmp_path: Path) -> None:
    print("\n[TEST 3] StatisticsAgent — user/ overrides core/ → user content used")
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root / "core" / "statistics" / "t-test" / "SKILL.md",
        "# Version: 1.0.0\n\n## CORE_INSTRUCTIONS: standard Welch t-test.\n",
    )
    user_dir = skills_root / "user" / "hospital-ttest"
    _write_skill(
        user_dir / "SKILL.md",
        "# Version: 0.2.0\n\n## USER_OVERRIDE: use one-sided test per SOP-007.\n",
    )
    (user_dir / "METADATA.yaml").write_text(
        "overrides:\n  core_skill_id: statistics/t-test\n", encoding="utf-8"
    )
    loader = SkillLoader(skills_root)

    captured: list[str] = []
    agent = StatisticsAgent(
        _mock_policy(), _mock_schema(), _mock_audit(),
        llm_client=_stub_llm(captured),
        skill_loader=loader,
    )
    await agent._execute(_make_agent_input(_STAT_PAYLOAD, "statistics"))
    assert captured
    assert "USER_OVERRIDE" in captured[0], "User skill not used"
    assert "CORE_INSTRUCTIONS" not in captured[0], "Core skill leaked through"
    assert "user" in captured[0]
    print("  PASSED — user skill override applied, core content excluded")
    print(f"  Skill block excerpt: {captured[0][-300:].strip()!r}")


async def test_visualization_skill_injection(tmp_path: Path) -> None:
    print("\n[TEST 4] VisualizationAgent — core/ SkillLoader → injection")
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root / "core" / "visualization" / "group-comparison" / "SKILL.md",
        "# Version: 1.0.0\n\n## VIZ_HARNESS: always add error bars.\n",
    )
    loader = SkillLoader(skills_root)

    captured: list[str] = []
    agent = VisualizationAgent(
        _mock_policy(), _mock_schema(), _mock_audit(),
        llm_client=_stub_llm(captured),
        skill_loader=loader,
    )
    await agent._execute(_make_agent_input(_VIZ_PAYLOAD, "visualization"))
    assert captured
    assert "VIZ_HARNESS" in captured[0], "Viz skill not injected"
    print("  PASSED — visualization skill block injected")


async def test_output_differs_with_skill(tmp_path: Path) -> None:
    """同じ解析で Skill あり／なしでシステムプロンプトが異なることを確認。"""
    print("\n[TEST 5] output_differs — with/without skill produces different prompt")
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root / "core" / "statistics" / "t-test" / "SKILL.md",
        "# Version: 1.0.0\n\n## DIFF_MARKER: use Bonferroni correction.\n",
    )
    loader = SkillLoader(skills_root)

    captured_no_skill: list[str] = []
    captured_with_skill: list[str] = []

    agent_no = StatisticsAgent(
        _mock_policy(), _mock_schema(), _mock_audit(),
        llm_client=_stub_llm(captured_no_skill),
        skill_loader=None,
    )
    agent_yes = StatisticsAgent(
        _mock_policy(), _mock_schema(), _mock_audit(),
        llm_client=_stub_llm(captured_with_skill),
        skill_loader=loader,
    )

    payload1 = dict(_STAT_PAYLOAD)
    payload2 = dict(_STAT_PAYLOAD)
    await agent_no._execute(_make_agent_input(payload1, "statistics"))
    await agent_yes._execute(_make_agent_input(payload2, "statistics"))

    assert captured_no_skill and captured_with_skill
    assert captured_no_skill[0] != captured_with_skill[0], \
        "Prompt must differ when skill_loader is injected"
    assert "DIFF_MARKER" not in captured_no_skill[0]
    assert "DIFF_MARKER" in captured_with_skill[0]
    print("  PASSED — prompts differ: skill_loader changes LLM system prompt")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    print("=" * 60)
    print("フェーズ4 Skill適用層 検証ハーネス")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        await test_statistics_no_skill()
        await test_statistics_core_skill(tmp / "t2")
        await test_statistics_user_overrides_core(tmp / "t3")
        await test_visualization_skill_injection(tmp / "t4")
        await test_output_differs_with_skill(tmp / "t5")

    print("\n" + "=" * 60)
    print("全テスト PASSED — フェーズ4 Skill適用層 検証完了")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
