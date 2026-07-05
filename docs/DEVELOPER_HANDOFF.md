# CIE 開発者ハンドオフ（別セッション継続用）

このドキュメント単体で、別のセッション／別の開発者が実装を継続できることを目的とする。
プラン全体は [../IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md) を参照。まず本書 → プラン → 該当コードの順で読む。

---

## 0. まず読むべき既存ファイル（CLAUDE.md の指示）
1. `MANIFEST.yaml`（仕様マスターインデックス）
2. `PROJECT_RULES.md`
3. `decisions/ADR-0001.md`（Orchestrator/Planner 責務境界）
4. `decisions/ADR-0002.md`（メタSkill・自己改善）
5. `decisions/ADR-0003.md`（ナレッジ取り込み）

### ADR 絶対ルール（違反禁止）
- Planner の出力に `workflow_id` を含めない（ADR-0001）。ワークフロー選択は Orchestrator の責務
- 全 Skill 更新に人間承認必須（ADR-0002）
- `inject_raw_data_rows` は常に `False`
- Capability Token は try/finally で必ず失効

---

## 1. これは何か（ゴール）
CIE = 臨床研究者の自然言語入力から、①実施すべき統計解析を判断 → ②**生成AI（LLM）がナレッジ参照で実行可能なRスクリプトを生成** → ③サンドボックスでR実行 → ④結果を（ユーザー指定/独自）フォーマットで出力、を行う AI ネイティブ基盤。

肝は2つ：
- **AI を統計アドバイザー兼プログラマーとして、研究を対話的に前進させる**
- **Skill を更新することで使いやすさが育つ（自己改善）**

UI は Streamlit（`cie/ui/app.py`）。LLM は `cie/core/llm_client.py`（anthropic/openai/google_gemini、env `CIE_ACTIVE_AI_PROVIDER`）。R は実際に `/usr/local/bin/Rscript` で実行される（サンドボックス `cie/runtime/`）。

---

## 2. 現状（2026-07時点、本セッション終了時）

### 動く
- Planner（自然言語→intent_object）LLM経由
- **Statistics の実行可能R生成**（LLM＋ナレッジRAG＋キャッシュ）← フェーズ1で実装、ハーネスで実証
- Runtime サンドボックスR実行＋`result.json`→`statistical_results`パース ← フェーズ1で実装
- 結果整形 `cie/reporting/result_formatter.py` ← フェーズ1で実装
- **Visualization ggplot2 実生成**（LLM＋RAG＋sandbox実行→実PNG）← フェーズ2で実装
- **Reporting 実原稿生成**（LLM＋ナレッジRAG、APA/AMA/Vancouver、CONSORT/STROBE/TRIPOD+AI/PRISMA）← フェーズ3で実装
- **Skill適用層**（SkillLoader: user/ > core/ 優先。statistics/visualization/reporting 注入済み）← フェーズ4で実装
- **フォーマット選択UI**（チェックリスト/雑誌スタイル/ユーザーSkillをUI選択→reporting contextへ伝搬）← フェーズ5で実装
- **フルDAGオーケストレーション**（decisionルーティング・EvaluationAgent・承認/再開・下流キー整合、E2Eハーネス完走）← フェーズ6で実装
- ナレッジ取り込みパイプライン＋UI、data_quality、スキーマ検証、Capabilityトークン/ポリシー、planner セマンティックキャッシュ

### 未実装／未配線（＝残タスク。詳細は IMPLEMENTATION_PLAN.md）
- メタSkill／自己改善ループ（SKILL.md のみ、reviewer→提案→承認→更新 未接続）
- ~~評価ステージ~~→**フェーズ6完了**（EvaluationAgent が evaluation ノードで4次元評価を実行）
- ~~decisionノードのルーティング~~→**フェーズ6完了**（rules 評価＋ブランチ枝刈り）
- ~~フルDAGのE2E~~→**フェーズ6完了**（承認/再開・下流キー整合、`scratchpad/harness_full_dag_exec.py`）
- 継続解析（対話的リファインメント）← 次はフェーズ7
- assumption_check ノードが実際の正規性検定（Shapiro-Wilk 等の実R実行）を行わない → evaluation の statistical 次元が0点（ST-002）。フェーズ7で実検定を積む

