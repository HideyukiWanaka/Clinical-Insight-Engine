# CIE Platform — Claude Code Implementation Prompts
# Phase 7: Evaluation System
# File: prompts/phase7_evaluation.md
# Version: 1.1.0

---

## PROMPT 7-0: ブランチ作成

```
# Phase 6 が main に merge 済みであることを確認してから実行してください。
git checkout main
git pull origin main
git checkout -b feature/phase-7-evaluation
```

---

## PROMPT 7-1: Evaluation基底クラスとCorrEctness評価

```
CIE PlatformのEvaluation基底クラスとCorrectness評価を実装してください。
全ての成果物が評価を通過することが完了の条件です（AP-017）。

### 読み込むべき仕様ファイル
- evaluation/correctness.yaml (全セクション)
- schemas/report.schema.json (review_report_section)
- agents/reviewer.yaml

### 前提
- PROMPT 5-1の BaseAgent が存在します
- PROMPT 2-1の SchemaRegistry が存在します

### 作成するもの

1. `cie/evaluation/base.py` を作成してください：

```python
# EvaluationDimension Enum:
#   CORRECTNESS = "correctness"
#   STATISTICAL = "statistical"
#   SECURITY = "security"
#   USABILITY = "usability"
#   REGRESSION = "regression"

# CheckResult dataclass:
#   check_id: str           # 例: "CC-001"
#   dimension: EvaluationDimension
#   passed: bool
#   severity: Literal["critical", "advisory"]
#   message: str
#   actual_value: str | None = None
#   expected_value: str | None = None

# DimensionScore dataclass:
#   dimension: EvaluationDimension
#   score: float            # 0.0〜100.0
#   weight_pct: int
#   check_results: list[CheckResult]
#   critical_failure: bool  # criticalチェックが1つでも失敗したらTrue

# EvaluationReport dataclass:
#   execution_id: str
#   report_id: str
#   dimension_scores: dict[EvaluationDimension, DimensionScore]
#   weighted_total_score: float
#   passed: bool            # weighted_total_score >= 90 かつ critical_failure=Falseの全次元
#   produced_at: datetime

# BaseEvaluator 抽象クラス:
#   dimension: EvaluationDimension   # abstractproperty
#   weight_pct: int                  # abstractproperty
#
#   @abstractmethod
#   def evaluate(self, artifacts: dict) -> DimensionScore: ...
#
#   def _pass_score(
#       self,
#       check_results: list[CheckResult]
#   ) -> float:
#     - critical check が1つでも失敗 → 0.0
#     - advisory checkは weight 0.5 で計算
#     - 全critical pass のとき: 100 - (advisory失敗数 * 50 / advisory総数)
#     - 最低0.0、最大100.0にクリップ
```

2. `cie/evaluation/correctness.py` を作成してください：

```python
# CorrectnessEvaluator(BaseEvaluator) クラス:
#   dimension = EvaluationDimension.CORRECTNESS
#   weight_pct = 40  # evaluation/correctness.yaml
#
#   def evaluate(self, artifacts: dict) -> DimensionScore:
#     # artifacts には以下を期待:
#     #   execution_result: dict (r_executor.ExecutionResult)
#     #   review_report: dict
#     #   analysis_plan: dict
#
#     # 以下のチェックを全て実装（evaluation/correctness.yaml CC-001〜CC-007）:
#
#     # CC-001 (critical): p_value が 0.0〜1.0 の範囲内
#     #   execution_result["primary_result"]["p_value"]
#
#     # CC-002 (critical): effect_size が 0.0 以上
#     #   execution_result["effect_size"]["value"]
#
#     # CC-003 (critical): n_observations が analysis_plan の期待値と一致
#     #   ±5% の誤差を許容
#
#     # CC-004 (advisory): CI幅が合理的（上限 > 下限）
#     #   ci_upper > ci_lower であること
#
#     # CC-005 (advisory): method_justification フィールドが存在し空でない
#
#     # CC-006 (critical): p < 0.05 のとき CI が null値を含まない
#     #   連続アウトカム: CI が 0 を含まない
#     #   ロジスティック: OR の CI が 1.0 を含まない
#
#     # CC-007 (advisory): effect_size の interpretation が
#     #   "negligible"|"small"|"medium"|"large" のいずれか
```

3. `tests/unit/test_correctness_evaluator.py` を作成してください：

```python
# テスト項目:
# - test_valid_results_pass: 正常な結果で全チェック通過
# - test_invalid_p_value_fails_cc001: p_value=1.5 で CC-001 critical failure
# - test_negative_effect_size_fails_cc002: effect_size=-0.1 で CC-002 critical failure
# - test_ci_inconsistent_with_p_fails_cc006: p=0.01 かつ CI=[−0.5, 0.3] で CC-006 failure
# - test_ci_consistent_with_p_passes_cc006: p=0.01 かつ CI=[0.2, 0.8] で CC-006 pass
# - test_critical_failure_zeroes_score: critical failure時にscore=0.0
# - test_advisory_failure_reduces_score: advisory のみ失敗時にscore>0
```

### 制約事項
- evaluation/correctness.yaml のweightと一致させること（weight_pct=40）
- CC-006はロジスティック回帰と連続アウトカムで判定ロジックが異なる
  （method_usedフィールドで分岐）
- チェックIDは evaluation/correctness.yaml の定義通りに使用すること
```

