# CIE Platform — Claude Code Implementation Prompts
# Phase 10: Integration Tests & Final Verification
# File: prompts/phase10_integration.md
# Version: 1.0.0

---

## PROMPT 10-1: E2Eワークフロー統合テスト

```
CIE Platformの全レイヤーを通したE2E統合テストを実装してください。
実際のRスクリプトは使用せず、全Agentをモック化してフロー全体を検証します。

### 読み込むべき仕様ファイル
- spec/workflow.yaml (clinical_analysis_standard ワークフロー)
- decisions/ADR-0001.md (Principle 1〜4)
- decisions/ADR-0002.md (Principle 4: 全Skill更新に人間承認必須)
- PROJECT_RULES.md Section 17（Definition of Done）

### 前提
- Phase 1〜9の全実装が完了しています

### 作成するもの

1. `tests/integration/test_e2e_standard_workflow.py` を作成してください：

```python
# テスト用フィクスチャ:
# @pytest.fixture
# async def cie_system(tmp_path):
#   # 以下の全コンポーネントを初期化してdictで返す:
#   # - SQLite in-memory DB (init_db済み)
#   # - AuditService
#   # - PIIFilter
#   # - ContextGuard
#   # - CapabilityTokenManager
#   # - PolicyEngine
#   # - VarNAliasMap / AliasStore
#   # - SchemaRegistry (実際のschemas/から読み込み)
#   # - WorkflowRegistry (実際のspec/workflow.yamlから読み込み)
#   # - WorkflowStateMachine
#   # - Orchestrator（全AgentをMockAgentに差し替え）
#
# MockAgent クラス（BaseAgentのテスト用実装）:
#   - _execute()は事前設定されたfixture responseを返す
#   - 実際のLLM/Rscript呼び出しを一切行わない
#
# テストケース:
#
# test_full_clinical_analysis_standard_workflow():
#   """clinical_analysis_standardワークフローの全ノードが順番に実行されること"""
#   # 1. 入力: "治療群AとBの血圧を比較したい" + mock dataset_metadata
#   # 2. Planner Agent mock: intent_objectを返す（workflow_idなし）
#   # 3. Orchestrator: WS-004でclinical_analysis_standardを選択
#   # 4. 全ノード（intake→...→evaluation）が順番に実行されること
#   # 5. 最終状態がcompleted
#   # 6. 全ノードの監査ログが記録されていること
#   assert final_state == WorkflowState.COMPLETED
#   assert len(audit_events) >= len(workflow_def.nodes)
#
# test_workflow_selection_correctness():
#   """ADR-0001: intent_objectの内容に応じて正しいworkflowが選択されること"""
#   cases = [
#     ({"outcome_type": "survival"}, "clinical_analysis_survival", "WS-001"),
#     ({"objective": "systematic_review"}, "clinical_analysis_meta", "WS-002"),
#     ({"objective": "prediction_model"}, "clinical_analysis_prediction", "WS-003"),
#     ({"objective": "between_group_comparison", "outcome_type": "continuous"},
#      "clinical_analysis_standard", "WS-004"),
#   ]
#   for intent, expected_wf, expected_rule in cases:
#     wf_id, rule_id, _ = workflow_registry.select_workflow(intent)
#     assert wf_id == expected_wf
#     assert rule_id == expected_rule
#
# test_planner_cannot_set_workflow_id():
#   """ADR-0001: Plannerの出力にworkflow_idが含まれていても無視されること"""
#   mock_planner_output = {
#     "intent_object": {"objective": "between_group_comparison", ...},
#     "workflow_id": "clinical_analysis_survival",  # 不正な注入
#   }
#   # Orchestratorがworkflow_idを無視してWS-004を選択すること
#   wf_id, _, _ = workflow_registry.select_workflow(mock_planner_output["intent_object"])
#   assert wf_id == "clinical_analysis_standard"  # 不正なworkflow_idは無視
#
# test_capability_token_revoked_after_each_node():
#   """各ノード完了後にCapability Tokenが失効していること"""
#   # Orchestratorがtask_dispatch_loopを実行後、
#   # 全発行トークンのrevoked=Trueを確認
#   for token in issued_tokens:
#     assert token.revoked == True
#
# test_security_review_pauses_workflow():
#   """security_reviewノードでworkflowがWAITING_FOR_HUMANに遷移すること"""
#   # approval typeのノードに達したとき
#   state = await orchestrator.run_up_to_node(
#     execution_id, "security_review"
#   )
#   assert state == WorkflowState.WAITING_FOR_HUMAN
#
# test_resume_after_human_approval():
#   """人間承認後にworkflowが再開されること"""
#   await orchestrator.resume_workflow(
#     execution_id,
#     human_decision={"action": "approved"}
#   )
#   # 次のノード（runtime_execution）が実行されること
#   assert "runtime_execution" in executed_nodes
#
# test_non_recoverable_error_fails_workflow():
#   """non-recoverableエラーでworkflowがFAILED状態になること"""
#   mock_statistics_agent.raise_on_next = SchemaValidationError(...)
#   final_state = await orchestrator.run_workflow(execution_id, intent_object)
#   assert final_state == WorkflowState.FAILED
#
# test_recoverable_error_retries_3_times():
#   """recoverable error（runtime_timeout）で3回リトライされること"""
#   mock_runtime_agent.fail_times = 2  # 2回失敗、3回目で成功
#   final_state = await orchestrator.run_workflow(execution_id, intent_object)
#   assert mock_runtime_agent.call_count == 3
#   assert final_state == WorkflowState.COMPLETED
#
# test_pii_in_prompt_blocked_before_planner():
#   """PIIを含むプロンプトがPlannerに到達する前にブロックされること"""
#   prompt = "田中花子（患者ID: 12345）の血圧を比較したい"
#   with pytest.raises(PIIDetectedError) as exc:
#     await orchestrator.run_workflow(execution_id, prompt=prompt)
#   assert exc.value.severity == "CRITICAL"
#
# test_raw_data_not_in_any_context():
#   """全ノード実行を通じてraw_data_rowsがcontextに含まれないこと"""
#   # context_guard.sanitize_context_payloadのcallをキャプチャして確認
#   for call_args in context_guard_spy.call_args_list:
#     assert "raw_data_rows" not in call_args[0][0]
#
# test_evaluation_score_written_to_db():
#   """ワークフロー完了後にSkillPerformanceRecordがDBに記録されること"""
#   final_state = await orchestrator.run_workflow(...)
#   records = await db.execute(select(SkillPerformanceRecord)
#              .where(SkillPerformanceRecord.execution_id == execution_id))
#   assert len(records) > 0
```

---

## PROMPT 10-2: セキュリティ境界テスト

```
CIE Platformのセキュリティ境界が正しく機能することを検証する
特化型テストスイートを実装してください。