---

## 3. アーキテクチャとデータフロー（最重要）

### エージェント基底（`cie/agents/base.py`）
全エージェントは `BaseAgent` を継承し `_execute(agent_input) -> AgentOutput` を実装。`run()` は封印済みで、順に：スコープ検証 → **入力スキーマ検証（`agent_input.input_schema_ref`）** → `_execute` → **出力スキーマ検証（`output.output_schema_ref`）** → 監査。
- 必須プロパティ：`agent_id`, `input_schema_ref`, `output_schema_ref`, `required_scopes`

### Orchestrator（`cie/workflow/orchestrator.py`）
`run_workflow(execution_id, intent_object, dataset_context=None)`：
1. `intent_object` から workflow_id を決定的選択（ADR-0001）。**intent はフラット構造**（`objective`/`outcome_type`/`requires_human_clarification` がトップレベル）を期待
2. `dataset_context`（列メタ・品質ゲート等）を initial_payload にマージ
3. entrypoint が `planner` の場合は intake ノードをスキップ（計算済み intent をシード）
4. DAG を BFS 実行。各ノードで token 発行 →（**入力スキーマは `cie://schemas/task-context.schema.json` 固定**）→ agent.run → 出力を `accumulated_context` にマージ → 次ノードへ
- **ノード出力は accumulated_context に `update()` される** → 下流は前段のキーを payload から読む

### コンテキストのキー連鎖（要！）
`accumulated_context` は `{intent_object, execution_id, frozen_knowledge, dataset_structural_metadata, data_quality_report, ...各ノード出力}`。各エージェントが読む/書く主キー：

| エージェント | 読む | 書く |
|---|---|---|
| statistics | intent_object, data_quality_report, dataset_structural_metadata | selected_methods, analysis_plan, **r_script**, r_script_provenance |
| runtime | **r_script** | execution_result, **statistical_results**, generated_files |
| visualization | **statistical_results**, intent_object | visualization_specifications, figure_manifest |
| reporting | **statistical_results**, figure_manifest, reporting_checklist_id, target_journal_style | manuscript_sections, reporting_checklist_status |
| reviewer | statistical_results, figure_manifest, manuscript_sections, reporting_checklist_status | review_passed, readiness_score, review_report |

- **`statistical_results` が下流の要（linchpin）**。RuntimeAgent が `result.json` をパースして生成する。これが無いと visualization/reporting/reviewer は動かない
- `statistical_results` の契約キー：`method_id, test_name, test_statistic, df, p_value, effect_size, effect_size_measure, ci_lower, ci_upper, sample_size, group_summaries`

### 標準ワークフロー DAG（`spec/workflow.yaml` clinical_analysis_standard）
`intake(planner)` → validate_dataset/classify_variables/detect_missing/detect_outliers(data_quality) → **select_analysis(decision, statistics)** → assumption_check(statistics) → **decision_assumption(decision, rulesルーティング＝フェーズ6実装)** → generate_r_script or select_nonparametric(statistics) → **security_review(approval, 人間承認で一時停止→resume_workflow)** → runtime_execution(runtime) → visualization → reporting → reviewer → **evaluation(EvaluationAgent, 4次元評価＝フェーズ6実装)**

### decisionルーティング（フェーズ6）
- `WorkflowNodeDef.rules`（registry が YAML `rules:` を取込）を Orchestrator `_apply_decision_rules` が評価
- 条件値解決は `_resolve_condition_value`：context top-level → assumption_report/epp_report/analysis_plan/data_quality_report/intent_object コンテナ → `normality` は `intent_object.distribution_assumptions` フォールバック → デフォルト True（主分岐）
- 非選択ブランチは completed 扱いで枝刈り。**pruned ノードの後続**（例: security_review は generate_r_script 依存）は選択ブランチの後に ready キューへ入る（入れないと DAG が早期 completed になる — 実装済みバグ修正）
- ルートは `accumulated_context["decision_routes"][node_id]` に記録、`DECISION_ROUTED:<node>` 監査イベント
- agent 付き decision ノード（prediction の select_prediction_method）は**エージェント実行後**に rules を評価（出力を条件に使えるように）

