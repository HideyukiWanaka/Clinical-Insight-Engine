# CIE Platform 実装ガイド
# Claude Codeによる開発における注意点とポイント集
# Version: 1.0.0
# 対象読者: CIE Platform 実装担当者

---

## 本資料の目的

本資料は、CIE PlatformをClaude Codeで実装する際に
陥りやすい問題・見落としがちなポイント・効率的な進め方を
体系的にまとめたものです。

`prompts/` 配下のプロンプト集（Phase 1〜10）と併用してください。

---

## 第1章 Claude Codeとの協働の基本原則

### 1.1 セッション開始時の必須手順

Claude Codeはセッションをまたぐと仕様書の内容を忘れます。
**毎回のセッション開始時に以下を実行してください。**

```
今日はCIE Platformの実装を続けます。
作業前に以下を読み込んでください：

- MANIFEST.yaml
- PROJECT_RULES.md
- decisions/ADR-0001.md
- decisions/ADR-0002.md
- [今日実装するPhaseのプロンプトファイル]

読み込み完了後、今日の実装予定を確認してから作業を開始してください。
```

長いセッションでは**1〜2時間ごとに**
「仕様書の内容を確認して現在の実装が整合しているか見てください」
と促すことで、仕様からの逸脱を防げます。

---

### 1.2 プロンプトの使い方

プロンプトファイル内の各プロンプトは、
```` ``` ```` で囲まれたコードブロック内のテキストを
**そのままClaude Codeに貼り付けてください。**

前後の説明文（ファイル名・Version行など）は不要です。

**効果的な追加指示の例:**

```
上記の実装を完了したら、以下を確認してください：
1. 型アノテーションが全関数についているか
2. docstringがGoogle形式で記述されているか
3. テストが全て通過するか（pytest tests/unit/test_XXX.py -v）
確認完了後、次のプロンプトに進む準備ができたと教えてください。
```

---

### 1.3 仕様と実装が食い違ったときの対処

Claude Codeが仕様を誤解して実装した場合、
**仕様書のファイルパスを明示して再指示**するのが最速です。

```
# 悪い例（抽象的すぎる）
「この実装は間違っています。直してください」

# 良い例（具体的・ファイルパス付き）
「decisions/ADR-0001.md の Principle 2 を読み直してください。
 Planner Agentの_execute()メソッドのoutput_payloadに
 'workflow_id'キーが含まれています。
 これはADR-0001違反なので削除してください。」
```

---

## 第2章 アーキテクチャ上の最重要制約

実装中に最も見落とされやすい、かつ修正コストが高い制約です。
各Phaseの完了前に必ずチェックしてください。

---

### 2.1 ADR-0001: PlannerはworkflowIdを設定しない

**違反パターン（よくある間違い）:**

```python
# ❌ Planner Agentの_execute()内でworkflow_idを設定してしまう例
output_payload = {
    "intent_object": intent_obj,
    "workflow_id": "clinical_analysis_standard",  # ← ADR-0001違反
    "confidence_score": 0.91
}
```

**正しい実装:**

```python
# ✅ Plannerはintent_objectのみを返す
output_payload = {
    "intent_object": intent_obj,
    "confidence_score": 0.91,
    "requires_human_clarification": False
    # workflow_idは含めない
}

# workflow_idはOrchestratorがWS-001〜WS-004で決定する
# cie/workflow/registry.py の select_workflow() が担う
```

**確認コマンド:**

```bash
# Plannerの出力にworkflow_idが含まれていないことを確認
grep -r "workflow_id" cie/agents/planner.py
# → output_payload への代入がゼロであること
```

---

### 2.2 ADR-0002: 全Skill更新に人間承認が必須

**違反パターン:**

```python
# ❌ human_review_requiredをFalseに設定してはならない
proposal = SkillImprovementProposal(
    ...
    human_review_required=False  # ← ADR-0002 Principle 4 違反
)