### 読み込むべき仕様ファイル
- architecture/security-model.md (SP-001〜SP-004)
- spec/permissions.yaml (agent_permission_matrix 全エージェント)
- architecture/security-pii-filter.md (4つの適用タイミング)

### 作成するもの

1. `tests/integration/test_security_boundaries.py` を作成してください：

```python
# 全9エージェントの権限境界テスト:
#
# test_permission_matrix_completeness():
#   """spec/permissions.yamlの全エージェント・全capabilityの
#      AGENT_ALLOWED_SCOPESとの完全一致を検証"""
#   # YAMLを読み込んで AGENT_ALLOWED_SCOPES と比較
#   for agent_id, perms in yaml_permissions.items():
#     for allowed_cap in perms["allow"]:
#       scope = CapabilityScope(allowed_cap)
#       token = token_manager.issue(
#         execution_id="test",
#         agent_id=agent_id,
#         step_id="test",
#         requested_scopes={scope}
#       )
#       assert scope in token.granted_scopes, \
#         f"{agent_id} should have {allowed_cap}"
#
#   for agent_id, perms in yaml_permissions.items():
#     for denied_cap in perms.get("deny", []):
#       if "*" in denied_cap:
#         continue  # ワイルドカードはスキップ
#       scope = CapabilityScope(denied_cap)
#       token = token_manager.issue(..., requested_scopes={scope})
#       assert scope in token.denied_scopes, \
#         f"{agent_id} must NOT have {denied_cap}"
#
# test_statistics_cannot_restore_variables():
#   """Statistics AgentはR_CODE_RESTORE_VARIABLESを取得できないこと"""
#   token = token_manager.issue(
#     agent_id="statistics",
#     requested_scopes={CapabilityScope.R_CODE_RESTORE_VARIABLES}
#   )
#   assert CapabilityScope.R_CODE_RESTORE_VARIABLES in token.denied_scopes
#
# test_planner_cannot_read_raw_data():
#   """Planner Agentはdataset.read_rawを取得できないこと"""
#   token = token_manager.issue(
#     agent_id="planner",
#     requested_scopes={CapabilityScope.DATASET_READ_RAW}
#   )
#   assert CapabilityScope.DATASET_READ_RAW in token.denied_scopes
#
# test_all_pii_timing_points_covered():
#   """PII検出フィルタが4つの適用タイミング全てで呼ばれること"""
#   # architecture/security-pii-filter.md の4タイミング:
#   # 1. Planner入力前（プロンプトPIIチェック）
#   # 2. Context構築前（inject_raw_data_rowsチェック）
#   # 3. Data Quality処理時（全列のLayer1+2）
#   # 4. 最終レポート出力前（原稿テキストのLayer1）
#   pii_filter_spy = spy_on(pii_filter.run_on_prompt)
#   context_guard_spy = spy_on(context_guard.sanitize_context_payload)
#   dq_spy = spy_on(data_quality_agent._execute)
#
#   await orchestrator.run_workflow(execution_id, intent)
#
#   assert pii_filter_spy.call_count >= 1   # タイミング1
#   assert context_guard_spy.call_count >= 1 # タイミング2
#   assert dq_spy.call_count >= 1           # タイミング3
#
# test_token_not_reused_across_nodes():
#   """異なるノードで同一Capability Tokenが再利用されないこと"""
#   tokens_per_node = {}
#   # orchestratorの各step 3（token発行）をキャプチャ
#   for node_id, token in captured_tokens.items():
#     assert token.token_id not in [t.token_id for n,t
#                                    in tokens_per_node.items() if n != node_id]
#
# test_var_n_alias_never_leaked_to_llm():
#   """LLMへのプロンプトにオリジナル列名が含まれないこと"""
#   llm_prompts = []
#   # httpxをモックしてLLMリクエストのbodyをキャプチャ
#   original_col_names = list(alias_store.get(execution_id)._reverse.keys())
#   for prompt in llm_prompts:
#     for col_name in original_col_names:
#       assert col_name not in prompt, \
#         f"Original column name '{col_name}' leaked to LLM"
#
# test_breach_terminates_immediately():
#   """BREACHイベント発生時に全トークンが即時失効しワークフローが停止すること"""
#   # Security AgentがBREACHを報告するシナリオをシミュレート
#   mock_security_agent.trigger_breach = True
#   final_state = await orchestrator.run_workflow(execution_id, intent)
#   assert final_state == WorkflowState.FAILED
#   # 全発行済みトークンがrevokedになっていること
#   for token in all_issued_tokens:
#     assert token.revoked == True
```

