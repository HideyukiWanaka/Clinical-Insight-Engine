# CIE 全機能実装プラン

仕様（MANIFEST.yaml / spec/ / agents/ / decisions/ADR）と実装の網羅監査に基づく、全機能実装のマスタープラン。
エラーが起きにくい順（部品を各段でハーネス検証 → 統合点の多いフルDAGを後半）に構成。

## 肝（プロジェクトの価値）
- **AI を統計アドバイザー兼プログラマーとして、研究を対話的に前進させる**
- **Skill を更新することで使いやすさが育っていく**（自己改善）

## 監査で判明した「仕様にあるが未実装／未配線」
| # | 機能 | 根拠 | 状態 |
|---|------|------|------|
| 1 | Visualization が図を生成しない（仕様のみ） | visualization.yaml | 未 |
| 2 | Reporting が原稿を生成しない（テンプレのみ、LLM/ナレッジ未使用） | reporting.yaml | 未 |
| 3 | ユーザー指定フォーマット（target_journal_style 等）読まれず・選択UIなし | reporting.yaml | 未 |
| 4 | ユーザー独自フォーマットSkill（skills/user/）を誰も適用しない | ADR-0002 | 未 |
| 5 | Skill適用そのもの（core Skillも未使用、SkillLoader呼出しゼロ） | MANIFEST | 未 |
| 6 | メタSkill/自己改善（SKILL.mdのみ、reviewer→提案→承認→更新 未接続） | ADR-0002 | 未 |
| 7 | 評価ステージ（モジュールは在るがワークフロー未接続、evaluationノード素通り） | evaluation/ | 未 |
| 8 | decisionノードのルーティング（rules評価なし） | workflow.yaml | 未 |
| 9 | フルDAGのE2E（承認/再開・下流キー整合が未完） | workflow.yaml | 未 |
| 10 | 継続解析（対話的リファインメント） | 要望/理想UX | 未 |

## フェーズ計画と進捗

### ✅ フェーズ1（B）: `statistical_results` 生成＋整形 — 完了
- RuntimeAgent が `result.json` をパース → `statistical_results`（下流契約キー）を出力。捏造防止
- R生成プロンプトの出力キーを下流契約に統一
- `cie/reporting/result_formatter.py`：人間可読整形（p<0.001のAPA表記、95%CI、群別要約）
- app.py/results.py 配線、フォーマッタ単体テスト
- **検証済**: ハーネスで NL→R生成→実行→パース→整形（実 t検定：p<0.001, Cohen's d=1.04, 95%CI）

### ✅ フェーズ2: Visualization 実生成 — 完了
- LLM＋reference_library 注入、ナレッジ（ggplot2_best_practices/chart_selection_guide）参照
- 実行可能な ggplot2 R を生成（_VZ_R_GEN_SYSTEM_PROMPT＋RAG＋キャッシュ）→ インライン runtime実行 → PNG出力
- `figure_manifest` に実パス（actual_path）を収録。RUNTIME_INVOKE_EXECUTION を visualization スコープに追加
- app.py: viz_runtime_provider/viz_scripts/viz_output を VisualizationAgent に配線
- **検証済**: ハーネス（scratchpad/harness_viz_exec.py）で実PNG生成（figure_fig_box_plot_with_jitter_001.png）、figure_manifestに実パス確認

### ✅ フェーズ3: Reporting 実生成＋標準フォーマット — 完了
- LLM＋ナレッジ（manuscript_structure/result_interpretation/reporting_checklists）で実原稿生成（数値は statistical_results 由来のみ）
- `reporting_checklist_id`（CONSORT/STROBE/TRIPOD+AI 2024/PRISMA 2020…）＋`target_journal_style`（APA/AMA/Vancouver）反映。未指定は study_design から推論
- APA: "p = .034", AMA: "P = .034", Vancouver: "p = 0.034" — 全スタイル検証済み
- [TRACE: statistical_results.<field>] タグで RP-001 追跡性を確保、[UNRESOLVED_ITEM] で RP-004 人間承認事項を列挙
- template fallback（llm_client=None）でユニットテスト互換性を維持
- app.py 配線: ReportingAgent に llm_client + reference_library 注入済み
- **検証済**: ハーネス（scratchpad/harness_reporting_exec.py）で APA＋STROBE 原稿（7セクション）、p値フォーマット×6ケース、checklist_inferred、explicit override 全 PASSED

### ✅ フェーズ4: Skill適用層（「Skillで賢くなる」核心）— 完了
- `SkillLoader.read_skill_content()` / `get_skill_prompt_block()` を追加（user/ > core/ 優先解決）
- statistics/visualization/reporting に `skill_loader: SkillLoader | None = None` を注入
  - Statistics: method_id → `_METHOD_TO_SKILL_ID` で skill_id を解決しシステムプロンプトに追記
  - Visualization: chart_key → `_CHART_TO_SKILL_ID` で解決
  - Reporting: 常に `reporting/manuscript-section` を解決
- app.py: `SkillLoader(Path("skills"))` を生成し全3エージェントに配線
- user/ Skill 上書きで LLM システムプロンプトが変わることを確認（ユニットテスト3件＋ハーネス5件 全 PASSED）
- `tests/unit/test_skill_application.py`（14件）新規作成、`scratchpad/harness_skill_exec.py` で実証
- **検証済**: 618 passed（+14件）/ 15 failed（既存 DB/SQLAlchemy 系のみ）— 回帰ゼロ

