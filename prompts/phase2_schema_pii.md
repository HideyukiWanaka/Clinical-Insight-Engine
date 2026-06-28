# CIE Platform — Claude Code Implementation Prompts
# Phase 2: Schema Validation & PII Detection
# File: prompts/phase2_schema_pii.md
# Version: 1.0.0

---

## PROMPT 2-1: スキーマバリデーション基盤

```
CIE Platformのスキーマバリデーション基盤を実装してください。
schemas/配下のJSONスキーマを使って、Agent間のペイロードを検証します。

### 読み込むべき仕様ファイル
- schemas/dataset.schema.json
- schemas/analysis-request.schema.json
- schemas/workflow.schema.json
- schemas/report.schema.json
- schemas/agent.schema.json
- schemas/task.schema.json
- PROJECT_RULES.md Section 13（Schema Rules）

### 前提
- PROMPT 1-1〜1-3の実装が完了しています
- jsonschema >= 4.19 がインストール済みです

### 作成するもの

1. `cie/schemas/validator.py` を作成してください：

```python
# SchemaRegistry クラス:
#   __init__(self, schema_dir: Path) -> None
#     - schema_dirからすべての .schema.json ファイルを読み込み
#     - $id をキーとしてスキーマをキャッシュ
#
#   def get_schema(self, schema_ref: str) -> dict:
#     - schema_refは "cie://schemas/dataset.schema.json" 形式
#     - 存在しない場合はSchemaValidationError("SCHEMA_NOT_FOUND")
#
#   def validate(self, payload: dict, schema_ref: str) -> None:
#     - jsonschema.Draft202012Validatorで検証
#     - 失敗時はSchemaValidationError("SCHEMA_VALIDATION_FAILED")
#       - errors属性にValidationErrorの詳細リストを含める
#     - additionalPropertiesの違反を必ず検出すること
#
#   def validate_agent_output(
#       self,
#       agent_id: str,
#       payload: dict,
#       output_schema_ref: str
#   ) -> None:
#     - validate()のラッパー
#     - 失敗時のerrorにagent_idを含める

# モジュールレベルの関数:
# def load_registry(schema_dir: Path | None = None) -> SchemaRegistry:
#     - schema_dirがNoneの場合はプロジェクトルートの schemas/ を使用
```

2. `cie/schemas/payloads.py` を作成してください：

```python
# Pydanticモデル（schemas/に対応するPythonクラス）:
#
# ColumnMetadata:
#   var_n: str  # パターン: ^var_[0-9]+$
#   inferred_type: Literal["continuous","categorical_binary","categorical_ordinal",
#                          "categorical_nominal","date","text","unknown"]
#   missing_count: int
#   missing_rate_pct: float  # 0.0〜100.0
#   summary_stats: dict | None = None
#   clinical_range_violation: bool | None = None
#
# DatasetMetadata:
#   dataset_id: str  # UUID
#   execution_id: str  # UUID
#   metadata_type: Literal["proxy_metadata", "validated_structural"]
#   source_file_hash: str | None  # sha256:...
#   row_count: int
#   column_count: int
#   columns: list[ColumnMetadata]
#   var_n_alias_map: dict[str, str] | None = None
#   quality_gate_passed: bool | None = None
#   created_at: datetime
#
# IntentObject:
#   objective: str  (analysis-request.schema.jsonのenum値)
#   outcome_type: str
#   predictor_type: str | None = None
#   paired: bool | None = None
#   subject_id_var: str | None = None  # ^var_[0-9]+$
#   n_groups_estimate: int | None = None
#   sample_size_estimate: int | None = None
#   distribution_assumptions: str = "unknown"
#   reporting_checklist_inference: str | None = None
#   natural_language_summary: str | None = None
#   outcome_variables: list[dict] = []
#   predictor_variables: list[dict] = []
#
# AnalysisRequest:
#   execution_id: str
#   intent_object: IntentObject
#   confidence_score: float  # 0.0〜1.0
#   requires_human_clarification: bool
#   clarification_options: list[dict] = []
#   created_at: datetime
```

3. `tests/unit/test_schema_validator.py` を作成してください：

```python
# テスト項目:
# - test_valid_dataset_metadata: 正常なDatasetMetadataが検証を通過すること
# - test_invalid_var_n_pattern: "var_abc"のような無効なvar_nがエラーになること
# - test_additional_properties_rejected: additionalPropertiesがあるとエラーになること
# - test_schema_not_found: 存在しないschema_refでSchemaValidationError
# - test_missing_required_field: 必須フィールド欠落でエラー
# - test_metadata_type_enum: proxy_metadata以外の値でエラー
```

### 制約事項
- スキーマファイルを直接編集しないこと
- 実行時にスキーマをメモリにキャッシュし、毎回ファイル読み込みしないこと
```

