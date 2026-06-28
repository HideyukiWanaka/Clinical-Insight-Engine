# CIE Platform — Claude Code Implementation Prompts
# Phase 4: Runtime Provider
# Phase 5: Core Agents
# Phase 6: Workflow Engine & Orchestrator
# File: prompts/phase4_6_runtime_agents_workflow.md
# Version: 1.1.0

---

# ═══════════════════════════════════════
# PHASE 4: RUNTIME PROVIDER
# ═══════════════════════════════════════

## PROMPT 4-0: ブランチ作成

```
# Phase 3 が main に merge 済みであることを確認してから実行してください。
git checkout main
git pull origin main
git checkout -b feature/phase-4-runtime
```

---



## PROMPT 4-1: Rスクリプト実行エンジン

```
CIE PlatformのLocal Restricted Runtime（R実行部分）を実装してください。
Rscriptをサブプロセスで安全に実行し、結果を収集します。

### 読み込むべき仕様ファイル
- spec/runtime.yaml (local_restricted_runtime セクション全体)
- agents/runtime.yaml (RT-001〜RT-006ルール)
- knowledge/R/statistical_packages.md (Forbidden R Patterns セクション)

### 前提
- PROMPT 3-2の ContextGuard.sanitize_stdout() が存在します
- PROMPT 1-1の RuntimeExecutionError が存在します

### 作成するもの

1. `cie/runtime/r_executor.py` を作成してください：

```python
# ExecutionResult dataclass:
#   execution_id: str
#   status: Literal["success", "timeout", "error", "security_abort"]
#   exit_code: int
#   duration_ms: int
#   stdout_digest: str    # sanitize_stdout後のsha256ハッシュ
#   stderr_digest: str    # sanitize後のsha256ハッシュ
#   sanitized_stdout_summary: str  # 最初の1000文字のみ（sanitize済み）
#   output_artifacts: list[str]    # OUTPUT_DIR内の相対パス
#   r_version: str | None
#   package_versions: dict[str, str]  # {"tidyverse": "2.0.0"} etc.
#   dataset_hash: str | None      # スクリプトから抽出

# FORBIDDEN_R_PATTERNS: list[re.Pattern]
#   # knowledge/R/statistical_packages.md の Forbidden R Patterns テーブルより
#   # system(), system2(), shell(), Sys.setenv(), install.packages()
#   # options(warn=-1) を検出するパターン

# RScriptValidator クラス:
#   def validate(self, script_content: str) -> list[str]:
#     - FORBIDDEN_R_PATTERNSをスクリプト内容にマッチング
#     - 検出された禁止パターンの説明リストを返す（空リストなら合格）
#     - 絶対パス（C:\\, /home/, /etc/ 等）の使用も検出する

# LocalRExecutor クラス:
#   MAX_EXECUTION_SECONDS: int = 300  # spec/runtime.yaml
#   MAX_MEMORY_MB: int = 4096
#   MAX_STDOUT_BYTES: int = 1048576   # 1 MB
#
#   __init__(
#       self,
#       workspace_dir: Path,
#       output_dir: Path,
#       context_guard: ContextGuard
#   ) -> None
#
#   async def execute(
#       self,
#       execution_id: str,
#       script_path: Path,
#       capability_token: CapabilityToken
#   ) -> ExecutionResult:
#     1. capability_token.require_scope(RUNTIME_INVOKE_EXECUTION)
#     2. RScriptValidator().validate(script_path.read_text()) → 違反があればRuntimeExecutionError
#     3. 環境変数を設定:
#        CIE_EXECUTION_ID, WORKSPACE_DIR, OUTPUT_DIR
#        （それ以外の環境変数は継承しない）
#     4. asyncio.create_subprocess_exec で Rscript --vanilla --slave を実行
#        （shell=False必須）
#     5. asyncio.wait_for でMAX_EXECUTION_SECONDS以内に完了しなければtimeout
#     6. stdoutをcontextguard.sanitize_stdout()に通す
#     7. OUTPUT_DIR内のファイルを列挙してoutput_artifactsに含める
#     8. ExecutionResultを構築して返す
#
#   def _collect_r_session_info(self, stdout: str) -> dict:
#     # sessionInfo()の出力からRバージョン・パッケージバージョンを抽出
#     # 正規表現でパース（外部ツール不使用）
```

2. `tests/unit/test_r_executor.py` を作成してください：

```python
# テスト項目（実際のRscript実行は不要。モックで代替）:
# - test_validate_system_call_detected: "system('ls')" -> 違反検出
# - test_validate_install_packages_detected: "install.packages()" -> 違反検出
# - test_validate_absolute_path_detected: "/home/user/data.csv" -> 違反検出
# - test_validate_clean_script_passes: 正常スクリプト -> 違反なし
# - test_scope_check_required: RuntimeExecutionError if scope missing
# - test_timeout_handled: タイムアウト時のstatus="timeout"
# - test_output_artifacts_collected: OUTPUT_DIR内ファイルが収集されること
# - test_forbidden_env_vars_not_passed: PATH等が継承されないこと
```

### 制約事項
- subprocess.run()禁止（asyncio.create_subprocess_exec必須）
- shell=True禁止（shell=False必須）
- 環境変数はCIE_EXECUTION_ID, WORKSPACE_DIR, OUTPUT_DIRの3つのみ設定
- stdoutとstderrをバッファ上限(1MB/512KB)で切り捨てること
- rawデータをscriptに埋め込まないこと（script_pathを受け取るだけ）
```

