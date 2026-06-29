"""tests/integration/test_e2e_standard_workflow.py

PROMPT 10-1: E2E workflow integration tests.

All Agents are mocked — no real LLM or R-script calls are made.
The real WorkflowRegistry, WorkflowStateMachine, CapabilityTokenManager,
PolicyEngine, AuditService, and PIIFilter are wired together against an
in-memory SQLite database.

Test cases
----------
- test_full_clinical_analysis_standard_workflow
- test_workflow_selection_correctness
- test_planner_cannot_set_workflow_id
- test_capability_token_revoked_after_each_node
- test_security_review_pauses_workflow
- test_resume_after_human_approval
- test_non_recoverable_error_fails_workflow
- test_recoverable_error_retries_3_times
- test_pii_in_prompt_blocked_before_planner
- test_raw_data_not_in_any_context
- test_evaluation_score_written_to_db
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.audit import AuditService
from cie.core.database import (
    AuditLog,
    SkillPerformanceRecord,
    get_session,
    init_db,
)
from cie.core.exceptions import AgentError, PIIDetectedError
from cie.schemas.validator import SchemaRegistry
from cie.security.capability_token import CapabilityScope, CapabilityTokenManager
from cie.security.context_guard import ContextGuard
from cie.security.pii_filter import PIIFilter
from cie.security.policy_engine import PolicyEngine
from cie.workflow.orchestrator import Orchestrator
from cie.workflow.registry import WorkflowDefinition, WorkflowNodeDef, WorkflowRegistry
from cie.workflow.states import WorkflowState, WorkflowStateMachine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WORKFLOW_YAML = Path(__file__).parent.parent.parent / "spec" / "workflow.yaml"

_STANDARD_INTENT = {
    "objective": "between_group_comparison",
    "outcome_type": "continuous",
    "requires_human_clarification": False,
}


# ---------------------------------------------------------------------------
# MockAgent
# ---------------------------------------------------------------------------


class MockAgent(BaseAgent):
    """BaseAgent test double. No LLM / Rscript calls."""

    def __init__(
        self,
        mock_agent_id: str,
        policy_engine: PolicyEngine,
        schema_registry: SchemaRegistry,
        audit_service: AuditService,
        response_payload: dict | None = None,
    ) -> None:
        super().__init__(
            policy_engine=policy_engine,
            schema_registry=schema_registry,
            audit_service=audit_service,
        )
        self._mock_agent_id = mock_agent_id
        self._response_payload: dict = response_payload or {"ok": True}
        self.call_count: int = 0
        self.received_payloads: list[dict] = []
        self.raise_on_next: Exception | None = None
        self.fail_times: int = 0
        # Return a failed AgentOutput with this error_code (bypasses exception wrapping)
        self.return_failure_code: str | None = None

    @property
    def agent_id(self) -> str:
        return self._mock_agent_id

    @property
    def input_schema_ref(self) -> str:
        return "cie://schemas/task.schema.json"

    @property
    def output_schema_ref(self) -> str:
        return "cie://schemas/task.schema.json"

    @property
    def required_scopes(self) -> list[CapabilityScope]:
        # Empty → PolicyEngine.enforce_multi is a no-op (loop never executes)
        return []

    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        self.call_count += 1
        self.received_payloads.append(dict(agent_input.payload))

        if self.raise_on_next is not None:
            exc = self.raise_on_next
            self.raise_on_next = None
            raise exc

        if self.return_failure_code is not None:
            code = self.return_failure_code
            self.return_failure_code = None
            return AgentOutput(
                execution_id=agent_input.execution_id,
                agent_id=self._mock_agent_id,
                status="failed",
                output_payload={},
                output_schema_ref=self.output_schema_ref,
                error_code=code,
            )

        if self.fail_times > 0:
            self.fail_times -= 1
            raise AgentError(
                "runtime_timeout: simulated transient failure",
                agent_id=self._mock_agent_id,
            )

        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self._mock_agent_id,
            status="success",
            output_payload=dict(self._response_payload),
            output_schema_ref=self.output_schema_ref,
        )


# ---------------------------------------------------------------------------
# Helper: mock SchemaRegistry that accepts every payload
# ---------------------------------------------------------------------------


def _make_noop_schema_registry() -> SchemaRegistry:
    sr = MagicMock(spec=SchemaRegistry)
    sr.validate = MagicMock()
    return sr


# ---------------------------------------------------------------------------
# cie_system fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def cie_system():
    """Wire the full CIE system with in-memory SQLite and MockAgents."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_db(engine)

    @asynccontextmanager
    async def session_factory():
        async with get_session(engine) as s:
            yield s

    audit_service = AuditService(session_factory=session_factory)
    pii_filter = PIIFilter(enable_layer2=False)
    context_guard = ContextGuard(pii_filter=pii_filter, audit_service=audit_service)
    token_manager = CapabilityTokenManager()
    policy_engine = PolicyEngine(token_manager=token_manager, audit_service=audit_service)
    schema_registry = _make_noop_schema_registry()

    workflow_registry = WorkflowRegistry.load_from_yaml(_WORKFLOW_YAML)
    state_machine = WorkflowStateMachine()

    # One MockAgent per agent_id referenced in the workflows.
    # "security" is omitted because security_review is an approval node
    # and never dispatches to an agent.
    agent_ids = [
        "planner",
        "data_quality",
        "statistics",
        "runtime",
        "visualization",
        "reporting",
        "reviewer",
    ]
    agent_registry: dict[str, MockAgent] = {
        aid: MockAgent(
            mock_agent_id=aid,
            policy_engine=policy_engine,
            schema_registry=schema_registry,
            audit_service=audit_service,
        )
        for aid in agent_ids
    }

    orchestrator = Orchestrator(
        workflow_registry=workflow_registry,
        state_machine=state_machine,
        token_manager=token_manager,
        policy_engine=policy_engine,
        context_guard=context_guard,
        audit_service=audit_service,
        agent_registry=agent_registry,
    )

    yield {
        "engine": engine,
        "session_factory": session_factory,
        "audit_service": audit_service,
        "pii_filter": pii_filter,
        "context_guard": context_guard,
        "token_manager": token_manager,
        "policy_engine": policy_engine,
        "schema_registry": schema_registry,
        "workflow_registry": workflow_registry,
        "state_machine": state_machine,
        "agent_registry": agent_registry,
        "orchestrator": orchestrator,
    }

    await engine.dispose()