---

## PROMPT 2-2: PII検出 Layer 1（正規表現・辞書ベース）

```
CIE Platformのnくーネーション検出フィルタ Layer 1を実装してください。
正規表現と辞書ベースで列名・カテゴリ値ラベルのPIIを検出します。

### 読み込むべき仕様ファイル
- architecture/security-pii-filter.md (Layer 1 セクション全体)
- agents/data-quality.yaml (DQ-001ルール)
- spec/permissions.yaml (capabilities.dataset.read_raw)

### 前提
- PROMPT 1-1の例外クラス（PIIDetectedError）が存在します

### 作成するもの

1. `cie/security/pii_patterns.py` を作成してください：

```python
# architecture/security-pii-filter.md の PII_PATTERNS 辞書を
# そのままPythonコードとして実装してください。
#
# 以下のパターンを全て含めること（md記載の通り）:
#   jp_full_name, patient_id, birth_date, phone_number,
#   address, email, medical_id_jp,
#   value_phone_pattern, value_email_pattern,
#   age_detail, free_text
#
# 各パターンのdict構造:
# {
#   "pattern": re.Pattern,
#   "severity": "CRITICAL" | "WARNING",
#   "target": "column_name" | "category_label",  # targetなしはcolumn_name
#   "description": str
# }
```

2. `cie/security/pii_detector.py` を作成してください：

```python
# PIIFinding dataclass:
#   layer: int  (1, 2, or 3)
#   pattern_id: str | None
#   signal_id: str | None
#   severity: Literal["CRITICAL", "WARNING"]
#   target_type: Literal["column_name", "category_value"]
#   matched_text: str  # 列名はそのまま。カテゴリ値は "[REDACTED]" 固定
#   description: str

# PIIDetectorLayer1 クラス:
#   __init__(self) -> None
#     - pii_patterns.PII_PATTERNS をコンパイル済み状態でロード
#
#   def detect_column_name(self, col_name: str) -> list[PIIFinding]:
#     - column_name対象のパターンのみ適用
#     - マッチした全パターンをPIIFindingのリストで返す
#     - col_nameはmatched_textに記録可（列名はPIIではない）
#
#   def detect_category_labels(
#       self,
#       top_categories: list[dict]  # {"label": str, "count": int}のリスト
#   ) -> list[PIIFinding]:
#     - category_label対象のパターンのみ適用
#     - マッチした場合: matched_text = "[REDACTED]"（値は記録しない）
#
#   def detect(
#       self,
#       col_name: str,
#       top_categories: list[dict] | None = None
#   ) -> list[PIIFinding]:
#     - detect_column_name() + detect_category_labels() を統合
```

3. `tests/unit/test_pii_layer1.py` を作成してください：

```python
# テスト項目（各パターンにつき1ケース以上）:
# - test_jp_full_name_detected: "氏名" -> CRITICAL
# - test_patient_id_detected: "患者ID" -> CRITICAL
# - test_birth_date_detected: "生年月日" -> CRITICAL
# - test_phone_column_detected: "電話番号" -> CRITICAL
# - test_email_column_detected: "メールアドレス" -> CRITICAL
# - test_free_text_warning: "備考" -> WARNING
# - test_age_detail_warning: "年齢詳細" -> WARNING
# - test_phone_value_detected: 電話番号形式の値 -> CRITICAL, matched_text="[REDACTED]"
# - test_email_value_detected: email形式の値 -> CRITICAL, matched_text="[REDACTED]"
# - test_safe_column_passes: "sbp_mmhg" -> findings空リスト
# - test_matched_text_redacted_for_values: カテゴリ値は必ず"[REDACTED]"
```

### 制約事項
- カテゴリ値のmatched_textは絶対に"[REDACTED]"以外にしないこと
- 正規表現パターンは architecture/security-pii-filter.md の定義と完全一致させること
- rawデータ行値をこのクラスに渡さないこと（APIに行値を受け取るパラメータを作らない）
```