### ✅ フェーズ5: フォーマット選択UI — 完了
- `cie/ui/screens/format_selection.py` 新規作成：チェックリスト (CONSORT/STROBE/TRIPOD+AI/PRISMA/STARD/自動) + 雑誌スタイル (APA/AMA/Vancouver) + ユーザーSkill の選択 UI（expander）
- `cie/reporting/format_context.py` 新規作成：テスト可能な純粋 Python ヘルパー `build_format_context()`
- `cie/ui/app.py`：format session_state キー追加、`_handle_intent()` にフォーマット選択パネル配線、ワークフロー起動時に `build_format_context()` を `dataset_context` にマージ、`_unpack_workflow_result()` に reporting → `manuscript_sections` / visualization → `figures` の抽出を追加
- `cie/agents/reporting.py`：`reporting_skill_id` をペイロードから受け取り `get_skill_prompt_block()` に渡す（ユーザーSkill上書き対応）
- `tests/unit/test_format_selection.py` 新規（18件 PASSED）
- **検証済**: 636 passed（+18件）/ 15 failed（既存 DB 系のみ）— 回帰ゼロ

### ✅ フェーズ6（A）: オーケストレーション完成＋フルDAG — 完了
- **decisionルーティング**: `WorkflowNodeDef.rules` 取込（registry）＋ Orchestrator `_apply_decision_rules`/`_resolve_condition_value`。条件値は accumulated_context から決定論的に解決（top-level → assumption_report/epp_report/analysis_plan/data_quality_report/intent_object → normality は distribution_assumptions フォールバック → デフォルトTrue）。非選択ブランチは prune（completed 扱い）し、pruned ノードの後続（security_review 等）は選択ブランチの後に ready キューへ。`decision_routes` を context に記録、`DECISION_ROUTED` 監査イベント
- **EvaluationAgent 新規**（`cie/agents/evaluation.py`）: correctness40/statistical35/security15/usability10 の4次元を実行、`EvaluationReport.build`（合格閾値90）。context→evaluator artifact アダプタ（statistical_results→primary_result 形へ、原稿list→word_count/methods_text、Cohen's d のみ interpretation 導出、PIIフラグは DQ 完了証跡から）。workflow.yaml 全4ワークフローの evaluation ノードに `agent: evaluation`、AGENT_ALLOWED_SCOPES と spec/permissions.yaml に evaluation 登録
- **承認/再開**: `resume_workflow` が結果dictを返すよう変更。app.py は security_review 停止時に生成Rスクリプトを承認パネル表示（`_maybe_request_security_approval`）→ 承認で `resume_workflow` → 結果マージ
- **下流キー整合**: reviewer が reporting の list 形式 manuscript_sections を正規化／reviewer 出力スキーマを寛容な `review-report.schema.json` に（report.schema.json は strict envelope で不適合だった）／reporting・reviewer の required_scopes を spec/permissions.yaml（正典）に整合（reporting の DATASET_READ_VALIDATED 除去、reviewer の WORKFLOW_STATE_READ→DATASET_READ_VALIDATED — 実DAGで PERMISSION_DENIED になっていた）／statistics は `select_nonparametric` ノードでノンパラ手法を強制／`_unpack_workflow_result` の TaskDispatchResult dataclass 正規化＋evaluation 出力取込／`_build_dataset_context` が DatasetMetadata 契約（var_nエイリアス・欠損率）を供給
- 新規テスト: `tests/unit/test_decision_routing.py`（ルーティング/枝刈り/再開→evaluation完走）＋ `tests/unit/test_evaluation_agent.py`（計34件）
- **検証済**: `scratchpad/harness_full_dag_exec.py` — 実Orchestrator＋実エージェント（LLMのみスタブ）で intake(スキップ)→data_quality×4→statistics×3→decision分岐→security_review停止→resume→**実R実行**（p=0.0141, d=0.653）→**実PNG**→原稿→reviewer→evaluation（4次元スコア）まで完走。回帰 670 passed / 15 failed（既存DB系のみ）
- 既知の残課題: statistical 次元は assumption_report（実際の正規性検定）が未生成のため0点＝正直な評価（フェーズ7で実検定を積む）

### ⬜ フェーズ7（C）: 継続解析ループ（AIアドバイザー核心）
- statistics/visualization が前回 statistical_results＋前回スクリプトを受理
- 継続プロンプト（前回結果を踏まえ次の解析を提案・生成）
- 対話UI：結果の下で追加解析を相談、解析履歴を保持／リスク: 中

### ⬜ フェーズ8: Skill自己改善ループ
- メタSkillのpython実装（skill-evaluator/proposer）
- reviewer 発見・評価スコア → Skill改善提案 → **必ず人間承認**（ADR-0002）→ SkillLifecycle で version更新・旧版archive
- 更新後に出力/スコア改善を確認／リスク: 中〜高

## 全フェーズ共通の安全策
- 各フェーズ末で `python3 -m pytest tests/unit/`（現状670件パス／既存失敗15件はDB系の元からの失敗で不変）
- ADR絶対ルール厳守：Planner に workflow_id を出さない／全Skill更新に人間承認／`inject_raw_data_rows=False`／Capabilityトークンは try/finally で失効
- 捏造防止：数値は必ず実R実行の result.json 由来のみ