# ❌ 提案を承認なしで直接適用してはならない
skill_path.write_text(new_skill_content)  # ← 承認フロー未経由
```

**正しい実装:**

```python
# ✅ 提案は常にPENDING_HUMAN_REVIEWから始まる
proposal = SkillImprovementProposal(
    human_review_required=True,   # 変更不可
    status=ProposalStatus.PENDING_HUMAN_REVIEW
)

# ✅ ファイル書き込みはapply_approved_proposal()経由のみ
# かつCapabilityScope.SKILL_UPDATE_COREの検証後のみ
```

---

### 2.3 inject_raw_data_rows は常にFalse

**agent.schema.jsonの`const: false`を実行時に強制します。**
以下の2か所で必ず検証してください。

```python
# cie/security/context_guard.py — sanitize_context_payload()内
async def sanitize_context_payload(self, payload: dict, ...) -> dict:
    # ① raw_data_rowsキーの存在チェック（絶対に通過させない）
    if "raw_data_rows" in payload:
        raise SecurityViolationError(
            error_code="INJECT_RAW_DATA_ROWS_ATTEMPTED"
        )
    ...

# cie/agents/data_quality.py — _execute()の入力チェック
async def _execute(self, agent_input: AgentInput) -> AgentOutput:
    # ② metadata_typeがproxy_metadataかvalidated_structuralのみ許可
    meta_type = agent_input.payload.get("metadata_type")
    if meta_type not in ("proxy_metadata", "validated_structural"):
        raise AgentError(error_code="RAW_DATA_ACCESS_ATTEMPTED")
```

---

### 2.4 Capability Tokenはtry/finallyで必ず失効させる

**Token失効はAgent実行の成否に関わらず必ず実行しなければなりません。**

```python
# cie/workflow/orchestrator.py — _task_dispatch_loop()内
async def _dispatch_node(self, node: WorkflowNodeDef, ...) -> TaskDispatchResult:
    token = self.token_manager.issue(
        execution_id=execution_id,
        agent_id=node.agent_id,
        step_id=node.node_id,
        requested_scopes=agent.required_scopes
    )
    try:
        result = await agent.run(AgentInput(
            capability_token=token, ...
        ))
        return result
    except Exception as e:
        raise
    finally:
        # ✅ 成功・失敗・例外に関わらず必ず実行
        token = self.token_manager.revoke(token)
        await self.audit_service.write(AuditEvent(
            action="token_revoked",
            ...
        ))
```

---

### 2.5 PII検出は4タイミング全てで適用する

以下の4か所全てにPIIフィルタが存在することを確認してください。

```python
# タイミング1: Planner Agent入力前（context_guard.py）
await context_guard.sanitize_context_payload(
    {"user_natural_language_prompt": prompt, ...}, ...
)

# タイミング2: 全AgentのLLMプロンプト構築前（orchestrator.py Step 4）
isolated_context = await context_guard.sanitize_context_payload(
    node_inputs, execution_id, agent_id
)

# タイミング3: Data Quality Agent処理時（data_quality.py）
findings = self.pii_filter.run(
    col_name=col.var_n,
    col_meta=col,
    row_count=dataset_metadata.row_count
)

# タイミング4: 最終レポート出力前（reporting agentまたはorchestrator）
sanitized_text = await context_guard.sanitize_stdout(
    manuscript_content, execution_id
)
```

---

## 第3章 Phase別の注意点

### Phase 1 — プロジェクト基盤

**注意点:**

`database.py`の`init_db()`は**冪等**に実装してください。
後のPhaseでテーブルを追加する際（Phase 8でSkillImprovementProposalを追加）に
既存テーブルが壊れないようにするためです。

```python
# ✅ CREATE TABLE IF NOT EXISTS を使う
async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # SQLAlchemy の create_all は IF NOT EXISTS と等価
```

**Claude Codeへの追加指示:**

```
database.pyのinit_db()は何度実行しても
既存データを破壊しない冪等な実装にしてください。
後のPhaseでテーブルを追加する可能性があります。
```

---

### Phase 2 — スキーマ・PII検出

**注意点①: カテゴリ値は必ず`[REDACTED]`**

```python
# cie/security/pii_detector.py — detect_category_labels()内
# ✅ 値は絶対に記録しない
findings.append(PIIFinding(
    matched_text="[REDACTED]",  # ← label変数の値を入れない
    ...
))
```

**注意点②: Layer 2はrow_count=0を安全に処理する**

```python
# cie/security/pii_detector_layer2.py
def detect(self, col_meta: ColumnMetadata, row_count: int) -> list[PIIFinding]:
    if row_count == 0:
        return []  # ZeroDivisionErrorを防ぐ
    if col_meta.summary_stats is None:
        # シグナル1/3/4をスキップ（シグナル2=date型のみ適用可）
        ...