---

## 4. 重要な規約と落とし穴（ハマりどころ）

1. **agent_id はアンダースコア規約**。workflow.yaml の `agent:`、`AGENT_ALLOWED_SCOPES`（`cie/security/capability_token.py`）、Orchestrator のトークンバインドが全て `data_quality`（ハイフンでない）。トークンは `validate_binding` で `bound_agent_id == agent.agent_id` を厳格照合 → 不一致は SecurityViolationError。新エージェントの agent_id は必ずこの3箇所と一致させる
2. **ディスパッチ入力スキーマは `task-context.schema.json`（寛容）**。Orchestrator は accumulated_context をこのスキーマで検証（`task.schema.json` はエンベロープ用で accumulated_context とは別物。混同禁止）
3. **出力スキーマは各エージェント固有**だが、内部成果物系は寛容スキーマ（analysis-plan/visualization-plan/manuscript-section/task-context、いずれも `additionalProperties: true`）。新規追加キーは基本通る
4. **ナレッジ .md は `MarkdownReferenceLibrary`（`cie/knowledge/reference_library.py`）で読む**。従来の `KnowledgeLoader` は METADATA.yaml しか読まず、`knowledge/official/*.md`（25件）はロードされない（frozen_knowledge は実質空）。R生成のRAG参照元はこの reference_library
5. **R サンドボックスの env は WORKSPACE_DIR / OUTPUT_DIR / CIE_EXECUTION_ID のみ**（RT-001、ホスト変数は継承しない）。よって：
   - データは `WORKSPACE_DIR/dataset.csv` に置く（app が配置）。生成Rは `read.csv(file.path(Sys.getenv("WORKSPACE_DIR"),"dataset.csv"))`
   - 結果は `OUTPUT_DIR/result.json` に書く。RuntimeAgent がここを読む
   - サンドボックスは毎回別プロセス＝ステートレス。前回のRオブジェクトは引き継げない（継続解析は result.json/データ再読込で積み上げる）
6. **捏造防止**：数値は必ず実R実行の result.json 由来のみ。スクリプトが無い/失敗時は捏造せず `statistical_results=None`＋理由を出す（RuntimeAgent 実装済みの方針）
7. **トークン節約キャッシュ**：`RScriptCache`（`cie/cache/r_script_cache.py`）は解析の「形」（method_id＋変数ロール＋列シグネチャ＋provider/model）でRスクリプトをキャッシュ。planner は別途 `CacheStore`（`cie/cache/store.py`）
8. **LLM R生成パターン**（statistics で確立、他エージェントに横展開する型）：
   - system prompt（`_R_GEN_SYSTEM_PROMPT`）＋ user message（method＋intent＋列メタ＋ナレッジ抜粋）
   - `reference_library.retrieve(query_terms, top_k=2)` でRAG
   - 応答から ```r ... ``` を正規表現抽出（`_extract_r_code`）
   - キャッシュ get/put、provenance（llm_generated/from_cache/knowledge_references）を記録
   - LLM未設定なら None を返し仕様のみにフォールバック（既存ユニットテスト互換）

---

## 5. 検証レシピ（必ず実施）

### ユニットテスト（回帰）
```
python3 -m pytest tests/unit/ -q
```
- **現状 670 passed / 15 failed**。15件は本作業前から存在する既存失敗（`test_audit`, `test_database`, `test_skill_lifecycle` の SQLAlchemy/DB系、`test_planner::test_input_schema_ref`）。**新規失敗を出さないこと**が回帰の基準

### ハーネス（実R実行のE2E断片検証）
`scratchpad/harness_r_exec.py` が雛形（statistics→runtime→statistical_results→formatter を実CSV・実Rで検証）。API不要のスタブLLMで実行可能。新フェーズでは同様に、対象エージェント単体を実Rまで通すハーネスで検証してから統合する。
- スタブLLM：`MagicMock` に `complete=AsyncMock(return_value="```r ... ```")`, `.provider`, `.model`
- context_guard スタブは `sanitize_stdout=AsyncMock(side_effect=lambda t,*a,**k: t)`（executor が呼ぶメソッド名に注意）
- RuntimeAgent には `output_dir` を渡す（result.json を読むため）