---

## PROMPT 4-X: Phase 4 完了処理

```
Phase 4 の全実装（PROMPT 4-1〜4-2）が完了し、テストがすべてパスしたことを
確認してから、以下の手順でブランチを main へ統合してください。

### テスト確認
pytest tests/unit/test_r_executor.py tests/unit/test_runtime_provider.py -v

### コミット
git add -A
git commit -m "feat(phase4): local restricted runtime — R executor & runtime provider"

### main へ merge
git checkout main
git merge --no-ff feature/phase-4-runtime \
  -m "merge: phase-4-runtime into main"

### 次フェーズのブランチを main から作成
git checkout -b feature/phase-5-agents
```

---

# ═══════════════════════════════════════
# PHASE 5: CORE AGENTS
# ═══════════════════════════════════════

## PROMPT 5-0: ブランチチェック

```
# Phase 4 が main に merge 済みであることを確認し、
# feature/phase-5-agents ブランチにいることを確認してから作業を開始してください。
git branch   # 現在ブランチの確認
```

## PROMPT 5-1: Agent基底クラス

```
CIE Platformの全Agentが継承する基底クラスを実装してください。

### 読み込むべき仕様ファイル
- schemas/agent.schema.json (AgentContract, BehaviorRule)
- agents/orchestrator.yaml (task_dispatch_loop cycle_steps 4〜6)
- PROJECT_RULES.md Section 9（Agent Rules）

### 前提
- PROMPT 3-1の CapabilityToken が存在します
- PROMPT 3-2の PolicyEngine が存在します
- PROMPT 2-1の SchemaRegistry が存在します
- PROMPT 1-3の AuditService が存在します

### 作成するもの

1. `cie/agents/base.py` を作成してください：

```python
# AgentInput dataclass:
#   execution_id: str
#   node_id: str
#   capability_token: CapabilityToken
#   payload: dict          # スキーマ検証済みのコンテキストペイロード
#   input_schema_ref: str  # 検証に使用したスキーマのURI

# AgentOutput dataclass:
#   execution_id: str
#   agent_id: str
#   status: Literal["success", "failed", "clarification_required"]
#   output_payload: dict
#   output_schema_ref: str
#   error_code: str | None = None
#   error_message: str | None = None
#   requires_human_clarification: bool = False
#   clarification_options: list[dict] = []

