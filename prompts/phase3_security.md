# CIE Platform — Claude Code Implementation Prompts
# Phase 3: Security & Permission System
# File: prompts/phase3_security.md
# Version: 1.0.0

---

## PROMPT 3-1: ケイパビリティトークン

```
CIE Platformの Ephemeral Capability Token (CCT) システムを実装してください。
すべてのAgent実行はこのトークンで権限が制御されます。

### 読み込むべき仕様ファイル
- spec/permissions.yaml (token_lifecycle, capabilities セクション)
- agents/security.yaml (SC-001〜SC-007)
- agents/orchestrator.yaml (task_dispatch_loop step 3, 7)

### 前提
- PROMPT 1-3の AuditService が存在します
- PROMPT 1-1の PermissionDeniedError, SecurityViolationError が存在します

### 作成するもの

1. `cie/security/capability_token.py` を作成してください：

```python
# CapabilityScope Enum（spec/permissions.yamlのcapabilities id一覧）:
#   DATASET_READ_RAW = "dataset.read_raw"
#   DATASET_PROXY_METADATA = "dataset.proxy_metadata"
#   DATASET_READ_VALIDATED = "dataset.read_validated"
#   WORKFLOW_STATE_READ = "workflow.state_read"
#   WORKFLOW_STATE_WRITE = "workflow.state_write"
#   R_CODE_GENERATE_TEMPLATE = "r_code.generate_template"
#   R_CODE_RESTORE_VARIABLES = "r_code.restore_variables"
#   RUNTIME_INVOKE_EXECUTION = "runtime.invoke_execution"
#   REPORT_COMPILE_MANUSCRIPT = "report.compile_manuscript"
#   REPORT_EXPORT_EXTERNAL = "report.export_external"
#   HUMAN_REQUEST_APPROVAL = "human.request_approval"
#   AUDIT_WRITE_ENTRY = "audit.write_entry"
#   SKILL_UPDATE_CORE = "skill.update_core"
#   SKILL_REGISTER_USER = "skill.register_user"
#   SKILL_READ_PERFORMANCE = "skill.read_performance_records"

# CapabilityToken dataclass:
#   token_id: str  # UUID
#   bound_execution_id: str
#   bound_agent_id: str
#   bound_step_id: str
#   granted_scopes: frozenset[CapabilityScope]
#   denied_scopes: frozenset[CapabilityScope]
#   issued_at: datetime  # UTC
#   expires_at: datetime  # issued_at + 300秒
#   revoked: bool = False
#   revoked_at: datetime | None = None
#
#   def is_valid(self) -> bool:
#     - revokedがFalseかつexpires_atが未来であること
#
#   def has_scope(self, scope: CapabilityScope) -> bool:
#     - is_valid()がTrueかつscope in granted_scopesであること
#
#   def require_scope(self, scope: CapabilityScope) -> None:
#     - has_scope()がFalseならPermissionDeniedError送出
#     - error_codeは"PERMISSION_DENIED"
#     - トークンが期限切れ/失効済みの場合は別途SecurityViolationError

# CapabilityTokenManager クラス:
#   AGENT_ALLOWED_SCOPES: dict[str, set[CapabilityScope]]
#     # spec/permissions.yaml の agent_permission_matrix を完全に実装
#     # 9 agents: orchestrator, planner, data_quality, statistics,
#     #           visualization, reporting, reviewer, security, runtime
#     # ※ skill_lifecycle は別途 PROMPT 3-3 で追加
#
#   def issue(
#       self,
#       execution_id: str,
#       agent_id: str,
#       step_id: str,
#       requested_scopes: set[CapabilityScope]
#   ) -> CapabilityToken:
#     - agent_idがAGENT_ALLOWED_SCOPESに存在しない場合はSecurityViolationError
#     - requested_scopesのうちAGENT_ALLOWED_SCOPESで許可されたもののみ granted_scopes に含める
#     - 許可されなかったものは denied_scopes に含める
#     - token_id=uuid4(), TTL=300秒で生成して返す
#
#   def revoke(self, token: CapabilityToken) -> CapabilityToken:
#     - token.revoked=True, token.revoked_at=now(UTC) としたコピーを返す
#     - 元のtokenは変更しない（immutable設計）
#
#   def validate_binding(
#       self,
#       token: CapabilityToken,
#       execution_id: str,
#       agent_id: str,
#       step_id: str
#   ) -> None:
#     - token.bound_execution_id != execution_id でSecurityViolationError
#     - token.bound_agent_id != agent_id でSecurityViolationError
#     - token.bound_step_id != step_id でSecurityViolationError
#     - is_valid()がFalseでSecurityViolationError
```

2. `tests/unit/test_capability_token.py` を作成してください：

```python
# テスト項目:
# - test_issue_valid_token: 正常なトークン発行
# - test_scope_filtering: agentの許可範囲外のscopeがdenied_scopesに入ること
# - test_has_scope_valid: 付与されたscopeはhas_scope()=True
# - test_has_scope_denied: 付与されていないscopeはhas_scope()=False
# - test_token_expires: expires_at過去のトークンはis_valid()=False
# - test_revoke_immutable: revoke()が元tokenを変更しないこと
# - test_revoked_token_invalid: revoke済みトークンはis_valid()=False
# - test_unknown_agent_rejected: 未知のagent_idでSecurityViolationError
# - test_binding_validation: execution_id不一致でSecurityViolationError
# - test_planner_cannot_get_read_raw: plannerにdataset.read_rawを要求するとdenied
# - test_security_agent_gets_restore_variables: securityはr_code.restore_variablesが許可
# - test_statistics_cannot_restore_variables: statisticsはr_code.restore_variablesが拒否
```

### 制約事項
- AGENT_ALLOWED_SCOPESはspec/permissions.yamlのagent_permission_matrixと
  完全に一致させること（手を抜かず全9エージェント分実装）
- トークンはdataclassでimmutableに設計すること（frozen=True推奨）
- TTLは300秒固定（spec/permissions.yaml: token_ttl_expired: 300 seconds）
```