### コンパイル即時チェック
```
python3 -m py_compile <file>
```

---

## 6. フェーズ別実装ガイド（別セッションはここから着手）

各フェーズは「対象ファイル・踏襲パターン・検証」を記載。順序はエラー最小（下から積み上げ）。

### ✅ フェーズ2: Visualization 実生成 — 完了
- 対象: `cie/agents/visualization.py`
- パターン: statistics の LLM R生成を踏襲。コンストラクタに `llm_client`, `reference_library`, `script_cache`（任意）を追加（app.py の生成箇所も更新）
- 入力: `statistical_results`（フェーズ1で供給済）＋intent_object
- ナレッジ: `knowledge/official/visualization/ggplot2_best_practices.md`, `chart_selection_guide.md`
- 生成: 実行可能な ggplot2 R（`WORKSPACE_DIR/dataset.csv` を読み、`OUTPUT_DIR/figure_*.png` を `ggsave` で保存）。`output_payload["r_script"]` に格納し、DAG順で runtime が実行 → `figure_manifest` に実PNGパス
- 注意: DAG では visualization ノードが runtime_execution の後段。可視化用Rも runtime で実行させる設計にするか、visualization 内で別途 runtime_provider を呼ぶか要判断（既存 figure_manifest 出力キーに合わせる）
- 検証: ハーネスで実PNG生成

### ✅ フェーズ3: Reporting 実生成＋標準フォーマット — 完了
- 対象: `cie/agents/reporting.py`（全面書き換え）、`cie/ui/app.py`（配線更新）
- LLM＋ナレッジRAG（`reporting/manuscript_structure_guide.md`, `result_interpretation_guide.md`, `reporting_checklists.md`）で実原稿生成
- `target_journal_style`（APA/AMA/Vancouver）の p値フォーマット実装。未指定は APA デフォルト
- `reporting_checklist_id` 明示→優先、未指定→study_design から推論（CONSORT/STROBE/TRIPOD+AI 2024/PRISMA 2020）
- llm_client=None → template fallback でユニットテスト互換維持
- 検証: `scratchpad/harness_reporting_exec.py` で PASSED（7セクション出力、p値6パターン、チェックリスト推論/上書き）

### ✅ フェーズ4: Skill適用層 — 完了
- `SkillLoader.read_skill_content()` / `get_skill_prompt_block()` 追加（user/ > core/ 優先）
- statistics: `_METHOD_TO_SKILL_ID` で method_id → skill_id を解決しシステムプロンプトに `=== SKILL INSTRUCTIONS ===` ブロックを追記
- visualization: `_CHART_TO_SKILL_ID` で chart_key → skill_id を解決し同様に注入
- reporting: 常に `reporting/manuscript-section` を解決し注入
- app.py: `SkillLoader(Path("skills"))` を生成し3エージェントに配線
- 新規テスト: `tests/unit/test_skill_application.py`（14件 PASSED）
- ハーネス: `scratchpad/harness_skill_exec.py`（5件 PASSED、プロンプト差分を目視確認）
- 回帰: 618 passed / 15 failed（既存 DB 系のみ）

### ✅ フェーズ5: フォーマット選択UI — 完了
- `cie/ui/screens/format_selection.py` — `render_format_selection()`: チェックリスト/雑誌スタイル/ユーザーSkill expander（presentation-only）
- `cie/reporting/format_context.py` — `build_format_context()`: streamlit なし純粋 Python ヘルパー（テスト可能）
- `cie/agents/reporting.py` — `_execute` が `payload.get("reporting_skill_id")` を読み、指定スキルIDで `get_skill_prompt_block()` を呼ぶ
- `cie/ui/app.py` — `_init_session_state()` に format_* キー追加、`_handle_intent()` に `render_format_selection` 配線、ワークフロー起動時に `build_format_context()` を `dataset_context` にマージ、`_unpack_workflow_result()` に reporting/viz 結果の抽出追加
- 新規テスト: `tests/unit/test_format_selection.py`（18件 PASSED）
- 回帰: 636 passed / 15 failed（既存 DB 系のみ）