# BaseAgent 抽象クラス:
#   agent_id: str  # abstractproperty
#   input_schema_ref: str  # abstractproperty
#   output_schema_ref: str  # abstractproperty
#   required_scopes: list[CapabilityScope]  # abstractproperty
#
#   __init__(
#       self,
#       policy_engine: PolicyEngine,
#       schema_registry: SchemaRegistry,
#       audit_service: AuditService
#   ) -> None
#
#   async def run(self, agent_input: AgentInput) -> AgentOutput:
#     # テンプレートメソッドパターン — サブクラスが _execute() を実装
#     1. required_scopesを全てenforce（policy_engine.enforce_multi）
#     2. input_payloadをスキーマ検証（schema_registry.validate）
#     3. self._execute(agent_input)を呼ぶ
#     4. output_payloadをスキーマ検証（schema_registry.validate）
#     5. audit_service.write()でAgent実行を記録
#     6. AgentOutputを返す
#     # 各ステップで例外が発生した場合はAgentOutputのstatus="failed"で返す
#
#   @abstractmethod
#   async def _execute(self, agent_input: AgentInput) -> AgentOutput:
#     ...
```

2. `tests/unit/test_base_agent.py` を作成してください：

```python
# ConcreteTestAgent（BaseAgentの最小実装）を作って以下をテスト:
# - test_scope_enforced: required_scopesチェックが実行されること
# - test_input_validated: 無効なpayloadでstatus="failed"
# - test_output_validated: 無効な出力payloadでstatus="failed"
# - test_audit_written: 成功時もauditが記録されること
# - test_execution_error_returns_failed_status: _execute内の例外がstatus="failed"に変換
```

### 制約事項
- _execute()は直接呼ばないこと（必ずrun()経由）
- スキーマ検証をバイパスするオプションを追加しないこと
- audit_service.write()の失敗はログ出力のみ（再送出しない）
```

---

## PROMPT 5-2: Planner Agent

```
CIE PlatformのPlanner Agentを実装してください。
自然言語プロンプトをintent_objectに変換します。

### 読み込むべき仕様ファイル
- agents/planner.yaml (全セクション — PL-001〜PL-006ルール)
- schemas/analysis-request.schema.json
- knowledge/statistics/method_selection_guide.md (Step 0 Mapping Table)
- spec/permissions.yaml (planner の allow/deny)

### 前提
- PROMPT 5-1の BaseAgent が存在します
- PROMPT 3-2の ContextGuard が存在します

### 作成するもの

1. `cie/agents/planner.py` を作成してください：

```python
# PlannerAgent(BaseAgent) クラス:
#   agent_id = "planner"
#   input_schema_ref = "cie://schemas/task.schema.json"
#   output_schema_ref = "cie://schemas/analysis-request.schema.json"
#   required_scopes = [
#       CapabilityScope.DATASET_PROXY_METADATA,
#       CapabilityScope.WORKFLOW_STATE_READ,
#       CapabilityScope.AUDIT_WRITE_ENTRY
#   ]
#
#   async def _execute(self, agent_input: AgentInput) -> AgentOutput:
#     # agent_input.payload から以下を取得:
#     #   user_natural_language_prompt: str
#     #   dataset_structural_metadata: dict
#     #
#     # Step 1: context_guard.sanitize_context_payload() でPIIチェック
#     # Step 2: LLMに送信するプロンプトを構築
#     #   - system: agents/planner.yaml の behavior_rules (PL-001〜006) を含める
#     #   - user: 自然言語プロンプト + dataset_structural_metadata（var_nのみ）
#     #   - inject_raw_data_rows=false を構造的に強制
#     # Step 3: LLM呼び出し（self._call_llm()）
#     # Step 4: レスポンスをanalysis-request.schema.jsonに検証
#     # Step 5: PL-005: paired=trueでsubject_id_var=nullならrequires_human_clarification=true
#     # Step 6: AgentOutputを構築して返す
#
#   async def _call_llm(
#       self,
#       system_prompt: str,
#       user_message: str
#   ) -> dict:
#     # LLMプロバイダーへのHTTPリクエスト（httpx使用）
#     # レスポンスのJSONをパース
#     # エラー時はAgentError("INTENT_EXTRACTION_FAILED")
#
#   def _build_system_prompt(self) -> str:
#     # PL-001: JSON出力のみ
#     # PL-002: 臨床疫学概念へのマッピング指示
#     # PL-003: 曖昧性検出
#     # PL-004: paired推定シグナル一覧
#     # PL-005: subject_id_var特定ルール
#     # PL-006: n_groups_estimate推定ルール
#     # analysis-request.schema.jsonのIntentObjectスキーマを含める
#     # 【重要】workflow_idを出力に含めてはならない旨を明記（ADR-0001）
```

2. `tests/unit/test_planner.py` を作成してください：

```python
# LLMをモック化してテスト:
# - test_paired_null_triggers_clarification: "3ヶ月と6ヶ月を比較" でrequires_human_clarification=true
# - test_paired_true_without_subject_id: paired=trueでsubject_id_var=nullのとき同上
# - test_workflow_id_not_in_output: output_payloadに"workflow_id"キーがないこと
# - test_pii_in_prompt_blocked: PIIを含むプロンプトでPIIDetectedError
# - test_raw_data_rows_blocked: raw_data_rowsキーでSecurityViolationError
```

### 制約事項
- output_payloadに "workflow_id" フィールドを絶対に含めないこと（ADR-0001）
- inject_raw_data_rowsをFalseにするチェックを省略しないこと
- LLMへのリクエストはhttpxのみ使用（requestsライブラリ禁止）
```