---

## PROMPT 3-2: パーミッション強制実行エンジン

```
CIE Platformのポリシーエンジンを実装してください。
全てのAgent実行前にトークンとスコープを検証します。

### 読み込むべき仕様ファイル
- agents/security.yaml (SC-001〜SC-007, security_event_classification)
- spec/permissions.yaml (policy_enforcement)
- architecture/security-model.md (SP-001〜SP-004)

### 前提
- PROMPT 3-1の CapabilityToken, CapabilityTokenManager が存在します
- PROMPT 1-3の AuditService が存在します

### 作成するもの

1. `cie/security/policy_engine.py` を作成してください：

```python
# PolicyDecision dataclass:
#   allowed: bool
#   granted_scopes: frozenset[CapabilityScope]
#   denied_scopes: frozenset[CapabilityScope]
#   violations: list[str]  # 違反の説明

# PolicyEngine クラス:
#   __init__(
#       self,
#       token_manager: CapabilityTokenManager,
#       audit_service: AuditService
#   ) -> None
#
#   async def enforce(
#       self,
#       token: CapabilityToken,
#       required_scope: CapabilityScope,
#       execution_id: str,
#       agent_id: str,
#       step_id: str
#   ) -> None:
#     - validate_binding() を呼ぶ → 失敗でSECURITY_BREACH_ATTEMPT監査ログ記録後に再送出
#     - token.require_scope(required_scope) → 失敗でPERMISSION_DENIED監査ログ記録後に再送出
#     - 成功時もaudit_service.write()でINFO levelで記録
#
#   async def enforce_multi(
#       self,
#       token: CapabilityToken,
#       required_scopes: list[CapabilityScope],
#       execution_id: str,
#       agent_id: str,
#       step_id: str
#   ) -> None:
#     - required_scopesの全スコープに対してenforce()を実行
#     - 最初の失敗で即時停止
#
#   async def handle_breach(
#       self,
#       execution_id: str,
#       agent_id: str,
#       breach_code: str,
#       details: dict
#   ) -> None:
#     - audit_service.write_security_event() でBREACH severity記録
#     - SecurityViolationError("SECURITY_BREACH_DETECTED")を送出
#     # 呼び出し元（Orchestrator）が全トークン失効を行う
```

2. `cie/security/context_guard.py` を作成してください：

```python
# ContextGuard クラス（LLMプロンプト構築前のガード）:
#   __init__(
#       self,
#       pii_filter: PIIFilter,
#       audit_service: AuditService
#   ) -> None
#
#   async def sanitize_context_payload(
#       self,
#       payload: dict,
#       execution_id: str,
#       agent_id: str
#   ) -> dict:
#     - payloadのすべてのstr値に対して pii_filter.run_on_prompt() を実行
#     - CRITICALが検出された場合: PIIDetectedError送出 + audit WARNING記録
#     - payloadに "raw_data_rows" キーが存在する場合:
#       SecurityViolationError("INJECT_RAW_DATA_ROWS_ATTEMPTED")を送出
#       （agent.schema.json inject_raw_data_rows=const:false の実行時強制）
#     - 安全なpayloadをそのまま返す
#
#   async def sanitize_stdout(
#       self,
#       stdout: str,
#       execution_id: str
#   ) -> str:
#     - stdoutに対してLayer 1 PIIパターンを適用
#     - 検出された箇所を "[REDACTED]" に置換して返す
#     - RT-004ルールの実装（agents/runtime.yaml参照）
```

3. `tests/unit/test_policy_engine.py` を作成してください：

```python
# テスト項目:
# - test_enforce_valid_scope: 正常なスコープでenforce()が通過
# - test_enforce_invalid_scope: 未付与スコープでPermissionDeniedError
# - test_enforce_expired_token: 期限切れトークンでSecurityViolationError
# - test_enforce_wrong_binding: execution_id不一致でSecurityViolationError
# - test_audit_written_on_success: 成功時もauditが記録されること
# - test_audit_written_on_failure: 失敗時もauditが記録されること
# - test_context_guard_raw_data_blocked: raw_data_rowsキーでSecurityViolationError
# - test_sanitize_stdout_redacts_pii: 電話番号パターンが[REDACTED]に置換されること
```

### 制約事項
- PolicyEngineはビジネスロジックを持たないこと（権限検証のみ）
- 全ての違反は必ず監査ログに記録してから例外を送出すること
- 監査ログ記録に失敗しても例外送出はブロックしないこと
  （audit失敗で元の違反が隠蔽されることを防ぐ）
```