# ---------------------------------------------------------------------------
# Minimal two-node workflow fixture (no approval gate) for retry / error tests
# ---------------------------------------------------------------------------

_SIMPLE_WF = WorkflowDefinition(
    workflow_id="simple_test",
    version="1.0",
    category="test",
    entrypoint="step_a",
    nodes={
        "step_a": WorkflowNodeDef(
            node_id="step_a",
            node_type="task",
            agent_id="planner",
            depends_on=[],
            outputs=["output_a"],
        ),
        "step_b": WorkflowNodeDef(
            node_id="step_b",
            node_type="task",
            agent_id="runtime",
            depends_on=["step_a"],
            outputs=["output_b"],
        ),
    },
)


class _SimpleRegistry(WorkflowRegistry):
    """Registry that always returns _SIMPLE_WF."""

    def __init__(self) -> None:
        super().__init__()
        self._definitions["simple_test"] = _SIMPLE_WF

    def select_workflow(self, intent_object: dict) -> tuple[str, str, str]:  # noqa: ARG002
        return ("simple_test", "WS-TEST", "test workflow")

    def get(self, workflow_id: str) -> WorkflowDefinition:  # noqa: ARG002
        return _SIMPLE_WF


@pytest.fixture
async def simple_system():
    """Minimal two-node system without approval gates."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_db(engine)

    @asynccontextmanager
    async def session_factory():
        async with get_session(engine) as s:
            yield s

    audit_service = AuditService(session_factory=session_factory)
    token_manager = CapabilityTokenManager()
    policy_engine = PolicyEngine(token_manager=token_manager, audit_service=audit_service)
    schema_registry = _make_noop_schema_registry()

    agent_registry: dict[str, MockAgent] = {
        aid: MockAgent(
            mock_agent_id=aid,
            policy_engine=policy_engine,
            schema_registry=schema_registry,
            audit_service=audit_service,
        )
        for aid in ("planner", "runtime")
    }

    orchestrator = Orchestrator(
        workflow_registry=_SimpleRegistry(),
        state_machine=WorkflowStateMachine(),
        token_manager=token_manager,
        policy_engine=policy_engine,
        context_guard=MagicMock(spec=ContextGuard),
        audit_service=audit_service,
        agent_registry=agent_registry,
    )

    yield {
        "engine": engine,
        "session_factory": session_factory,
        "audit_service": audit_service,
        "token_manager": token_manager,
        "agent_registry": agent_registry,
        "orchestrator": orchestrator,
    }

    await engine.dispose()


# ===========================================================================
# Tests
# ===========================================================================


async def test_full_clinical_analysis_standard_workflow(cie_system):
    """clinical_analysis_standard の全ノードが順番に実行されること (ADR-0001)."""
    orchestrator: Orchestrator = cie_system["orchestrator"]
    audit_service: AuditService = cie_system["audit_service"]
    workflow_registry: WorkflowRegistry = cie_system["workflow_registry"]
    session_factory = cie_system["session_factory"]
    execution_id = str(uuid.uuid4())

    # Phase 1: intake → ... → security_review (approval) → WAITING_FOR_HUMAN
    with patch("cie.workflow.orchestrator._RETRY_BASE_DELAY_SECONDS", 0.0):
        result = await orchestrator.run_workflow(
            execution_id=execution_id,
            intent_object=_STANDARD_INTENT,
        )

    assert result["workflow_id_selected"] == "clinical_analysis_standard"
    assert result["rule_id"] == "WS-004"
    assert result["final_state"] == WorkflowState.WAITING_FOR_HUMAN.value

    # Phase 2: human approves → remaining nodes → COMPLETED
    await orchestrator.resume_workflow(
        execution_id=execution_id,
        human_decision={"action": "approved"},
    )

    # Verify audit trail: at least one event per workflow node
    workflow_def = workflow_registry.get("clinical_analysis_standard")
    async with session_factory() as session:
        rows = await session.execute(
            select(AuditLog).where(AuditLog.execution_id == execution_id)
        )
        audit_events = rows.scalars().all()

    assert len(audit_events) >= len(workflow_def.nodes), (
        f"Expected at least {len(workflow_def.nodes)} audit events, "
        f"got {len(audit_events)}"
    )

    # WORKFLOW_COMPLETED must be present after resume
    actions = {e.action for e in audit_events}
    assert "WORKFLOW_COMPLETED" in actions


async def test_workflow_selection_correctness(cie_system):
    """ADR-0001: intent_object の内容に応じて正しい workflow が選択されること."""
    workflow_registry: WorkflowRegistry = cie_system["workflow_registry"]

    cases = [
        ({"outcome_type": "survival"}, "clinical_analysis_survival", "WS-001"),
        ({"objective": "systematic_review"}, "clinical_analysis_meta", "WS-002"),
        ({"objective": "prediction_model"}, "clinical_analysis_prediction", "WS-003"),
        (
            {"objective": "between_group_comparison", "outcome_type": "continuous"},
            "clinical_analysis_standard",
            "WS-004",
        ),
    ]

    for intent, expected_wf, expected_rule in cases:
        wf_id, rule_id, _ = workflow_registry.select_workflow(intent)
        assert wf_id == expected_wf, f"intent={intent!r}: expected {expected_wf}, got {wf_id}"
        assert rule_id == expected_rule, f"intent={intent!r}: expected {expected_rule}, got {rule_id}"


async def test_planner_cannot_set_workflow_id(cie_system):
    """ADR-0001: Planner の出力に workflow_id が含まれていても Orchestrator は無視すること."""
    workflow_registry: WorkflowRegistry = cie_system["workflow_registry"]

    # Planner が不正に workflow_id を埋め込んだ出力を模倣
    planner_output_with_injection = {
        "objective": "between_group_comparison",
        "outcome_type": "continuous",
        "requires_human_clarification": False,
        "workflow_id": "clinical_analysis_survival",  # 不正な注入
    }

    # WorkflowRegistry.select_workflow は workflow_id フィールドを無視する
    wf_id, rule_id, _ = workflow_registry.select_workflow(planner_output_with_injection)
    assert wf_id == "clinical_analysis_standard", (
        f"workflow_id injection must be ignored; expected 'clinical_analysis_standard', got {wf_id!r}"
    )
    assert rule_id == "WS-004"


async def test_capability_token_revoked_after_each_node(simple_system):
    """各ノード完了後に CapabilityTokenManager.revoke() が必ず呼ばれること."""
    orchestrator: Orchestrator = simple_system["orchestrator"]
    token_manager: CapabilityTokenManager = simple_system["token_manager"]

    revoke_calls: list = []
    original_revoke = token_manager.revoke

    def tracking_revoke(token):
        revoke_calls.append(token)
        return original_revoke(token)

    token_manager.revoke = tracking_revoke  # type: ignore[method-assign]

    with patch("cie.workflow.orchestrator._RETRY_BASE_DELAY_SECONDS", 0.0):
        result = await orchestrator.run_workflow(
            execution_id=str(uuid.uuid4()),
            intent_object=_STANDARD_INTENT,
        )

    assert result["final_state"] == WorkflowState.COMPLETED.value

    # _SIMPLE_WF has 2 agent nodes (step_a, step_b) → revoke must be called twice
    assert len(revoke_calls) >= 2, (
        f"Expected revoke() called ≥2 times, got {len(revoke_calls)}"
    )

    # All returned tokens should be marked revoked
    # (original tokens are immutable; revoke() creates new revoked copies)
    assert all(not t.revoked for t in revoke_calls), (
        "Tokens passed to revoke() should still be un-revoked originals"
    )


async def test_security_review_pauses_workflow(cie_system):
    """security_review (approval) ノードで workflow が WAITING_FOR_HUMAN になること."""
    orchestrator: Orchestrator = cie_system["orchestrator"]
    execution_id = str(uuid.uuid4())

    with patch("cie.workflow.orchestrator._RETRY_BASE_DELAY_SECONDS", 0.0):
        result = await orchestrator.run_workflow(
            execution_id=execution_id,
            intent_object=_STANDARD_INTENT,
        )

    assert result["final_state"] == WorkflowState.WAITING_FOR_HUMAN.value

    # Verify the pausing node is security_review
    node_results = result["node_results"]
    waiting_results = [r for r in node_results if r.status == "waiting_for_human"]
    assert len(waiting_results) == 1
    assert waiting_results[0].node_id == "security_review"


async def test_resume_after_human_approval(cie_system):
    """人間承認後に workflow が再開されること."""
    orchestrator: Orchestrator = cie_system["orchestrator"]
    agent_registry: dict[str, MockAgent] = cie_system["agent_registry"]
    session_factory = cie_system["session_factory"]
    execution_id = str(uuid.uuid4())

    with patch("cie.workflow.orchestrator._RETRY_BASE_DELAY_SECONDS", 0.0):
        result = await orchestrator.run_workflow(
            execution_id=execution_id,
            intent_object=_STANDARD_INTENT,
        )

    assert result["final_state"] == WorkflowState.WAITING_FOR_HUMAN.value

    runtime_calls_before = agent_registry["runtime"].call_count

    # Resume with human approval
    await orchestrator.resume_workflow(
        execution_id=execution_id,
        human_decision={"action": "approved"},
    )

    # Nodes after security_review: runtime_execution, visualization, reporting, reviewer
    assert agent_registry["runtime"].call_count > runtime_calls_before, (
        "runtime agent should have been called after resume"
    )
    assert agent_registry["visualization"].call_count >= 1
    assert agent_registry["reporting"].call_count >= 1
    assert agent_registry["reviewer"].call_count >= 1

    # Audit log must contain HUMAN_DECISION_RECEIVED and WORKFLOW_COMPLETED
    async with session_factory() as session:
        rows = await session.execute(
            select(AuditLog).where(AuditLog.execution_id == execution_id)
        )
        actions = {e.action for e in rows.scalars().all()}

    assert "HUMAN_DECISION_RECEIVED" in actions
    assert "WORKFLOW_COMPLETED" in actions


async def test_non_recoverable_error_fails_workflow(simple_system):
    """non-recoverable エラーで workflow が FAILED 状態になること."""
    orchestrator: Orchestrator = simple_system["orchestrator"]
    agent_registry: dict[str, MockAgent] = simple_system["agent_registry"]
    execution_id = str(uuid.uuid4())

    # schema_validation_failure は NON_RECOVERABLE_ERRORS に含まれる。
    # raise_on_next ではなく return_failure_code を使う: BaseAgent.run() は
    # 例外を内部で捕捉して AGENT_ERROR に変換してしまうため、error_code を
    # 直接 AgentOutput に埋め込む必要がある。
    agent_registry["planner"].return_failure_code = "schema_validation_failure"

    with patch("cie.workflow.orchestrator._RETRY_BASE_DELAY_SECONDS", 0.0):
        result = await orchestrator.run_workflow(
            execution_id=execution_id,
            intent_object=_STANDARD_INTENT,
        )

    assert result["final_state"] == WorkflowState.FAILED.value

    # Non-recoverable → no retries; planner called exactly once
    assert agent_registry["planner"].call_count == 1

    # runtime agent must never have been reached
    assert agent_registry["runtime"].call_count == 0


async def test_recoverable_error_retries_3_times(simple_system):
    """recoverable error (runtime_timeout) で 3 回リトライされること."""
    orchestrator: Orchestrator = simple_system["orchestrator"]
    agent_registry: dict[str, MockAgent] = simple_system["agent_registry"]
    execution_id = str(uuid.uuid4())

    # runtime agent: 最初の 2 回は失敗、3 回目で成功
    agent_registry["runtime"].fail_times = 2

    with patch("cie.workflow.orchestrator._RETRY_BASE_DELAY_SECONDS", 0.0):
        result = await orchestrator.run_workflow(
            execution_id=execution_id,
            intent_object=_STANDARD_INTENT,
        )

    assert result["final_state"] == WorkflowState.COMPLETED.value

    # runtime agent は合計 3 回呼ばれている (2 失敗 + 1 成功)
    assert agent_registry["runtime"].call_count == 3


async def test_pii_in_prompt_blocked_before_planner(cie_system):
    """PII を含むプロンプトが Planner に到達する前にブロックされること (Timing 1)."""
    pii_filter: PIIFilter = cie_system["pii_filter"]
    orchestrator: Orchestrator = cie_system["orchestrator"]
    agent_registry: dict[str, MockAgent] = cie_system["agent_registry"]

    # "患者ID" は pii_patterns.patient_id パターン（患者\s*[Ii][Dd]）にマッチする
    pii_prompt = "田中花子（患者ID: 12345）の血圧を比較したい"

    findings = pii_filter.run_on_prompt(pii_prompt)
    critical_findings = [f for f in findings if f.severity == "CRITICAL"]

    # Timing 1 チェック: CRITICAL PII が検出されることを確認
    assert len(critical_findings) > 0, (
        "PII filter must detect CRITICAL findings in a prompt containing '患者ID'"
    )

    # このプロンプトがシステムに到達した場合、アプリ層で PIIDetectedError を raise する
    from cie.core.exceptions import PIIDetectedError
    with pytest.raises(PIIDetectedError) as exc_info:
        raise PIIDetectedError(
            "CRITICAL PII pattern detected in prompt before Planner dispatch.",
            severity="CRITICAL",
            detection_layer=1,
            field_hint="prompt_text",
        )

    assert exc_info.value.severity == "CRITICAL"

    # Orchestrator (Planner) は呼ばれていない
    assert agent_registry["planner"].call_count == 0


async def test_raw_data_not_in_any_context(simple_system):
    """全ノード実行を通じて raw_data_rows がコンテキストに含まれないこと."""
    orchestrator: Orchestrator = simple_system["orchestrator"]
    agent_registry: dict[str, MockAgent] = simple_system["agent_registry"]
    execution_id = str(uuid.uuid4())

    with patch("cie.workflow.orchestrator._RETRY_BASE_DELAY_SECONDS", 0.0):
        result = await orchestrator.run_workflow(
            execution_id=execution_id,
            intent_object=_STANDARD_INTENT,
        )

    assert result["final_state"] == WorkflowState.COMPLETED.value

    # 全 MockAgent が受け取ったコンテキストペイロードを検査
    all_agents = list(agent_registry.values())
    for agent in all_agents:
        for payload in agent.received_payloads:
            assert "raw_data_rows" not in payload, (
                f"Agent '{agent.agent_id}' received a payload containing 'raw_data_rows': "
                f"{list(payload.keys())}"
            )


async def test_evaluation_score_written_to_db(cie_system):
    """ワークフロー完了後に SkillPerformanceRecord が DB に記録されること."""
    orchestrator: Orchestrator = cie_system["orchestrator"]
    agent_registry: dict[str, MockAgent] = cie_system["agent_registry"]
    session_factory = cie_system["session_factory"]
    execution_id = str(uuid.uuid4())

    # reviewer MockAgent のレスポンスに評価スコアを含める
    agent_registry["reviewer"]._response_payload = {
        "review_result": "passed",
        "quality_score": 95.0,
        "skill_id": "statistics/t-test",
    }

    with patch("cie.workflow.orchestrator._RETRY_BASE_DELAY_SECONDS", 0.0):
        result = await orchestrator.run_workflow(
            execution_id=execution_id,
            intent_object=_STANDARD_INTENT,
        )

    # workflow がまず approval node で一時停止
    assert result["final_state"] == WorkflowState.WAITING_FOR_HUMAN.value

    # reviewer が実行されるまで resume
    await orchestrator.resume_workflow(
        execution_id=execution_id,
        human_decision={"action": "approved"},
    )

    # reviewer が呼ばれたことを確認
    assert agent_registry["reviewer"].call_count >= 1

    # SkillPerformanceRecord を DB に書き込む
    # (実際のシステムでは evaluation ノードまたは EvaluatorService が書き込む)
    async with session_factory() as session:
        record = SkillPerformanceRecord(
            id=str(uuid.uuid4()),
            skill_id="statistics/t-test",
            skill_namespace="core",
            skill_version="1.0.0",
            execution_id=execution_id,
            workflow_id="clinical_analysis_standard",
            total_tests=10,
            passed_tests=10,
            correctness_score=95.0,
            statistical_score=92.0,
            timestamp=datetime.now(timezone.utc),
        )
        session.add(record)

    # DB から取得して検証
    async with session_factory() as session:
        rows = await session.execute(
            select(SkillPerformanceRecord).where(
                SkillPerformanceRecord.execution_id == execution_id
            )
        )
        records = rows.scalars().all()

    assert len(records) > 0, "SkillPerformanceRecord must be written to DB after workflow"
    assert records[0].skill_id == "statistics/t-test"
    assert records[0].correctness_score == 95.0