```

---

### Phase 3 — セキュリティ

**注意点: AGENT_ALLOWED_SCOPESはspec/permissions.yamlと完全一致させる**

実装後に以下のコマンドで照合してください。

```bash
# spec/permissions.yaml のallowリストを抽出して確認
python3 -c "
import yaml
perms = yaml.safe_load(open('spec/permissions.yaml'))
for agent, p in perms['agent_permission_matrix'].items():
    print(f'{agent}: {p.get(\"allow\", [])}')
"
```

これをPythonコード内の`AGENT_ALLOWED_SCOPES`と手動で照合します。
特に`security`エージェントの`r_code.restore_variables`と
`statistics`エージェントの`r_code.restore_variables`が
**逆に設定されないよう**注意してください。

```python
# ✅ 正しい設定
AGENT_ALLOWED_SCOPES = {
    "security": {
        CapabilityScope.R_CODE_RESTORE_VARIABLES,  # securityのみ許可
        CapabilityScope.HUMAN_REQUEST_APPROVAL,
        CapabilityScope.AUDIT_WRITE_ENTRY,
    },
    "statistics": {
        CapabilityScope.DATASET_READ_VALIDATED,
        CapabilityScope.R_CODE_GENERATE_TEMPLATE,
        CapabilityScope.AUDIT_WRITE_ENTRY,
        # R_CODE_RESTORE_VARIABLESは含めない
    },
}
```

---

### Phase 4〜6 — Runtime・Agents・Orchestrator

**注意点①: Rscriptのサブプロセスはshell=False必須**

```python
# ✅ 正しい実装
proc = await asyncio.create_subprocess_exec(
    "Rscript", "--vanilla", "--slave", str(script_path),
    env={"CIE_EXECUTION_ID": execution_id,
         "WORKSPACE_DIR": str(workspace_dir),
         "OUTPUT_DIR": str(output_dir)},
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE
    # shell=False がデフォルト — 明示的にshell=Trueにしないこと
)

# ❌ 禁止: shell=True
proc = await asyncio.create_subprocess_shell(...)
```

**注意点②: WorkflowRegistry.select_workflow()はPlannerの出力にworkflow_idがあっても無視する**

```python
def select_workflow(self, intent_object: dict) -> tuple[str, str, str]:
    # intent_objectに誤ってworkflow_idが含まれていても参照しない
    # WS-001〜WS-004のルールのみで決定する
    outcome_type = intent_object.get("outcome_type", "")
    objective    = intent_object.get("objective", "")
    requires_clarification = intent_object.get("requires_human_clarification", False)

    if requires_clarification:
        raise WorkflowError("WORKFLOW_SELECTION_SUSPENDED")
    if outcome_type == "survival":
        return "clinical_analysis_survival", "WS-001", f"outcome_type=survival → WS-001"
    # ... WS-002, WS-003
    return "clinical_analysis_standard", "WS-004", "default → WS-004"
```

**注意点③: 実際のR実行テストにはフラグを設ける**

```python
# tests/conftest.py に追加
import shutil, pytest

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "requires_r: marks tests that need Rscript installed"
    )

@pytest.fixture(scope="session")
def r_available():
    return shutil.which("Rscript") is not None