### ✅ フェーズ6(A): オーケストレーション完成＋フルDAG — 完了
- `cie/workflow/registry.py`: `WorkflowNodeDef.rules` 追加（YAML `rules:` 取込）
- `cie/workflow/orchestrator.py`: `_apply_decision_rules` / `_resolve_condition_value`（decisionルーティング、上記§3参照）、`resume_workflow` が結果 dict を返すように変更
- `cie/agents/evaluation.py` 新規: EvaluationAgent（agent_id=`evaluation`、4次元評価、context→artifact アダプタ。DBには書かない — SkillPerformanceRecord 永続化は EvaluatorService の役割のまま）
- `spec/workflow.yaml`: 全4ワークフローの evaluation ノードに `agent: evaluation`
- `spec/permissions.yaml` + `AGENT_ALLOWED_SCOPES`: evaluation エージェント登録（workflow.state_read / audit.write_entry / skill.read_performance_records）
- **スコープ正典整合（実DAGで PERMISSION_DENIED になっていた）**: reporting から DATASET_READ_VALIDATED を除去、reviewer の WORKFLOW_STATE_READ → DATASET_READ_VALIDATED（spec/permissions.yaml が正典。required_scopes は必ず allow のサブセットに）
- `schemas/review-report.schema.json` 新規（寛容）: reviewer 出力は report.schema.json（strict envelope, additionalProperties:false）に適合しないため専用スキーマに変更
- `cie/agents/reviewer.py`: manuscript_sections が list（Reporting出力形式）でも正規化して処理
- `cie/agents/statistics.py`: node_id=`select_nonparametric` でノンパラ手法を強制
- `cie/ui/app.py`: EvaluationAgent 配線、`_build_dataset_context` が DatasetMetadata 契約（var_n エイリアス、欠損率）を供給、`_unpack_workflow_result` の dataclass 正規化＋evaluation 取込、`_maybe_request_security_approval`（停止時に生成Rを承認パネル表示）→ 承認で `resume_workflow` → 結果マージ
- 検証: `scratchpad/harness_full_dag_exec.py`（実Orchestrator/実エージェント/実R/実PNG、LLMのみスタブ）全項目 PASSED。回帰 670 passed / 15 failed（既存DB系のみ）
- 残課題: assumption_check が実検定を実行しないため evaluation の statistical 次元は0点（正直な評価）。フェーズ7で実検定を積む

### フェーズ7(C): 継続解析ループ ← 次はここ
- statistics/visualization が `prior_statistical_results`＋`prior_r_script` を受理する任意入力を追加
- 継続プロンプト分岐。前回 result.json/データを読み直して積み上げ
- UI：結果の下に「この結果を踏まえ追加解析を相談」入力＋会話ループ、`session_state` に解析履歴保持

### フェーズ8: Skill自己改善
- メタSkill python実装（`skills/meta/skill-evaluator`, `skill-proposer` は現状 SKILL.md のみ）
- reviewer 発見・評価スコア → Skill改善提案 → **必ず人間承認**（ADR-0002）→ `cie/skills/lifecycle.py` の SkillLifecycleService で version 更新・旧版 archive
- 検証: 更新後に同解析の出力/スコア改善

---

## 7. フェーズ6で変更/新規したファイル

### 新規
- `cie/agents/evaluation.py` — EvaluationAgent（4次元評価、context→artifact アダプタ）
- `schemas/review-report.schema.json` — reviewer 出力用の寛容スキーマ
- `tests/unit/test_decision_routing.py` — decisionルーティング/枝刈り/再開完走
- `tests/unit/test_evaluation_agent.py` — EvaluationAgent（アダプタ含む）
- `scratchpad/harness_full_dag_exec.py` — フルDAG E2E ハーネス（実R/実PNG）