---

## PROMPT 7-2: Statistical評価とSecurity評価

```
CIE PlatformのStatistical評価とSecurity評価を実装してください。

### 読み込むべき仕様ファイル
- evaluation/statistical.yaml (全セクション)
- evaluation/security.yaml (全セクション)

### 前提
- PROMPT 7-1の BaseEvaluator, CheckResult, DimensionScore が存在します

### 作成するもの

1. `cie/evaluation/statistical.py` を作成してください：

```python
# StatisticalEvaluator(BaseEvaluator) クラス:
#   dimension = EvaluationDimension.STATISTICAL
#   weight_pct = 35  # evaluation/statistical.yaml
#
#   def evaluate(self, artifacts: dict) -> DimensionScore:
#     # 以下のチェックを実装（evaluation/statistical.yaml ST-001〜ST-007）:
#
#     # ST-001 (critical): set.seed(42) がRスクリプト内に存在すること
#     #   artifacts["r_script_content"] を検索
#
#     # ST-002 (critical): 仮定チェックが実行されていること
#     #   assumption_report が存在し、normality_results が空でない
#
#     # ST-003 (critical): post-hoc検定がomnibus p < 0.05 のときのみ実行
#     #   posthoc が None ↔ omnibus_p >= 0.05 の整合性チェック
#
#     # ST-004 (advisory): 効果量の解釈ラベルが値と一致すること
#     #   Cohen's d: <0.2=negligible, <0.5=small, <0.8=medium, >=0.8=large
#
#     # ST-005 (critical): paired設計で独立検定が使われていないこと
#     #   design="paired" かつ method_used in {"welch_t_test","mann_whitney_u"} → failure
#
#     # ST-006 (advisory): Fisherの正確確率検定が小サンプルで使用されていること
#     #   カテゴリカル変数で期待度数 < 5 のセルがある場合
#
#     # ST-007 (advisory): multiple testing補正が複数アウトカム時に適用されていること
```

2. `cie/evaluation/security.py` を作成してください：

```python
# SecurityEvaluator(BaseEvaluator) クラス:
#   dimension = EvaluationDimension.SECURITY
#   weight_pct = 15  # evaluation/security.yaml
#
#   def evaluate(self, artifacts: dict) -> DimensionScore:
#     # 以下のチェックを実装（evaluation/security.yaml SEC-001〜SEC-006）:
#
#     # SEC-001 (critical): Rスクリプトにvar_nエイリアスのみ使用（元列名なし）
#     #   artifacts["r_script_content"] に var_n 以外の列名パターンがないこと
#     #   検出: "var_[0-9]+" 以外の識別子を列名として使っていないか確認
#
#     # SEC-002 (critical): PII検出フィルタが実行されたこと
#     #   artifacts["quality_report"]["pii_checks_performed"] == True
#
#     # SEC-003 (critical): audit_logにBREACHイベントがないこと
#     #   artifacts["audit_events"] に severity="BREACH" がないこと
#
#     # SEC-004 (critical): raw_data_rowsがcontextに注入されていないこと
#     #   artifacts["context_payloads"] に "raw_data_rows" キーがないこと
#
#     # SEC-005 (advisory): Capability Tokenが全ノードで発行・失効されていること
#     #   audit_log に token_issued と token_revoked が対になっていること
#
#     # SEC-006 (critical): レポートにvar_n以外の列名が出力されていないこと
#     #   （Security Agentのrestore後は元列名が正しく戻っていること）
```

3. `tests/unit/test_statistical_evaluator.py` を作成してください：

```python
# - test_set_seed_missing_fails_st001
# - test_paired_with_independent_test_fails_st005
# - test_posthoc_without_significant_omnibus_fails_st003
# - test_effect_size_label_correct_st004
```

4. `tests/unit/test_security_evaluator.py` を作成してください：

```python
# - test_original_colname_in_script_fails_sec001
# - test_pii_check_not_performed_fails_sec002
# - test_breach_event_fails_sec003
# - test_raw_data_rows_in_context_fails_sec004
# - test_clean_execution_passes_all_sec_checks
```

### 制約事項
- security_evaluatorはevaluation/security.yamlのweight_pctを使用すること
- SEC-001のvar_n検出は厳格に行うこと（日本語列名が1文字でもあればfailure）
- ST-003のpost-hocチェックはomnibus p値との整合性を必ず確認すること
```

---

## PROMPT 7-3: Evaluation統合と回帰テスト