# R依存テストには @pytest.mark.requires_r を付ける
# CI環境ではスキップ可能にする
```

---

### Phase 7 — Evaluation

**注意点: 重みの合計が100%になること**

```python
# ✅ 重み付き平均の計算
# correctness:40 + statistical:35 + security:15 + usability:10 = 100

evaluators = [
    CorrectnessEvaluator(),   # weight_pct = 40
    StatisticalEvaluator(),   # weight_pct = 35
    SecurityEvaluator(),      # weight_pct = 15
    UsabilityEvaluator(),     # weight_pct = 10
]

# 合計チェック（実装後に確認）
total_weight = sum(e.weight_pct for e in evaluators)
assert total_weight == 100, f"Weights must sum to 100, got {total_weight}"
```

**また、CC-006（CI方向チェック）はmethod_usedで分岐させること。**

```python
# cie/evaluation/correctness.py — CC-006チェック
def _check_cc006(self, result: dict) -> CheckResult:
    p_value   = result["primary_result"]["p_value"]
    method    = result.get("method_used", "")
    ci_lower  = result["primary_result"]["ci_lower"]
    ci_upper  = result["primary_result"]["ci_upper"]

    if p_value >= 0.05:
        return CheckResult(check_id="CC-006", passed=True, ...)

    if "logistic" in method or "glm" in method:
        # ロジスティック回帰: OR の CI が 1.0 を含まないこと
        ci_valid = ci_lower > 1.0 or ci_upper < 1.0
    else:
        # 連続アウトカム: CI が 0 を含まないこと
        ci_valid = ci_lower > 0 or ci_upper < 0

    return CheckResult(
        check_id="CC-006",
        passed=ci_valid,
        severity="critical",
        ...
    )
```

---

### Phase 8 — Skills

**注意点①: ファイル更新前に必ずバックアップを作成する**

```python
# cie/skills/lifecycle.py — apply_approved_proposal()内
async def apply_approved_proposal(self, proposal_id: str, ...) -> None:
    skill_path = resolve_skill_path(target_skill_id)
    backup_path = skill_path.parent / "versions" / current_version / "SKILL.md"

    # Step 1: バックアップ作成
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_content = skill_path.read_text(encoding="utf-8")
    backup_path.write_text(backup_content, encoding="utf-8")

    try:
        # Step 2: 新バージョンを書き込み
        skill_path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        # Step 3: 失敗したらロールバック
        skill_path.write_text(backup_content, encoding="utf-8")
        raise SkillError(f"SKILL_UPDATE_FAILED: {e}") from e
```

**注意点②: User SkillのMETADATA.yamlの`approved_by`はLifecycleService外で設定しない**

```python
# ❌ scaffolder.pyで勝手にapprovedにしてはならない
metadata = {
    "approved_by": "human",  # ← scaffolderが設定してはならない
    "approved_at": "2025-06-27",
    "status": "active"
}

# ✅ scaffolderはdraftのみ
metadata = {
    "approved_by": None,   # LifecycleService.register_user_skill()が設定する
    "approved_at": None,
    "status": "draft"
}
```

---

### Phase 9 — UI

**注意点①: ビジネスロジックをUIコンポーネントに含めない**

```python
# ❌ 悪い例: UIコンポーネント内でPlannerを呼ぶ
def render_intent_entry():
    prompt = st.text_area("研究目的")
    if st.button("解析"):
        intent = planner_agent.run(prompt)  # ← UIコンポーネント内でAgent呼び出し

# ✅ 正しい例: コールバックで呼び出し元に委譲
def render_intent_entry(on_submit: Callable) -> None:
    prompt = st.text_area("研究目的")
    if st.button("解析"):
        on_submit(prompt)  # ← app.pyのon_submitハンドラに委譲

# app.py側でAgentを呼ぶ
def handle_submit(prompt: str) -> None:
    result = await orchestrator.run_workflow(execution_id, prompt)
    st.session_state["intent_result"] = result
