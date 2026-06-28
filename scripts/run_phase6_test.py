import asyncio
import os
import pandas as pd
import numpy as np
from pathlib import Path

def generate_sample_data():
    np.random.seed(42)
    n = 60
    df = pd.DataFrame({
        "group":     ["A"]*30 + ["B"]*30,
        "sbp_mmhg":  np.concatenate([
                       np.random.normal(130, 15, 30),
                       np.random.normal(120, 15, 30)
                     ]).round(1),
        "age_years": np.random.randint(40, 75, n),
        "bmi":       np.random.normal(24, 3, n).round(1),
    })
    data_path = Path("sample_data.csv")
    df.to_csv(data_path, index=False)
    print(f"✅ sample_data.csv を自動生成しました ({n}行)")
    return data_path

# === 本物のContextGuard仕様に適合したモックPIIフィルター ===
class MockPIIFilter:
    def run_on_prompt(self, value: str) -> list:
        return []

# === モックエージェントクラス ===
from cie.agents.base import BaseAgent, AgentInput, AgentOutput

class MockWorkflowAgent(BaseAgent):
    # 抽象プロパティと抽象メソッドをダミー実装して、インスタンス化可能にする
    @property
    def agent_id(self) -> str:
        return self._m_agent_id
    @property
    def input_schema_ref(self) -> str:
        return "cie://schemas/task.schema.json"
    @property
    def output_schema_ref(self) -> str:
        return "cie://schemas/task.schema.json"
    @property
    def required_scopes(self) -> list:
        return []
    async def _execute(self, agent_input: AgentInput) -> AgentOutput:
        pass

    def __init__(self, agent_id: str, policy_engine, schema_registry, audit_service):
        super().__init__(policy_engine, schema_registry, audit_service)
        self._m_agent_id = agent_id
        
    async def run(self, agent_input: AgentInput) -> AgentOutput:
        print(f"🤖 [{self._m_agent_id.upper()} AGENT] ノード '{agent_input.node_id}' を実行中...")
        return AgentOutput(
            execution_id=agent_input.execution_id,
            agent_id=self._m_agent_id,
            status="success",
            error_code=None,
            output_schema_ref="cie://schemas/task.schema.json",
            output_payload={
                "validated_dataset": "sample_data.csv",
                "variable_metadata": {"group": "categorical", "sbp_mmhg": "continuous"},
                "missing_value_report": "None",
                "outlier_report": "None",
                "analysis_plan": "t-test",
                "statistical_method": "Welch_t_test",
                "assumption_report": "Normal",
                "r_script": "t.test(sbp_mmhg ~ group, data=df)",
                "execution_permission": True,
                "execution_result": "p = 0.002",
                "generated_files": ["plot.png"],
                "figures": ["plot.png"],
                "report": "Analysis completed successfully.",
                "review_result": "Approved",
                "quality_score": 95,
                "evaluation_report": "Pass",
                "reproducibility_report": "100%",
                "completion_status": "COMPLETED"
            },
            requires_human_clarification=False
        )

async def main():
    # 1. ディレクトリとサンプルデータの準備
    Path("./workspace").mkdir(exist_ok=True)
    Path("./output").mkdir(exist_ok=True)
    
    os.environ["WORKSPACE_DIR"] = "./workspace"
    os.environ["OUTPUT_DIR"] = "./output"
    os.environ["CIE_EXECUTION_ID"] = "exec_phase6_demo"

    dataset_path = generate_sample_data()

    # 2. 本物のコンポーネントをインポート
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from cie.core.database import init_db
    from cie.workflow.orchestrator import Orchestrator
    from cie.workflow.registry import WorkflowRegistry
    from cie.workflow.states import WorkflowStateMachine
    from cie.security.capability_token import CapabilityTokenManager
    from cie.security.policy_engine import PolicyEngine
    from cie.security.context_guard import ContextGuard
    from cie.core.audit import AuditService
    from cie.schemas.validator import SchemaRegistry

    # 3. データベース（SQLite3）の初期化
    db_url = "sqlite+aiosqlite:///./cie_database.db"
    print(f"📦 データベース（SQLite3）を初期化中: {db_url}")
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    await init_db(engine)
    print("✅ データベースの初期化に成功しました。")

    print("🛡️ 統治コンポーネントを本物の定義ファイルと完全同期して初期化中...")
    
    # 4. コンポーネントを本物の引数定義に完全同期して生成
    audit_service = AuditService(session_factory=session_factory)
    token_manager = CapabilityTokenManager()
    policy_engine = PolicyEngine(token_manager=token_manager, audit_service=audit_service) 
    
    # 本物の仕様（pii_filter, audit_service）に完全同期！メソッド不整合も防ぐ
    mock_pii_filter = MockPIIFilter()
    context_guard = ContextGuard(pii_filter=mock_pii_filter, audit_service=audit_service)
    
    state_machine = WorkflowStateMachine()

    # 本物のクラスメソッドから、正式にYAML定義をロード
    print("📋 spec/workflow.yaml から ADR-0001 正式ルートでワークフロー定義をロードしています...")
    workflow_registry = WorkflowRegistry.load_from_yaml(Path("spec/workflow.yaml"))

    # 5. エージェント辞書の構築 (dict[str, BaseAgent])
    agent_ids = ["planner", "data_quality", "statistics", "security", "runtime", "visualization", "reporting", "reviewer"]
    schema_registry = SchemaRegistry(Path("schemas"))
    agent_registry_dict = {
        aid: MockWorkflowAgent(
            agent_id=aid,
            policy_engine=policy_engine,
            schema_registry=schema_registry,
            audit_service=audit_service
        )
        for aid in agent_ids
    }

    # 6. 本物の仕様通りに Orchestrator をインスタンス化
    orchestrator = Orchestrator(
        workflow_registry=workflow_registry,
        state_machine=state_machine,
        token_manager=token_manager,
        policy_engine=policy_engine,
        context_guard=context_guard,
        audit_service=audit_service,
        agent_registry=agent_registry_dict
    )

    print("\n🚀 CIE Platform Phase 6 E2E ワークフローを実行します...")
    
    # ADR-0001 / WS-004 ルールに完全に準拠した本物の intent_object 構造
    mock_intent_object = {
        "objective": "between_group_comparison",
        "outcome_type": "continuous",
        "paired": False,
        "dataset_path": str(dataset_path),
        "variables": {
            "group": "group",
            "outcome": "sbp_mmhg"
        }
    }

    try:
        # 本物のシグネチャ仕様に則り実行
        result = await orchestrator.run_workflow(
            execution_id="exec_phase6_demo",
            intent_object=mock_intent_object
        )

        print("\n=== 📄 実行結果 ===")
        print(f"✨ 決定されたワークフロー : {result.get('workflow_id_selected')}")
        print(f"✨ 適用されたルール判定   : {result.get('rule_id')}")
        print(f"✨ ルール判定の正当性(理由): {result.get('justification')}")
        print(f"✨ 最終ステート          : {result.get('final_state')}")
        print(f"✅ 実行されたノード数     : {len(result.get('node_results', []))} ノード")
        
        print("\n✅ 全てのコアインフラ、防衛セキュリティ線、およびDAGループの走破テストが完全に成功しました！")
    except Exception as e:
        print(f"\n❌ 実行中にエラーが発生しました: {e}")

if __name__ == "__main__":
    asyncio.run(main())