---

## PROMPT 5-3: Data Quality Agent

```
CIE PlatformのData Quality Agentを実装してください。
データセットの品質を検証し、PIIを検出します。

### 読み込むべき仕様ファイル
- agents/data-quality.yaml (全セクション — DQ-001〜DQ-005ルール)
- schemas/dataset.schema.json
- schemas/report.schema.json (quality_report_section)
- knowledge/statistics/missing_data_taxonomy.md (閾値定義)
- architecture/security-pii-filter.md (適用タイミング3)

### 前提
- PROMPT 5-1の BaseAgent が存在します
- PROMPT 2-3の PIIFilter が存在します

### 作成するもの

1. `cie/agents/data_quality.py` を作成してください：

```python
# DataQualityAgent(BaseAgent) クラス:
#   agent_id = "data-quality"
#   CRITICAL_MISSING_THRESHOLD: float = 20.0  # data-quality.yaml
#   WARNING_MISSING_THRESHOLD: float = 5.0
#
#   async def _execute(self, agent_input: AgentInput) -> AgentOutput:
#     # agent_input.payloadから DatasetMetadata を取得
#     # DQ-001: rawデータへのアクセスは行わない
#     #         （metadata_typeがproxy_metadataかvalidated_structuralのみ受け入れる）
#
#     # Step 1: 欠損値チェック（全カラム）
#     critical_findings = []
#     advisory_findings = []
#     for col in dataset_metadata.columns:
#       if col.missing_rate_pct >= CRITICAL_MISSING_THRESHOLD:
#           critical_findings.append(...)  # DQ-003
#       elif col.missing_rate_pct >= WARNING_MISSING_THRESHOLD:
#           advisory_findings.append(...)  # DQ-003
#
#     # Step 2: PII検出（Layer 1 + Layer 2）
#     #   pii_filter.run()を全カラムに適用
#     #   CRITICALのPII検出 → critical_findingsに追加
#     #   WARNING → advisory_findingsに追加
#
#     # Step 3: quality_gate_passed の決定
#     quality_gate_passed = len(critical_findings) == 0
#
#     # Step 4: report.schema.json のquality_report_section形式で出力
#     output = {
#       "execution_id": agent_input.execution_id,
#       "report_id": str(uuid4()),
#       "report_type": "quality_report",
#       "produced_by_agent_id": "data-quality",
#       "schema_version": "1.0",
#       "gate_passed": quality_gate_passed,
#       "critical_findings": [...],  # Finding形式
#       "advisory_findings": [...],
#       "quality_report_section": {
#         "columns_evaluated": len(dataset_metadata.columns),
#         "columns_with_critical_missing": ...,
#         "columns_with_warning_missing": ...,
#         ...
#       }
#     }
```

2. `tests/unit/test_data_quality.py` を作成してください：

```python
# テスト項目:
# - test_high_missing_rate_critical: 欠損率25% -> critical_finding
# - test_moderate_missing_rate_warning: 欠損率10% -> advisory_finding
# - test_low_missing_rate_passes: 欠損率3% -> findings空
# - test_pii_column_name_detected: "患者ID"カラム -> critical finding
# - test_quality_gate_false_when_critical: critical findingありでgate_passed=False
# - test_quality_gate_true_when_only_warnings: warningのみでgate_passed=True
# - test_raw_data_not_accessed: DQ-001 — metadata_typeがproxy_metadataのみ受け入れ
# - test_output_conforms_to_schema: 出力がreport.schema.jsonを通過すること
```

### 制約事項
- DQ-001厳守: rawデータ行値を一切受け取らない・処理しない
- PIIフィルタをスキップするオプションを作らない
- quality_gate_passedはcritical_findingsが空の場合のみTrueになること
```