```
CIE PlatformのEvaluation統合サービスと回帰テストシステムを実装してください。

### 読み込むべき仕様ファイル
- evaluation/regression.yaml (全セクション — skill_performance_monitoringを含む)
- evaluation/usability.yaml
- spec/configuration.yaml (evaluation_gateways)

### 前提
- PROMPT 7-1〜7-2の全Evaluatorが存在します
- PROMPT 1-2の SkillPerformanceRecord テーブルが存在します
- PROMPT 1-3の AuditService が存在します

### 作成するもの

1. `cie/evaluation/usability.py` を作成してください：

```python
# UsabilityEvaluator(BaseEvaluator) クラス:
#   dimension = EvaluationDimension.USABILITY
#   weight_pct = 10  # evaluation/usability.yaml
#
#   def evaluate(self, artifacts: dict) -> DimensionScore:
#     # US-001 (advisory): unresolved_items が3件以下
#     # US-002 (advisory): 原稿のword_count が目標範囲内
#     # US-003 (advisory): figure が少なくとも1件生成されていること
#     # US-004 (advisory): methods_textが200文字以上
```

2. `cie/evaluation/evaluator_service.py` を作成してください：

```python
# EvaluatorService クラス:
#   MINIMUM_PASS_SCORE: float = 90.0  # spec/configuration.yaml
#
#   __init__(
#       self,
#       evaluators: list[BaseEvaluator],
#       audit_service: AuditService,
#       db_session_factory: Callable
#   ) -> None
#
#   async def run_full_evaluation(
#       self,
#       execution_id: str,
#       artifacts: dict
#   ) -> EvaluationReport:
#     - 全evaluatorを実行してDimensionScoreを収集
#     - 重み付き平均スコアを計算
#       weighted_total = sum(dim.score * dim.weight_pct / 100 for dim in scores)
#     - passed = weighted_total >= MINIMUM_PASS_SCORE
#               AND 全dimensionのcritical_failure == False
#     - EvaluationReportを構築
#     - audit_service.write()で記録
#     - SkillPerformanceRecordをDBに書き込む（ADR-0002）
#     - EvaluationReportを返す
#
#   async def _write_skill_performance_record(
#       self,
#       execution_id: str,
#       workflow_id: str,
#       evaluation_report: EvaluationReport,
#       artifacts: dict
#   ) -> None:
#     # ADR-0002 skill_performance_monitoring の実装
#     # artifacts["skill_id"], artifacts["skill_namespace"], artifacts["skill_version"]
#     # evaluation_report から correctness_score, statistical_score を取得
#     # SkillPerformanceRecord をDBに挿入
#     # SE-001〜SE-003トリガー条件を確認
#     #   → 条件合致した場合は audit に SKILL_EVALUATION_TRIGGERED を記録
```

3. `cie/evaluation/regression.py` を作成してください：

```python
# RegressionChecker クラス:
#   # evaluation/regression.yaml の REG-001〜REG-005 を実装
#
#   RECURRING_FINDING_WINDOW: int = 5
#   RECURRING_FINDING_THRESHOLD: int = 3
#   PASS_RATE_WINDOW: int = 10
#   PASS_RATE_THRESHOLD: float = 0.80
#
#   def __init__(self, db_session_factory: Callable) -> None
#
#   async def check_skill_triggers(
#       self,
#       skill_id: str,
#       skill_namespace: str
#   ) -> list[str]:
#     # cie_database.db の skill_performance_records を参照
#     # 直近5件: 同一finding_idが3件以上 → SE-001
#     # 直近10件: avg pass_rate < 0.80 → SE-002
#     # 最新1件: failed_test_ids が空でない → SE-003
#     # 戻り値: トリガーされた trigger_id のリスト（例: ["SE-001", "SE-003"]）
```

4. `tests/unit/test_evaluator_service.py` を作成してください：

```python
# - test_all_dimensions_run: 5次元全て評価が実行されること
# - test_weighted_score_calculated: 重み付き平均が正確に計算されること
# - test_critical_failure_fails_overall: 1次元でもcritical失敗なら passed=False
# - test_skill_performance_record_written: SkillPerformanceRecordがDBに書かれること
# - test_se001_triggered_on_recurring: 同一findingが3/5件でSE-001トリガー
# - test_se002_triggered_on_low_rate: avg_pass_rate < 0.80でSE-002トリガー

### 制約事項
- 重み付き平均の合計が100%になることを確認すること
  （correctness:40 + statistical:35 + security:15 + usability:10 = 100）
- SkillPerformanceRecordの書き込みは評価完了後に行うこと（評価自体に影響しない）
- RegressionCheckerはSkillファイルを変更しないこと（検出のみ）

## PROMPT 7-X: Phase 7 完了処理

```
Phase 7 の全実装（PROMPT 7-1〜7-3）が完了し、テストがすべてパスしたことを
確認してから、以下の手順でブランチを main へ統合してください。

### テスト確認
pytest tests/unit/test_correctness_evaluator.py tests/unit/test_statistical_evaluator.py \
       tests/unit/test_security_evaluator.py tests/unit/test_evaluator_service.py -v

### コミット
git add -A
git commit -m "feat(phase7): evaluation system — correctness, composite, regression checker"

### main へ merge
git checkout main
git merge --no-ff feature/phase-7-evaluation \
  -m "merge: phase-7-evaluation into main"

### 次フェーズのブランチを main から作成
git checkout -b feature/phase-8-skills
```