---

## PROMPT 10-3: Definition of Done 最終確認スクリプト

```
CIE PlatformのDefinition of Done（PROJECT_RULES.md Section 17）を
自動検証するスクリプトを実装してください。

### 読み込むべき仕様ファイル
- PROJECT_RULES.md Section 17（Definition of Done）
- MANIFEST.yaml（repository.required ファイル一覧）

### 作成するもの

1. `scripts/check_done.py` を作成してください：

```python
#!/usr/bin/env python3
"""
CIE Platform — Definition of Done 自動チェッカー
PROJECT_RULES.md Section 17 の全項目を検証します。

実行: python scripts/check_done.py [--project-root PATH]
"""
import sys
from pathlib import Path

# チェック項目（PROJECT_RULES.md Section 17）:

def check_manifest_files(project_root: Path) -> list[str]:
    """MANIFEST.yamlに定義された全必須ファイルの存在確認"""
    # MANIFEST.yamlを読み込んでrequiredファイルを列挙
    # 存在しないファイルをfailuresリストで返す

def check_schema_validity(project_root: Path) -> list[str]:
    """schemas/配下の全JSONスキーマが有効なJSON-Schemaであること"""
    # jsonschema.Draft202012Validatorでメタスキーマに対して検証

def check_adr_for_architecture_changes(project_root: Path) -> list[str]:
    """decisions/にADR-0001とADR-0002が存在すること"""