---

## PROMPT 2-3: PII検出 Layer 2（統計的異常検知）

```
CIE PlatformのPII検出フィルタ Layer 2を実装してください。
dataset.schema.jsonのColumnMetadataフィールドを使った統計的ヒューリスティック検出です。

### 読み込むべき仕様ファイル
- architecture/security-pii-filter.md (Layer 2 セクション全体)
- schemas/dataset.schema.json (ColumnMetadata, SummaryStats定義)

### 前提
- PROMPT 2-2で作成した PIIFinding dataclass が存在します
- cie/schemas/payloads.py の ColumnMetadata が存在します

### 作成するもの

1. `cie/security/pii_detector_layer2.py` を作成してください：

```python
# PIIDetectorLayer2 クラス:
#   def detect(
#       self,
#       col_meta: ColumnMetadata,
#       row_count: int
#   ) -> list[PIIFinding]:
#
#   以下の4つのシグナルを全て実装すること
#   （architecture/security-pii-filter.mdのLayer 2 検出ロジック通り）:
#
#   シグナル1: L2-HIGH-UNIQUENESS
#     - 条件: inferred_type in ("text", "unknown")
#             AND unique_count / row_count > 0.95
#     - severity: CRITICAL
#     - evidence: {unique_count, row_count, uniqueness_ratio, inferred_type}
#
#   シグナル2: L2-DATE-TYPE
#     - 条件: inferred_type == "date"
#     - severity: WARNING
#
#   シグナル3: L2-FIXED-LENGTH-NUMERIC
#     - 条件: top_categoriesの全ラベルが数字のみ
#             AND 全ラベルの長さが同一
#             AND 8 <= length <= 12
#             AND サンプル数 >= 3
#     - severity: CRITICAL
#     - evidence: {label_length, sample_count}
#
#   シグナル4: L2-HIGH-UNIQUENESS-CONTINUOUS
#     - 条件: inferred_type == "continuous"
#             AND unique_count / row_count > 0.99
#     - severity: WARNING
#     - description: "連続値の高ユニーク率（個人測定値の可能性）"
#
#   【注意】row_count=0の場合は全シグナルをスキップ（ZeroDivisionError防止）
#   【注意】summary_stats が None の場合はシグナル1/3/4をスキップ
```

2. `cie/security/pii_filter.py` を作成してください：

```python
# PIIFilter クラス（Layer 1 + Layer 2 を統合）:
#   __init__(self, enable_layer2: bool = True) -> None
#
#   def run(
#       self,
#       col_name: str,
#       col_meta: ColumnMetadata,
#       row_count: int
#   ) -> tuple[list[PIIFinding], list[PIIFinding]]:
#     - Layer 1: col_name と top_categories に対して実行
#     - Layer 2: col_meta と row_count に対して実行（enable_layer2=Trueの場合）
#     - 戻り値: (critical_findings, warning_findings)
#
#   def run_on_prompt(self, prompt_text: str) -> list[PIIFinding]:
#     - 自然言語プロンプトへのLayer 1適用（column_nameパターンのみ）
#     - 適用タイミング1: Planner Agent入力前（security-pii-filter.md参照）
```

3. `tests/unit/test_pii_layer2.py` を作成してください：

```python
# テスト項目:
# - test_high_uniqueness_text_detected: unique_count/row_count=0.98, type=text -> CRITICAL
# - test_date_type_warning: inferred_type="date" -> WARNING
# - test_fixed_length_numeric_detected: 10桁数字カテゴリ3件以上 -> CRITICAL
# - test_low_uniqueness_passes: unique_count/row_count=0.5 -> findings空
# - test_row_count_zero_safe: row_count=0でもエラーなし
# - test_none_summary_stats_safe: summary_stats=NoneでもL2-HIGH-UNIQUENESSスキップ
# - test_continuous_high_uniqueness_warning: 連続値0.999ユニーク率 -> WARNING
# - test_pii_filter_run_integration: Layer1+2統合テスト
```

### 制約事項
- このクラスはrawデータ行値を受け取るパラメータを持たないこと
- ColumnMetadataのフィールドのみ参照すること
- Layer 2の限界はarchitecture/security-pii-filter.md Section 4.3の通りであり、
  偽陽性・偽陰性はトレードオフとして許容する設計
```
