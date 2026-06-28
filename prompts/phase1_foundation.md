# CIE Platform — Claude Code Implementation Prompts
# Phase 1: Project Foundation
# File: prompts/phase1_foundation.md
# Version: 1.0.0

---

## PROMPT 1-1: プロジェクト初期化

```
あなたはCIE Platform（Clinical Intelligence Environment）のバックエンド実装を担当するエンジニアです。
以下の仕様に従い、Pythonプロジェクトの初期構造を作成してください。

### 読み込むべき仕様ファイル
- MANIFEST.yaml
- PROJECT_RULES.md
- spec/system.yaml

### 作成するもの

1. ディレクトリ構造を以下の通りに作成してください：

```
cie/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── config.py
│   └── exceptions.py
├── agents/
│   └── __init__.py
├── runtime/
│   └── __init__.py
├── workflow/
│   └── __init__.py
├── schemas/
│   └── __init__.py
├── security/
│   └── __init__.py
├── evaluation/
│   └── __init__.py
├── skills/
│   └── __init__.py
└── ui/
    └── __init__.py
tests/
├── __init__.py
├── unit/
│   └── __init__.py
└── integration/
    └── __init__.py
pyproject.toml
```

2. `pyproject.toml` を作成してください。内容：
   - name: "cie-platform"
   - version: "2.1.0"
   - python: ">=3.11"
   - 依存パッケージ（最小限）:
     - pydantic >= 2.0
     - sqlalchemy >= 2.0
     - aiosqlite >= 0.19
     - httpx >= 0.25
     - keyring >= 24.0
     - pyyaml >= 6.0
     - jsonschema >= 4.19
   - 開発依存:
     - pytest >= 7.0
     - pytest-asyncio >= 0.21
     - ruff >= 0.1

3. `cie/core/exceptions.py` を作成してください。以下の例外クラスを定義：

```python
# CIEの全例外の基底クラスと、以下のサブクラス：
# - CIEError (基底)
# - SchemaValidationError
# - PermissionDeniedError
# - SecurityViolationError
# - WorkflowError
# - AgentError
# - RuntimeExecutionError
# - PIIDetectedError (severity: "CRITICAL" | "WARNING" を属性に持つ)
# - SkillError
# - HumanApprovalRequiredError
```

各クラスに：
- `error_code: str` 属性（SCREAMING_SNAKE_CASE）
- `execution_id: str | None` 属性
- `__str__` メソッド

4. `cie/core/config.py` を作成してください。spec/configuration.yamlの内容を
   Pydantic BaseSettingsで読み込むクラス：

```python
# CIEConfig クラス：
# - database_filepath: str  (デフォルト: "{USER_DOCUMENTS}/CIE/cie_database.db")
# - workspace_directory: str
# - offline_first_mode: bool = True
# - default_ui_language: str = "ja"
# - global_minimum_pass_score: int = 90
# - enable_pii_regex_guardrail: bool = True
# - enable_pii_statistical_detection: bool = True
# - enable_pii_ml_detection: bool = False
# - enable_skill_performance_monitoring: bool = True
# - enable_user_skill_registration: bool = True
# - active_ai_provider: str = "anthropic"
# クラスメソッド load_from_yaml(path: str) -> "CIEConfig" を追加
```

### 制約事項
- 型アノテーションを全関数・クラスに付与すること
- docstringをGoogle形式で記述すること
- PROJECT_RULES.md Section 14（Coding Rules）に従うこと
- ビジネスロジックをこのPhaseで実装しないこと（構造のみ）
```

---

## PROMPT 1-2: データベース初期化

```
CIE Platformのデータベース層を実装してください。

### 読み込むべき仕様ファイル
- spec/system.yaml (storage_locations)
- spec/configuration.yaml (database_filepath)

### 前提
PROMPT 1-1で作成した cie/core/config.py が存在します。

### 作成するもの

1. `cie/core/database.py` を作成してください：

```python
# SQLAlchemy 2.0 async engine を使用
# テーブル定義（SQLAlchemy ORM）:

# AuditLog テーブル:
#   id: UUID (PK, auto)
#   timestamp: DateTime (UTC, not null)
#   execution_id: String(36) (not null, indexed)
#   agent_id: String(64)
#   action: String(256) (not null)
#   status: String(32)
#   event_severity: String(16)  # INFO | WARNING | CRITICAL | BREACH
#   payload_hash: String(71)    # sha256:...
#   created_at: DateTime (UTC, auto)
#
# WorkflowInstance テーブル:
#   id: UUID (PK)
#   execution_id: String(36) (unique, indexed)
#   workflow_definition_id: String(64) (not null)
#   workflow_selection_rule_id: String(8)  # WS-001〜WS-004
#   workflow_selection_justification: Text
#   current_state: String(32) (not null)
#   created_at: DateTime
#   updated_at: DateTime
#   completed_at: DateTime (nullable)
#
# SkillPerformanceRecord テーブル:
#   id: UUID (PK, auto)
#   skill_id: String(128) (not null, indexed)
#   skill_namespace: String(16) (not null)  # core | user
#   skill_version: String(16)
#   execution_id: String(36) (indexed)
#   workflow_id: String(64)
#   total_tests: Integer
#   passed_tests: Integer
#   failed_test_ids: JSON
#   reviewer_finding_ids: JSON
#   correctness_score: Float (nullable)
#   statistical_score: Float (nullable)
#   timestamp: DateTime (UTC, not null)

# 関数:
# async def get_engine(config: CIEConfig) -> AsyncEngine
# async def init_db(engine: AsyncEngine) -> None  # テーブル作成
# async def get_session(engine: AsyncEngine) -> AsyncSession  # context manager
```

2. `tests/unit/test_database.py` を作成してください：

```python
# テスト項目:
# - test_init_db_creates_tables: テーブルが正常に作成されること
# - test_audit_log_insert: AuditLogレコードを挿入・取得できること
# - test_workflow_instance_insert: WorkflowInstanceを挿入・取得できること
# - test_skill_performance_record_insert: レコードを挿入・取得できること
# すべてSQLite in-memory DBを使用
# pytest-asyncio を使用
```

### 制約事項
- SQLite（aiosqlite）のみ使用。外部DBへの依存なし（Offline First）
- raw SQL禁止。SQLAlchemy ORM のみ使用
- 全カラムに型アノテーション
```

---

## PROMPT 1-3: ロギング・監査基盤

```
CIE Platformの監査ログ書き込み基盤を実装してください。

### 読み込むべき仕様ファイル
- agents/orchestrator.yaml (audit_policy セクション)
- agents/security.yaml (security_event_classification)
- spec/permissions.yaml (audit.write_entry)

### 前提
- PROMPT 1-2で作成した cie/core/database.py が存在します
- AuditLog テーブルが定義済みです

### 作成するもの

1. `cie/core/audit.py` を作成してください：

```python
# AuditEventSeverity Enum:
#   INFO = "INFO"
#   WARNING = "WARNING"
#   CRITICAL = "CRITICAL"
#   BREACH = "BREACH"

# AuditEvent dataclass:
#   execution_id: str
#   agent_id: str
#   action: str
#   status: str
#   severity: AuditEventSeverity
#   payload: dict  # 書き込み時にsha256ハッシュ化してpayload_hashとして保存
#   timestamp: datetime (UTC, auto)

# AuditService クラス:
#   __init__(self, session_factory: Callable) -> None
#
#   async def write(self, event: AuditEvent) -> None:
#     - payloadをJSON化してsha256ハッシュ計算
#     - AuditLogレコードをDBに挿入
#     - 挿入失敗時はCIEError("AUDIT_INTEGRITY_FAILURE")を送出
#     - 【重要】LLMの内部推論（think span）はpayloadに含めない
#       → payload dictに "reasoning" キーが含まれていればKeyErrorを送出
#
#   async def write_security_event(
#       self,
#       execution_id: str,
#       agent_id: str,
#       event_code: str,
#       severity: AuditEventSeverity,
#       details: dict
#   ) -> None:
#     - write()を呼び出すラッパー
#     - BREACHの場合: write後にBREACH_DETECTEDフラグをDBに記録
#
#   async def get_events(
#       self,
#       execution_id: str,
#       severity_filter: list[AuditEventSeverity] | None = None
#   ) -> list[AuditLog]:
#     - execution_idでフィルタリング
#     - severity_filterが指定された場合はさらに絞り込み
```

2. `tests/unit/test_audit.py` を作成してください：

```python
# テスト項目:
# - test_write_audit_event: 正常な書き込みと取得
# - test_payload_is_hashed: payload本文はDBに保存されずhashのみ保存されること
# - test_reasoning_key_rejected: payloadに"reasoning"キーがあるとエラー
# - test_breach_severity_recorded: BREACH eventが正しく記録されること
# - test_get_events_filtered: severity_filterが正しく機能すること
# - test_audit_failure_raises: DB挿入失敗時にCIEErrorが送出されること
```

### 制約事項
- payloadの中身をDBに保存しないこと（ハッシュのみ）
- immutabilityを保証するため、UPDATE/DELETEをAuditLogテーブルに発行しないこと
- orchestrator.yaml の capture_reasoning_spans: false を厳守
```