def check_skill_namespace_structure(project_root: Path) -> list[str]:
    """skills/core/, meta/, user/ の構造がMANIFEST定義と一致すること"""
    # 各core Skillにversions/ディレクトリが存在すること
    # user/にREGISTRY.yamlが存在すること
    # meta/に3つのSkillが存在すること

def check_no_workflow_id_in_planner(project_root: Path) -> list[str]:
    """agents/planner.yamlに workflow_id_assignment が strictly_forbidden に含まれること"""
    # ADR-0001の実装確認

def check_skill_lifecycle_spec_exists(project_root: Path) -> list[str]:
    """spec/skill-lifecycle.md が存在すること（ADR-0002）"""

def check_permissions_yaml_skill_lifecycle(project_root: Path) -> list[str]:
    """spec/permissions.yamlにskill_lifecycleエージェントが定義されていること"""

def run_checks(project_root: Path) -> dict[str, list[str]]:
    """全チェックを実行してカテゴリ別の結果を返す"""
    results = {}
    checks = [
        ("必須ファイルの存在", check_manifest_files),
        ("スキーマ有効性", check_schema_validity),
        ("ADR存在確認", check_adr_for_architecture_changes),
        ("Skill名前空間構造", check_skill_namespace_structure),
        ("ADR-0001実装確認", check_no_workflow_id_in_planner),
        ("ADR-0002実装確認(spec)", check_skill_lifecycle_spec_exists),
        ("ADR-0002実装確認(permissions)", check_permissions_yaml_skill_lifecycle),
    ]
    for name, fn in checks:
        failures = fn(project_root)
        results[name] = failures
    return results

def main():
    project_root = Path(__file__).parent.parent
    results = run_checks(project_root)

    total_failures = 0
    for category, failures in results.items():
        if failures:
            print(f"\n❌ {category}")
            for f in failures:
                print(f"   - {f}")
            total_failures += len(failures)
        else:
            print(f"✅ {category}")

    print(f"\n{'='*50}")
    if total_failures == 0:
        print("✅ Definition of Done: 全項目クリア")
        sys.exit(0)
    else:
        print(f"❌ Definition of Done: {total_failures}件の問題が残っています")
        sys.exit(1)

if __name__ == "__main__":
    main()
```

2. `scripts/run_all_tests.sh` を作成してください：

```bash
#!/bin/bash
# CIE Platform — 全テスト実行スクリプト
# 使用法: ./scripts/run_all_tests.sh

set -e

echo "================================================"
echo "CIE Platform — Full Test Suite"
echo "================================================"

echo ""
echo "[1/4] Definition of Done チェック"
python scripts/check_done.py

echo ""
echo "[2/4] Unit Tests"
pytest tests/unit/ -v --tb=short \
  --cov=cie \
  --cov-report=term-missing \
  --cov-fail-under=80

echo ""
echo "[3/4] Integration Tests"
pytest tests/integration/ -v --tb=short

echo ""
echo "[4/4] Schema Validation"
python -c "
from pathlib import Path
from cie.schemas.validator import load_registry
registry = load_registry()
print(f'✅ {len(registry._schemas)} schemas loaded and valid')
"

echo ""
echo "================================================"
echo "✅ 全テスト完了"
echo "================================================"
```

3. `tests/integration/test_definition_of_done.py` を作成してください：

```python
# scripts/check_done.pyのcheck関数をpytestから呼ぶラッパー:
# - test_manifest_files_exist: 全必須ファイルが存在すること
# - test_schemas_valid: 全スキーマが有効であること
# - test_adr_exists: ADR-0001とADR-0002が存在すること
# - test_skill_namespace_correct: 3名前空間の構造が正しいこと
# - test_no_workflow_id_in_planner: planner.yamlにworkflow_id_assignment禁止が明記
# - test_skill_lifecycle_spec: spec/skill-lifecycle.mdが存在すること
```

### 制約事項
- check_done.pyはCIシステムでも実行できるようにすること（exit codeで結果を返す）
- 全チェックは独立して実行可能なこと（1つのチェック失敗が他に影響しない）
- チェック結果は人間が読めるメッセージで出力すること（エラーコードだけでなく）
```