---

## PROMPT 3-3: var_nエイリアスシステム

```
CIE Platformのvar_nエイリアス管理システムを実装してください。
患者識別情報を含む列名を安全に管理します。

### 読み込むべき仕様ファイル
- architecture/security-model.md (var_n Alias System セクション)
- architecture/security-pii-filter.md (Section 8: var_nエイリアス設計との整合)
- knowledge/R/statistical_packages.md (var_n Alias System セクション)
- spec/permissions.yaml (r_code.restore_variables — security agent only)

### 前提
- PROMPT 2-2の PIIFilter が存在します
- PROMPT 3-1の CapabilityToken, CapabilityScope が存在します

### 作成するもの

1. `cie/security/var_alias.py` を作成してください：

```python
# VarNAliasMap クラス:
#   __init__(self) -> None
#     - _map: dict[str, str]  # {"var_1": "original_col_name"}
#     - _reverse: dict[str, str]  # {"original_col_name": "var_1"}
#     - _locked: bool = False  # restore後はTrue
#
#   def register(self, original_col_names: list[str]) -> dict[str, str]:
#     - 列名リストをvar_1, var_2, ... にマッピング
#     - 既に登録済みの場合はVarNAlreadyRegisteredError
#     - 戻り値: {var_n: original_name} の辞書
#     - _mapと_reverseを更新
#
#   def get_var_n(self, original_name: str) -> str:
#     - original_nameからvar_nを返す
#     - 未登録の場合はKeyError
#
#   def restore(
#       self,
#       token: CapabilityToken
#   ) -> dict[str, str]:
#     - token.require_scope(CapabilityScope.R_CODE_RESTORE_VARIABLES) を呼ぶ
#       → 失敗でPermissionDeniedError（Security Agent以外はここで失敗する）
#     - _locked = True にしてからmapのコピーを返す
#     - 2回目以降の呼び出しはAlreadyRestoredError
#
#   def to_proxy_metadata(self) -> dict[str, str]:
#     # var_nのみ返す（original名は返さない）
#     - {var_n: "---"} 形式で返す（値はマスク）
#
# VarNAlreadyRegisteredError(CIEError)
# AlreadyRestoredError(CIEError)

# AliasStore クラス（execution_idでVarNAliasMapを管理）:
#   __init__(self) -> None
#     - _store: dict[str, VarNAliasMap]
#
#   def create(self, execution_id: str) -> VarNAliasMap:
#     - 新しいVarNAliasMapを生成してstoreに保存して返す
#
#   def get(self, execution_id: str) -> VarNAliasMap:
#     - execution_idに対応するmapを返す
#     - 存在しない場合はKeyError
#
#   def drop(self, execution_id: str) -> None:
#     - execution_id完了後にmapを削除（メモリクリア）
```

2. `tests/unit/test_var_alias.py` を作成してください：

```python
# テスト項目:
# - test_register_creates_var_n: 列名がvar_1, var_2...に変換されること
# - test_get_var_n: original→var_nの変換
# - test_restore_requires_scope: r_code.restore_variables scopeなしでPermissionDeniedError
# - test_restore_with_valid_scope: 正しいscopeで元の列名が返ること
# - test_restore_locked_after_first: 2回目のrestoreでAlreadyRestoredError
# - test_proxy_metadata_masks_values: to_proxy_metadata()が"---"を返すこと
# - test_alias_store_lifecycle: create/get/dropのライフサイクル
# - test_double_register_fails: 同じexecution_idへの2回登録でエラー
```

### 制約事項
- _mapと_reverseは外部から直接アクセスできないこと（privateプロパティ）
- restore()はSecurity Agentのtokenがある場合のみ成功すること
  （CapabilityScope.R_CODE_RESTORE_VARIABLESチェックを省略しないこと）
- dropされたexecution_idのmapはメモリから完全に削除されること
```