---

## PROMPT 5-X: Phase 5 完了処理

```
Phase 5 の全実装（PROMPT 5-1〜5-5）が完了し、テストがすべてパスしたことを
確認してから、以下の手順でブランチを main へ統合してください。

### テスト確認
pytest tests/unit/test_base_agent.py tests/unit/test_statistics_agent.py \
       tests/unit/test_visualization_agent.py tests/unit/test_reporting_agent.py \
       tests/unit/test_data_quality_agent.py -v

### コミット
git add -A
git commit -m "feat(phase5): core agents — base, statistics, visualization, reporting, data-quality"

### main へ merge
git checkout main
git merge --no-ff feature/phase-5-agents \
  -m "merge: phase-5-agents into main"

### 次フェーズのブランチを main から作成
git checkout -b feature/phase-6-workflow
```

---

# ═══════════════════════════════════════
# PHASE 6: WORKFLOW ENGINE & ORCHESTRATOR
# ═══════════════════════════════════════

## PROMPT 6-0: ブランチチェック

```
# Phase 5 が main に merge 済みであることを確認し、
# feature/phase-6-workflow ブランチにいることを確認してから作業を開始してください。
git branch   # 現在ブランチの確認
```

## PROMPT 6-1: ワークフロー状態機械

```
CIE PlatformのWorkflow State Machineを実装してください。
ADR-0001に従い、静的ワークフロー定義の管理と状態遷移を担います。

### 読み込むべき仕様ファイル
- spec/workflow.yaml (states, workflow_selection_rules, 4ワークフロー定義)
- agents/orchestrator.yaml (state_machine, workflow_selection セクション)
- schemas/workflow.schema.json
- decisions/ADR-0001.md (全原則)

### 前提
- PROMPT 1-2の WorkflowInstance テーブルが存在します
- PROMPT 1-1の WorkflowError が存在します

### 作成するもの

1. `cie/workflow/states.py` を作成してください：

```python
# WorkflowState Enum（spec/workflow.yaml states 全10値）:
#   DRAFT = "draft"
#   VALIDATED = "validated"
#   PLANNED = "planned"
#   RUNNING = "running"
#   WAITING_FOR_HUMAN = "waiting_for_human"
#   RETRYING = "retrying"
#   COMPLETED = "completed"
#   FAILED = "failed"
#   CANCELLED = "cancelled"
#   ARCHIVED = "archived"

# VALID_TRANSITIONS: dict[WorkflowState, set[WorkflowState]]
#   # orchestrator.yaml valid_statesと整合する遷移マップ
#   # 例: DRAFT -> {VALIDATED, FAILED, CANCELLED}
#   # COMPLETED/FAILED/CANCELLEDからの遷移はARCHIVEDのみ

# StateTransitionError(WorkflowError) クラス

# WorkflowStateMachine クラス:
#   def transition(
#       self,
#       current: WorkflowState,
#       target: WorkflowState,
#       trigger_event: str
#   ) -> WorkflowState:
#     - VALID_TRANSITIONSで許可されていなければStateTransitionError
#     - 成功時はtargetを返す
```

2. `cie/workflow/registry.py` を作成してください：

```python
# WorkflowNodeDef dataclass:
#   node_id: str
#   node_type: Literal["task", "decision", "approval", "evaluation"]
#   agent_id: str
#   depends_on: list[str]
#   outputs: list[str]
#   description: str = ""

# WorkflowDefinition dataclass:
#   workflow_id: str
#   version: str
#   category: str
#   entrypoint: str
#   nodes: dict[str, WorkflowNodeDef]  # node_id -> WorkflowNodeDef
#
#   def get_node(self, node_id: str) -> WorkflowNodeDef
#   def get_next_nodes(self, completed_node_id: str) -> list[WorkflowNodeDef]:
#     - depends_onにcompleted_node_idを含む全ノードを返す