```

**注意点②: st.session_stateの書き込みはapp.pyに集約する**

各コンポーネント関数は`return`でUIイベントを通知し、
`st.session_state`への書き込みは`app.py`で行います。
これによりコンポーネントが独立してテスト可能になります。

**注意点③: モックデータで早期にUI確認ができる**

バックエンドが未完成でもUIの使い勝手を確認するために、
以下のように`dev_mode`フラグを最初から設けることを推奨します。

```python
# app.py
DEV_MODE = os.getenv("CIE_DEV_MODE", "false").lower() == "true"

if DEV_MODE:
    # モックデータでUIを確認
    st.session_state["workflow_state"] = "waiting_for_human"
    st.session_state["quality_report"] = MOCK_QUALITY_REPORT
```

---

### Phase 10 — 統合テスト

**注意点: セキュリティ境界テストはspec/permissions.yamlとの自動照合が最も信頼できる**

```python
# tests/integration/test_security_boundaries.py
def test_permission_matrix_completeness():
    """実装がspec/permissions.yamlと完全一致することを自動検証"""
    import yaml
    spec = yaml.safe_load(open("spec/permissions.yaml"))
    matrix = spec["agent_permission_matrix"]

    for agent_id, perms in matrix.items():
        for cap_str in perms.get("allow", []):
            if "*" in cap_str:
                continue
            scope = CapabilityScope(cap_str)
            token = token_manager.issue(
                execution_id="test",
                agent_id=agent_id,
                step_id="test",
                requested_scopes={scope}
            )
            assert scope in token.granted_scopes, (
                f"BUG: {agent_id} should have {cap_str} "
                f"per spec/permissions.yaml but it was denied"
            )
```

---

## 第4章 データベース管理の注意点

### 4.1 テーブル追加時の対応（Phase 8）

Phase 8でSkillImprovementProposalテーブルを追加する際、
以下の手順で既存DBに影響を与えずに追加してください。

```python
# cie/core/database.py に追記するだけでOK
# SQLAlchemyのcreate_all()はIF NOT EXISTSで動作するため
# 既存テーブルには影響しない

class SkillImprovementProposal(Base):
    __tablename__ = "skill_improvement_proposals"
    id = Column(UUID, primary_key=True, default=uuid4)
    # ... 他のカラム

# init_db()の変更は不要
# Base.metadata.create_all(conn) が新テーブルも作成する
```

### 4.2 AuditLogテーブルはUPDATE/DELETE禁止

```python
# ✅ AuditLogはINSERTのみ
# cie/core/audit.py

async def write(self, event: AuditEvent) -> None:
    async with self.session_factory() as session:
        log_entry = AuditLog(...)
        session.add(log_entry)
        await session.commit()
        # UPDATE/DELETEは実装しない
        # immutabilityはアーキテクチャレベルで保証する
```

---

## 第5章 テスト戦略

### 5.1 テストの分類と実行方針

| 種別 | 場所 | 実行条件 | 目標カバレッジ |
|------|------|---------|--------------|
| ユニットテスト | `tests/unit/` | 常時（CI/ローカル） | 80%以上 |
| 統合テスト | `tests/integration/` | Phase完了時 | 主要フロー全件 |
| Rscript実行テスト | `tests/unit/` (marks) | Rインストール済み環境のみ | — |

### 5.2 テスト実行コマンド

```bash
# 全ユニットテスト（カバレッジ付き）
pytest tests/unit/ -v --cov=cie --cov-report=term-missing

# 統合テストのみ
pytest tests/integration/ -v

# Rが必要なテストをスキップ
pytest tests/ -v -m "not requires_r"

# Definition of Done確認
python scripts/check_done.py

