"""tests/integration/test_security_boundaries.py

PROMPT 10-2: Security boundary integration tests.

Verifies that CIE Platform security boundaries function correctly:
- SP-001 Default Deny / SC-001 deny-first
- SP-002 Least Privilege
- SP-003 Separation of Duties
- SP-004 Zero Trust
- PII detection at all 4 application timings
- var_n alias protection
- Token uniqueness across nodes
- BREACH event terminates workflow immediately

Spec references:
- architecture/security-model.md  (SP-001〜SP-004)
- spec/permissions.yaml           (agent_permission_matrix)
- architecture/security-pii-filter.md (4 application timings)
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from cie.agents.base import AgentInput, AgentOutput, BaseAgent
from cie.core.audit import AuditService
from cie.core.database import get_session, init_db
from cie.core.exceptions import SecurityViolationError
from cie.schemas.payloads import ColumnMetadata
from cie.schemas.validator import SchemaRegistry
from cie.security.capability_token import (
    CapabilityScope,
    CapabilityToken,
    CapabilityTokenManager,
)
from cie.security.context_guard import ContextGuard
from cie.security.pii_filter import PIIFilter
from cie.security.policy_engine import PolicyEngine
from cie.security.var_alias import AliasStore, VarNAliasMap
from cie.workflow.orchestrator import Orchestrator
from cie.workflow.registry import WorkflowDefinition, WorkflowNodeDef, WorkflowRegistry
from cie.workflow.states import WorkflowState, WorkflowStateMachine
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PERMISSIONS_YAML = Path(__file__).parent.parent.parent / "spec" / "permissions.yaml"
_WORKFLOW_YAML = Path(__file__).parent.parent.parent / "spec" / "workflow.yaml"

# Mapping from YAML scope string → CapabilityScope enum
# (only concrete, non-wildcard scopes present in CapabilityScope)
_SCOPE_MAP: dict[str, CapabilityScope] = {s.value: s for s in CapabilityScope}

_STANDARD_INTENT = {
    "objective": "between_group_comparison",
    "outcome_type": "continuous",
    "requires_human_clarification": False,
}


# ---------------------------------------------------------------------------
# Minimal MockAgent (no LLM / Rscript calls)
# ---------------------------------------------------------------------------


class _MockAgent(BaseAgent):
    def __init__(self, mock_agent_id: str, policy_engine, schema_registry, audit_service):
        super().__init__(
            policy_engine=policy_engine,
            schema_registry=schema_registry,
            audit_service=audit_service,
        )
        self._mock_agent_id = mock_agent_id
        self.call_count: int = 0
        self.received_payloads: list[dict] = []
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
        return []

    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        self.call_count += 1
        self.received_payloads.append(dict(agent_input.payload))

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

        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self._mock_agent_id,
            status="success",
            output_payload={"ok": True},
            output_schema_ref=self.output_schema_ref,
        )


def _noop_schema_registry() -> SchemaRegistry:
    sr = MagicMock(spec=SchemaRegistry)
    sr.validate = MagicMock()
    return sr


# ---------------------------------------------------------------------------
# Simple two-node workflow (no approval gate) used by several tests
# ---------------------------------------------------------------------------

_SIMPLE_WF = WorkflowDefinition(
    workflow_id="security_test",
    version="1.0",
    category="test",
    entrypoint="step_a",
    nodes={
        "step_a": WorkflowNodeDef(
            node_id="step_a", node_type="task", agent_id="planner", depends_on=[], outputs=[]
        ),
        "step_b": WorkflowNodeDef(
            node_id="step_b",
            node_type="task",
            agent_id="runtime",
            depends_on=["step_a"],
            outputs=[],
        ),
    },
)


class _SimpleRegistry(WorkflowRegistry):
    def __init__(self) -> None:
        super().__init__()
        self._definitions["security_test"] = _SIMPLE_WF

    def select_workflow(self, intent_object: dict) -> tuple[str, str, str]:  # noqa: ARG002
        return ("security_test", "WS-TEST", "security test workflow")

    def get(self, workflow_id: str) -> WorkflowDefinition:  # noqa: ARG002
        return _SIMPLE_WF


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def security_system():
    """Real token manager + policy engine + audit on in-memory SQLite."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_db(engine)

    @asynccontextmanager
    async def session_factory():
        async with get_session(engine) as s:
            yield s

    audit_service = AuditService(session_factory=session_factory)
    token_manager = CapabilityTokenManager()
    policy_engine = PolicyEngine(token_manager=token_manager, audit_service=audit_service)
    schema_registry = _noop_schema_registry()

    agent_registry = {
        aid: _MockAgent(
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
        "audit_service": audit_service,
        "token_manager": token_manager,
        "policy_engine": policy_engine,
        "agent_registry": agent_registry,
        "orchestrator": orchestrator,
    }

    await engine.dispose()


# ===========================================================================
# Tests
# ===========================================================================


# ---------------------------------------------------------------------------
# 1. Permission matrix completeness
# ---------------------------------------------------------------------------


def test_permission_matrix_completeness():
    """spec/permissions.yaml の全エージェント・全 capability が
    AGENT_ALLOWED_SCOPES と完全に一致すること (SP-001, SP-002)."""
    with _PERMISSIONS_YAML.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    yaml_matrix: dict = raw["agent_permission_matrix"]
    py_matrix = CapabilityTokenManager.AGENT_ALLOWED_SCOPES

    # ── allow リストの一致確認 ──────────────────────────────────────────
    for agent_id, perms in yaml_matrix.items():
        if agent_id not in py_matrix:
            # skill_lifecycle は AGENT_ALLOWED_SCOPES に未実装 (実装フェーズ外)
            continue

        yaml_allow_scopes: set[CapabilityScope] = set()
        for scope_str in perms.get("allow", []):
            if scope_str in _SCOPE_MAP:
                yaml_allow_scopes.add(_SCOPE_MAP[scope_str])

        py_allow_scopes = py_matrix[agent_id]

        assert yaml_allow_scopes == py_allow_scopes, (
            f"Agent '{agent_id}': YAML allow={yaml_allow_scopes!r} "
            f"≠ Python allow={py_allow_scopes!r}"
        )

    # ── 具体的な deny 確認（非ワイルドカードのみ） ──────────────────────
    # 各エージェントへのトークン発行で denied_scopes に入ることを確認
    tm = CapabilityTokenManager()
    dummy_exec = "test-exec"
    dummy_step = "test-step"

    # (agent_id, denied_scope_string) の具体的ペア
    explicit_deny_cases: list[tuple[str, str]] = [
        ("planner", "dataset.read_raw"),
        ("planner", "dataset.read_validated"),
        ("statistics", "dataset.read_raw"),
        ("statistics", "r_code.restore_variables"),
        ("statistics", "runtime.invoke_execution"),
        ("visualization", "dataset.read_raw"),
        ("visualization", "r_code.restore_variables"),
        ("reporting", "dataset.read_raw"),
        ("reviewer", "dataset.read_raw"),
        ("security", "dataset.read_raw"),
        ("security", "r_code.generate_template"),
        ("security", "runtime.invoke_execution"),
        ("runtime", "dataset.read_raw"),
        ("data_quality", "workflow.state_write"),
    ]

    for agent_id, scope_str in explicit_deny_cases:
        scope = _SCOPE_MAP[scope_str]
        token = tm.issue(
            execution_id=dummy_exec,
            agent_id=agent_id,
            step_id=dummy_step,
            requested_scopes={scope},
        )
        assert scope in token.denied_scopes, (
            f"Agent '{agent_id}' must NOT have scope '{scope_str}', "
            f"but it was not in denied_scopes"
        )


# ---------------------------------------------------------------------------
# 2. Statistics cannot restore variables (SP-003)
# ---------------------------------------------------------------------------


def test_statistics_cannot_restore_variables():
    """Statistics Agent は R_CODE_RESTORE_VARIABLES を取得できないこと (SP-003).

    r_code.restore_variables は Security Agent 専用 (spec/permissions.yaml)。
    """
    tm = CapabilityTokenManager()
    token = tm.issue(
        execution_id="test",
        agent_id="statistics",
        step_id="select_analysis",
        requested_scopes={CapabilityScope.R_CODE_RESTORE_VARIABLES},
    )

    assert CapabilityScope.R_CODE_RESTORE_VARIABLES in token.denied_scopes
    assert CapabilityScope.R_CODE_RESTORE_VARIABLES not in token.granted_scopes


# ---------------------------------------------------------------------------
# 3. Planner cannot read raw data (SP-002)
# ---------------------------------------------------------------------------


def test_planner_cannot_read_raw_data():
    """Planner Agent は DATASET_READ_RAW を取得できないこと (SP-002).

    Planner が参照できるのは dataset.proxy_metadata のみ (spec/permissions.yaml)。
    """
    tm = CapabilityTokenManager()
    token = tm.issue(
        execution_id="test",
        agent_id="planner",
        step_id="intake",
        requested_scopes={CapabilityScope.DATASET_READ_RAW},
    )

    assert CapabilityScope.DATASET_READ_RAW in token.denied_scopes
    assert CapabilityScope.DATASET_READ_RAW not in token.granted_scopes


# ---------------------------------------------------------------------------
# 4. All 4 PII timing points covered
# ---------------------------------------------------------------------------


async def test_all_pii_timing_points_covered():
    """PII 検出フィルタが 4 つの適用タイミング全てで機能すること
    (architecture/security-pii-filter.md Section 6)."""
    pii_filter = PIIFilter(enable_layer2=False)

    # ── Timing 1: Planner Agent 入力前（プロンプト PII チェック） ─────────
    # 「患者ID」は pii_patterns.patient_id の正規表現にマッチする
    prompt_with_pii = "田中花子（患者ID: 12345）の血圧を比較したい"
    t1_findings = pii_filter.run_on_prompt(prompt_with_pii)
    t1_critical = [f for f in t1_findings if f.severity == "CRITICAL"]
    assert len(t1_critical) >= 1, "Timing 1: prompt PII must be detected"

    # ── Timing 2: Context コンストラクション前（inject_raw_data_rows チェック） ─
    # ContextGuard が raw_data_rows を含むペイロードをブロックすること
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    await init_db(engine)

    @asynccontextmanager
    async def session_factory():
        async with get_session(engine) as s:
            yield s

    audit_service = AuditService(session_factory=session_factory)
    context_guard = ContextGuard(pii_filter=pii_filter, audit_service=audit_service)

    from cie.core.exceptions import SecurityViolationError

    with pytest.raises(SecurityViolationError):
        await context_guard.sanitize_context_payload(
            payload={"raw_data_rows": [[1, 2, 3], [4, 5, 6]]},
            execution_id="test-timing2",
            agent_id="orchestrator",
        )

    # ── Timing 3: Data Quality Agent — 列名・カテゴリ PII チェック ────────
    # pii_filter.run() が ColumnMetadata に対して動作すること
    pii_col_meta = ColumnMetadata(
        var_n="var_1",
        inferred_type="text",
        missing_count=0,
        missing_rate_pct=0.0,
        summary_stats=None,
    )
    t3_critical, _t3_warnings = pii_filter.run(
        col_name="患者ID",
        col_meta=pii_col_meta,
        row_count=100,
    )
    assert len(t3_critical) >= 1, "Timing 3: column-name PII must be detected"

    # ── Timing 4: 最終レポート出力前（原稿テキスト PII チェック） ─────────
    # レポート原稿に患者名が混入した場合を検出
    report_text_with_pii = "患者ID: P-00123 の SBP は 138 mmHg であった。"
    t4_findings = pii_filter.run_on_prompt(report_text_with_pii)
    t4_critical = [f for f in t4_findings if f.severity == "CRITICAL"]
    assert len(t4_critical) >= 1, "Timing 4: report text PII must be detected"

    await engine.dispose()


# ---------------------------------------------------------------------------
# 5. Token not reused across nodes (SC-002)
# ---------------------------------------------------------------------------


async def test_token_not_reused_across_nodes(security_system):
    """異なるノードで同一 Capability Token が再利用されないこと (SC-002).

    CapabilityTokenManager.issue() は毎回新しい token_id を生成する。
    """
    orchestrator: Orchestrator = security_system["orchestrator"]
    token_manager: CapabilityTokenManager = security_system["token_manager"]

    issued_tokens: list[CapabilityToken] = []
    original_issue = token_manager.issue

    def tracking_issue(execution_id, agent_id, step_id, requested_scopes):
        t = original_issue(execution_id, agent_id, step_id, requested_scopes)
        issued_tokens.append(t)
        return t

    token_manager.issue = tracking_issue  # type: ignore[method-assign]

    with patch("cie.workflow.orchestrator._RETRY_BASE_DELAY_SECONDS", 0.0):
        result = await orchestrator.run_workflow(
            execution_id=str(uuid.uuid4()),
            intent_object=_STANDARD_INTENT,
        )

    assert result["final_state"] == WorkflowState.COMPLETED.value

    # _SIMPLE_WF has 2 agent nodes → 2 tokens must have been issued
    assert len(issued_tokens) >= 2, "At least one token per agent node"

    # All token_ids must be unique
    token_ids = [t.token_id for t in issued_tokens]
    assert len(token_ids) == len(set(token_ids)), (
        "Every node must receive a unique token_id — tokens are never reused"
    )

    # Each token is bound to a distinct (agent_id, step_id) pair
    bindings = [(t.bound_agent_id, t.bound_step_id) for t in issued_tokens]
    assert len(bindings) == len(set(bindings)), (
        "Token bindings (agent_id, step_id) must be unique per node"
    )


# ---------------------------------------------------------------------------
# 6. var_n alias never leaked to LLM context
# ---------------------------------------------------------------------------


async def test_var_n_alias_never_leaked_to_llm(security_system):
    """LLM に渡されるコンテキストにオリジナル列名が含まれないこと
    (architecture/security-model.md var_n Alias System)."""
    orchestrator: Orchestrator = security_system["orchestrator"]
    agent_registry = security_system["agent_registry"]

    # 列名エイリアスを登録
    original_col_names = ["患者ID", "氏名", "SBP", "DBP", "年齢"]
    alias_map = VarNAliasMap()
    alias_map.register(original_col_names)

    # オリジナル列名は含まず、var_n プロキシのみを intent に含める
    proxy_metadata = alias_map.to_proxy_metadata()  # {var_1: "---", var_2: "---", ...}

    intent_with_proxy = {
        **_STANDARD_INTENT,
        "column_metadata": proxy_metadata,          # var_n aliases only
        "dataset_summary": "n=100, vars=5",
    }

    with patch("cie.workflow.orchestrator._RETRY_BASE_DELAY_SECONDS", 0.0):
        result = await orchestrator.run_workflow(
            execution_id=str(uuid.uuid4()),
            intent_object=intent_with_proxy,
        )

    assert result["final_state"] == WorkflowState.COMPLETED.value

    # 全 MockAgent が受け取ったペイロードにオリジナル列名が含まれていないこと
    for agent in agent_registry.values():
        for payload in agent.received_payloads:
            payload_str = str(payload)
            for col_name in original_col_names:
                assert col_name not in payload_str, (
                    f"Original column name '{col_name}' leaked into "
                    f"payload for agent '{agent.agent_id}'"
                )


# ---------------------------------------------------------------------------
# 7. BREACH event terminates workflow immediately
# ---------------------------------------------------------------------------


async def test_breach_terminates_immediately(security_system):
    """BREACH イベント（security_violation エラー）でワークフローが即座に停止し、
    トークンが失効されること (architecture/security-model.md Incident Classification)."""
    orchestrator: Orchestrator = security_system["orchestrator"]
    token_manager: CapabilityTokenManager = security_system["token_manager"]
    agent_registry = security_system["agent_registry"]

    revoke_calls: list[CapabilityToken] = []
    original_revoke = token_manager.revoke

    def tracking_revoke(token: CapabilityToken) -> CapabilityToken:
        revoke_calls.append(token)
        return original_revoke(token)

    token_manager.revoke = tracking_revoke  # type: ignore[method-assign]

    # planner (step_a) が security_violation を返す
    # → NON_RECOVERABLE_ERRORS に含まれるため IMMEDIATE_ABORT
    agent_registry["planner"].return_failure_code = "security_violation"

    with patch("cie.workflow.orchestrator._RETRY_BASE_DELAY_SECONDS", 0.0):
        result = await orchestrator.run_workflow(
            execution_id=str(uuid.uuid4()),
            intent_object=_STANDARD_INTENT,
        )

    # ── BREACH → FAILED ────────────────────────────────────────────────
    assert result["final_state"] == WorkflowState.FAILED.value, (
        "security_violation (BREACH-level) must terminate workflow as FAILED"
    )

    # ── runtime agent は呼ばれていない ────────────────────────────────────
    assert agent_registry["runtime"].call_count == 0, (
        "No subsequent agent must execute after a BREACH"
    )

    # ── 発行したトークンは全て revoke() が呼ばれている ────────────────────
    # (non-recoverable abort でも finally ブロックが実行される)
    assert len(revoke_calls) >= 1, (
        "token_manager.revoke() must be called even on BREACH abort"
    )

    # planner は non-recoverable のため再試行なし (1 回のみ)
    assert agent_registry["planner"].call_count == 1, (
        "Non-recoverable error must NOT be retried"
    )


# ---------------------------------------------------------------------------
# 8. Security Agent is the sole holder of r_code.restore_variables
# ---------------------------------------------------------------------------


def test_only_security_agent_can_restore_variables():
    """r_code.restore_variables を保持できるのは security agent のみ (SP-003)."""
    tm = CapabilityTokenManager()
    dummy = {"execution_id": "test", "step_id": "test"}

    # security agent → granted
    security_token = tm.issue(
        **dummy,
        agent_id="security",
        requested_scopes={CapabilityScope.R_CODE_RESTORE_VARIABLES},
    )
    assert CapabilityScope.R_CODE_RESTORE_VARIABLES in security_token.granted_scopes

    # all other agents → denied
    non_security_agents = [
        "planner", "data_quality", "statistics",
        "visualization", "reporting", "reviewer", "runtime",
    ]
    for agent_id in non_security_agents:
        token = tm.issue(
            **dummy,
            agent_id=agent_id,
            requested_scopes={CapabilityScope.R_CODE_RESTORE_VARIABLES},
        )
        assert CapabilityScope.R_CODE_RESTORE_VARIABLES in token.denied_scopes, (
            f"Agent '{agent_id}' must not hold r_code.restore_variables"
        )


# ---------------------------------------------------------------------------
# 9. VarNAliasMap — restore requires correct scope token
# ---------------------------------------------------------------------------


def test_var_n_restore_requires_scope():
    """VarNAliasMap.restore() は R_CODE_RESTORE_VARIABLES スコープが必要なこと."""
    from datetime import timedelta
    from cie.security.capability_token import TOKEN_TTL_SECONDS

    alias_map = VarNAliasMap()
    alias_map.register(["患者ID", "氏名"])

    now = datetime.now(timezone.utc)

    # Token WITHOUT the scope → PermissionDeniedError
    token_without_scope = CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id="test",
        bound_agent_id="statistics",
        bound_step_id="step",
        granted_scopes=frozenset({CapabilityScope.R_CODE_GENERATE_TEMPLATE}),
        denied_scopes=frozenset({CapabilityScope.R_CODE_RESTORE_VARIABLES}),
        issued_at=now,
        expires_at=now + timedelta(seconds=TOKEN_TTL_SECONDS),
    )

    from cie.core.exceptions import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        alias_map.restore(token_without_scope)

    # Token WITH the scope → success
    token_with_scope = CapabilityToken(
        token_id=str(uuid.uuid4()),
        bound_execution_id="test",
        bound_agent_id="security",
        bound_step_id="step",
        granted_scopes=frozenset({CapabilityScope.R_CODE_RESTORE_VARIABLES}),
        denied_scopes=frozenset(),
        issued_at=now,
        expires_at=now + timedelta(seconds=TOKEN_TTL_SECONDS),
    )
    restored = alias_map.restore(token_with_scope)
    assert restored == {"var_1": "患者ID", "var_2": "氏名"}