# WorkflowRegistry クラス:
#   _definitions: dict[str, WorkflowDefinition]  # workflow_id -> def
#
#   @classmethod
#   def load_from_yaml(cls, workflow_yaml_path: Path) -> "WorkflowRegistry":
#     - spec/workflow.yaml の workflows セクションを読み込み
#     - 4ワークフロー全てを WorkflowDefinition に変換
#
#   def get(self, workflow_id: str) -> WorkflowDefinition:
#     - 存在しない場合はWorkflowError("WORKFLOW_NOT_FOUND")
#
#   def select_workflow(self, intent_object: dict) -> tuple[str, str, str]:
#     # ADR-0001 Workflow Selection Rules (WS-001〜WS-004) の実装
#     # 戻り値: (workflow_id, rule_id, justification)
#     #
#     # WS-001: intent_object.outcome_type == "survival"
#     #   -> "clinical_analysis_survival", "WS-001", justification
#     # WS-002: intent_object.objective == "systematic_review"
#     #   -> "clinical_analysis_meta", "WS-002", justification
#     # WS-003: intent_object.objective == "prediction_model"
#     #   -> "clinical_analysis_prediction", "WS-003", justification
#     # WS-004: default
#     #   -> "clinical_analysis_standard", "WS-004", justification
#     #
#     # requires_human_clarification=trueの場合はWorkflowError("WORKFLOW_SELECTION_SUSPENDED")
```

3. `tests/unit/test_workflow_registry.py` を作成してください：

```python
# テスト項目:
# - test_load_4_workflows: 4ワークフローが全てロードされること
# - test_select_survival_ws001: outcome_type=survival -> clinical_analysis_survival
# - test_select_meta_ws002: objective=systematic_review -> clinical_analysis_meta
# - test_select_prediction_ws003: objective=prediction_model -> clinical_analysis_prediction
# - test_select_default_ws004: その他 -> clinical_analysis_standard
# - test_requires_clarification_suspended: requires_human_clarification=trueでエラー
# - test_state_valid_transition: DRAFT -> VALIDATED は成功
# - test_state_invalid_transition: COMPLETED -> RUNNING は失敗
# - test_get_next_nodes: depends_onチェーンが正しく解決されること
```

### 制約事項
- select_workflow()はintent_objectにworkflow_idが含まれていても無視すること
  （Plannerが誤ってworkflow_idを設定しても、Orchestratorが上書きする）
- WS-001〜WS-004の優先順位を必ず守ること（WS-001が最優先）
- ワークフロー定義はload_from_yaml()でのみ読み込み、コードにハードコーディングしないこと
```

---

## PROMPT 6-2: Orchestrator（タスクディスパッチループ）

```
CIE PlatformのOrchestratorを実装してください。
workflow選択からDAGの順次実行まで、全体を統括します。

### 読み込むべき仕様ファイル
- agents/orchestrator.yaml (task_dispatch_loop全9ステップ, resilience_routing)
- spec/workflow.yaml (failure_policy)
- decisions/ADR-0001.md (Principle 1〜4)

### 前提
- PROMPT 6-1の WorkflowRegistry, WorkflowStateMachine が存在します
- PROMPT 3-1の CapabilityTokenManager が存在します
- PROMPT 3-2の PolicyEngine, ContextGuard が存在します
- PROMPT 5-1の BaseAgent が存在します
- PROMPT 1-3の AuditService が存在します

### 作成するもの

1. `cie/workflow/orchestrator.py` を作成してください：

```python
# TaskDispatchResult dataclass:
#   node_id: str
#   agent_id: str
#   status: Literal["completed", "failed", "waiting_for_human"]
#   output_payload: dict | None
#   error_code: str | None
#   retry_count: int