# 全テスト一括実行
./scripts/run_all_tests.sh
```

### 5.3 各Phaseのテスト完了基準

| Phase | 完了基準 |
|-------|---------|
| 1 | `test_database.py`, `test_audit.py` 全件パス |
| 2 | `test_schema_validator.py`, `test_pii_layer1.py`, `test_pii_layer2.py` 全件パス |
| 3 | `test_capability_token.py`, `test_policy_engine.py`, `test_var_alias.py` 全件パス |
| 4-6 | `test_r_executor.py`, `test_base_agent.py`, `test_planner.py`, `test_workflow_registry.py`, `test_orchestrator.py` 全件パス |
| 7 | `test_correctness_evaluator.py`, `test_statistical_evaluator.py`, `test_security_evaluator.py`, `test_evaluator_service.py` 全件パス |
| 8 | `test_skill_loader.py`, `test_skill_lifecycle.py`, `test_scaffolder.py` 全件パス |
| 9 | `test_ui_components.py` 全件パス |
| 10 | `test_e2e_standard_workflow.py`, `test_security_boundaries.py`, `test_definition_of_done.py` 全件パス |

---

## 第6章 よくあるエラーと対処法

### 6.1 スキーマ検証エラー

```
SchemaValidationError: 'workflow_id' is not valid under any of the given schemas
```

**原因:** Planner AgentがADR-0001に違反してworkflow_idを出力している。

**対処:**
```
decisions/ADR-0001.md のPrinciple 2を読み直してください。
cie/agents/planner.pyの_execute()メソッドの
output_payloadからworkflow_idを削除してください。
```

---

### 6.2 PermissionDeniedError

```
PermissionDeniedError: statistics agent cannot access r_code.restore_variables
```

**原因:** StatisticsがR_CODE_RESTORE_VARIABLESを要求している。

**対処:**
```
spec/permissions.yaml のstatistics agentのallow/denyを確認してください。
r_code.restore_variablesはsecurity agentのみ許可されます。
cie/security/capability_token.py のAGENT_ALLOWED_SCOPESを修正してください。
```

---

### 6.3 ZeroDivisionError（PII Layer 2）

```
ZeroDivisionError: division by zero
```

**原因:** `row_count=0`のデータセットでuniqueness_ratioを計算している。

**対処:**
```python
# cie/security/pii_detector_layer2.py
def detect(self, col_meta, row_count: int):
    if row_count == 0:
        return []  # この行を先頭に追加
```

---

### 6.4 Token期限切れエラー

```
SecurityViolationError: Token has expired
```

**原因:** 300秒を超えるRスクリプト実行（spec/runtime.yamlの上限）。

**対処:** まずRスクリプトのロジックを確認してタイムアウトの原因を特定してください。
正当な理由がある場合は`spec/runtime.yaml`の`max_execution_time_seconds`を
変更してADRに記録してください（アーキテクチャ変更のため）。

---

### 6.5 YAMLパースエラー（MANIFEST.yaml）

```
yaml.parser.ParserError: expected <block end>
```

**原因:** `subdirectories`などでリスト形式とマッピング形式が混在している。

**対処:**
```bash
# YAMLの検証コマンド
python3 -c "import yaml; yaml.safe_load(open('MANIFEST.yaml')); print('OK')"
```
エラー行を特定して、リスト（`- key:`）かマッピング（`key:`）かを統一してください。

---

## 第7章 完了チェックリスト

実装完了の判定基準（PROJECT_RULES.md Section 17準拠）

### Phase完了前チェック

```
□ 実装対象のプロンプトの「制約事項」を全項目確認した
□ pytest tests/unit/ が全件パスする
□ 型アノテーションが全関数についている（ruff check で確認）
□ docstringがGoogle形式で記述されている
□ セキュリティ関連の制約が守られている（第2章のチェックリスト）
□ 次のPhaseが受け取るインターフェースを確認した
```

### 全Phase完了後チェック

```
□ python scripts/check_done.py が全項目パスする
□ ./scripts/run_all_tests.sh が正常終了する
□ E2Eテスト（test_e2e_standard_workflow.py）が全件パスする
□ セキュリティ境界テスト（test_security_boundaries.py）が全件パスする
□ spec/permissions.yamlとAGENT_ALLOWED_SCOPESが完全一致している
□ PII検出の4タイミングが全て実装されている
□ 全Skill更新フローにhuman_review_required=Trueが設定されている
□ ADR-0001: Plannerの出力にworkflow_idが含まれていない
□ ADR-0002: SkillファイルへのWriteはLifecycleServiceのみ
```