### 変更
- `cie/workflow/registry.py` — `WorkflowNodeDef.rules` 追加
- `cie/workflow/orchestrator.py` — decisionルーティング、pruned 後続のキューイング、`resume_workflow` が結果を返す
- `spec/workflow.yaml` — evaluation ノードに `agent: evaluation`（4ワークフロー）
- `spec/permissions.yaml` — evaluation エージェントの permission matrix 追加
- `cie/security/capability_token.py` — AGENT_ALLOWED_SCOPES に evaluation
- `cie/agents/reporting.py` — required_scopes を正典に整合（DATASET_READ_VALIDATED 除去）
- `cie/agents/reviewer.py` — required_scopes 整合、出力スキーマ変更、manuscript list 正規化
- `cie/agents/statistics.py` — select_nonparametric ノードでノンパラ強制
- `cie/ui/app.py` — evaluation 配線、DatasetMetadata 供給、承認→resume 配線、`_unpack_workflow_result` 修正
- `tests/unit/test_reporting_agent.py` / `test_reviewer.py` — スコープ/スキーマ期待値を正典に更新

## 7b. フェーズ5で変更/新規したファイル

### 新規
- `cie/ui/screens/format_selection.py` — フォーマット選択 UI コンポーネント（presentation-only）
- `cie/reporting/format_context.py` — `build_format_context()` ヘルパー（streamlit 依存なし）
- `tests/unit/test_format_selection.py` — フォーマット選択 18 件ユニットテスト

### 変更
- `cie/agents/reporting.py` — `_generate_manuscript_with_llm` に `reporting_skill_id` パラメータ追加、ペイロードの skill_id を反映
- `cie/ui/app.py` — format session_state キー追加、`_handle_intent()` 配線、`build_format_context()` マージ、`_unpack_workflow_result()` reporting/viz 出力抽出

---

## 8. フェーズ1〜4で変更/新規したファイル（参考）

### 新規（フェーズ1〜4）
- `cie/agents/runtime.py` — RuntimeAgent（R実行＋result.jsonパース→statistical_results、捏造防止）
- `cie/knowledge/reference_library.py` — MarkdownReferenceLibrary（.mdをRAG検索）
- `cie/cache/r_script_cache.py` — RScriptCache（Rスクリプトのトークン節約キャッシュ）
- `cie/reporting/__init__.py`, `cie/reporting/result_formatter.py` — 結果整形
- `schemas/task-context.schema.json` — ディスパッチ用寛容スキーマ
- `schemas/analysis-plan.schema.json`, `visualization-plan.schema.json`, `manuscript-section.schema.json` — 欠落していた出力スキーマ（寛容）
- `tests/unit/test_result_formatter.py`
- `IMPLEMENTATION_PLAN.md`, `docs/DEVELOPER_HANDOFF.md`（本書）

### 変更（フェーズ1〜4）
- `cie/agents/statistics.py` — LLM＋ナレッジRAG＋キャッシュでR生成、result.json契約キー統一
- `cie/agents/data_quality.py` — agent_id を `data_quality`（アンダースコア）に統一、produced_by も
- `cie/agents/planner.py` — JSON抽出堅牢化・キャッシュ汚染ガード・outcome_variables推論フォールバック
- `cie/workflow/orchestrator.py` — ディスパッチ入力スキーマを task-context に、dataset_context マージ、intake スキップ、AuditEventSeverity.ERROR→CRITICAL
- `cie/cache/store.py` — delete_by_key 追加
- `cie/core/llm_client.py` — （既存の gemini モデル名調整）
- `cie/ui/app.py` — 各エージェント配線（statistics へLLM/参照/キャッシュ、runtime へ output_dir、planner/runtime を registry 追加）、CSV→workspace/dataset.csv、intent フラット化、statistical_results 取り込み・表示
- `cie/ui/screens/intent_entry.py` — intent プレビューのネスト解消・フィールド整合
- `cie/ui/screens/results.py` — statistical_results 整形表示
- `schemas/agent.schema.json`, `report.schema.json`, `task.schema.json` — agent_id enum に `data_quality` 追加
- `tests/unit/test_data_quality.py` — agent_id 期待値更新

---

## 8. メモ（Claude セッションメモリ、参考）
`~/.claude/projects/-Users-...-Clinical-insight-engine/memory/` に要約あり：`mvp-core-design.md`, `spec-implementation-gaps.md`。ただし正典はリポジトリ内の本書と IMPLEMENTATION_PLAN.md。