# Orchestrator クラス:
#   MAX_RETRY_ATTEMPTS: int = 3  # spec/workflow.yaml
#   RECOVERABLE_ERRORS: set[str] = {
#       "runtime_timeout", "temporary_io_failure", "runtime_busy"
#   }
#
#   __init__(
#       self,
#       workflow_registry: WorkflowRegistry,
#       state_machine: WorkflowStateMachine,
#       token_manager: CapabilityTokenManager,
#       policy_engine: PolicyEngine,
#       context_guard: ContextGuard,
#       audit_service: AuditService,
#       agent_registry: dict[str, BaseAgent]  # agent_id -> Agent instance
#   ) -> None
#
#   async def run_workflow(
#       self,
#       execution_id: str,
#       intent_object: dict
#   ) -> dict:
#     # ADR-0001 workflow selection
#     # 1. intent_objectからworkflow_idを選択（WorkflowRegistry.select_workflow）
#     # 2. WorkflowInstanceをDBに記録（workflow_selection_rule_idも保存）
#     # 3. state_machine.transition(DRAFT -> VALIDATED)
#     # 4. task_dispatch_loop()を実行
#     # 5. 最終状態とresultを返す
#
#   async def _task_dispatch_loop(
#       self,
#       execution_id: str,
#       workflow_def: WorkflowDefinition,
#       initial_payload: dict
#   ) -> dict:
#     # orchestrator.yaml task_dispatch_loop 9ステップを実装:
#     # Step 1: 次の実行可能ノードを解決（depends_onが全て完了しているノード）
#     # Step 2: 依存関係と前提条件を検証
#     # Step 3: ephemeral capability tokenを発行
#     # Step 4: isolated context payloadを構築（context_guard経由）
#     # Step 5: 対象Agentにディスパッチ（agent_registry[agent_id].run()）
#     # Step 6: レスポンスをスキーマ検証
#     # Step 7: capabilityトークンを即時失効
#     # Step 8: 監査ログに記録
#     # Step 9: 状態機械を進める or 分岐処理
#     #
#     # WAITING_FOR_HUMAN ノード（type=approval）:
#     #   → state_machineをWAITING_FOR_HUMANに遷移
#     #   → ループを一時停止（外部からresume_workflow()が呼ばれるまで）
#     #
#     # エラー処理:
#     #   - recoverable: retry（最大3回、指数バックオフ）
#     #   - non-recoverable: IMMEDIATE_ABORT, 全token失効, state=FAILED
#
#   async def resume_workflow(
#       self,
#       execution_id: str,
#       human_decision: dict
#   ) -> None:
#     # WAITING_FOR_HUMANから再開
#     # human_decisionを監査ログに記録
#     # _task_dispatch_loop()を再開
```

2. `tests/integration/test_orchestrator.py` を作成してください：

```python
# 全Agentをモックした統合テスト:
# - test_workflow_selection_ws004_default: 標準ワークフローが選択されること
# - test_workflow_id_not_set_by_planner: Plannerの出力にworkflow_idがあっても無視
# - test_token_revoked_after_node: 各ノード完了後にトークンが失効すること
# - test_recoverable_error_retries: runtime_timeoutで3回リトライすること
# - test_non_recoverable_aborts: schema_validation_failureで即座にFAILED
# - test_human_approval_pauses_loop: approvalノードでWAITING_FOR_HUMANに遷移
# - test_all_nodes_audited: 全ノードが監査ログに記録されること
```

### 制約事項
- step 7（トークン失効）はstep 5（Agent実行）が成功・失敗に関わらず必ず実行すること
  （try/finally パターンで実装）
- Orchestratorが統計分析・メソッド選択を行わないこと（全てAgentに委譲）
- select_workflow()の結果はWorkflow Instance DBレコードのworkflow_selection_rule_idに保存すること
```

---

## PROMPT 6-X: Phase 6 完了処理

```
Phase 6 の全実装（PROMPT 6-1〜6-2）が完了し、テストがすべてパスしたことを
確認してから、以下の手順でブランチを main へ統合してください。

### テスト確認
pytest tests/unit/test_workflow_state.py tests/unit/test_orchestrator.py -v

### コミット
git add -A
git commit -m "feat(phase6): workflow engine & orchestrator — state machine, ADR-0001 compliance"

### main へ merge
git checkout main
git merge --no-ff feature/phase-6-workflow \
  -m "merge: phase-6-workflow into main"

### 次フェーズのブランチを main から作成
git checkout -b feature/phase-7-evaluation
```
