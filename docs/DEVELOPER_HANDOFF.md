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
- **Statistics の実行可能R生成**（LLM＋ナレッジRAG＋キャッシュ）← 本セッションで実装、ハーネスで実証
- Runtime サンドボックスR実行＋`result.json`→`statistical_results`パース ← 本セッションで実装
- 結果整形 `cie/reporting/result_formatter.py` ← 本セッションで実装
- ナレッジ取り込みパイプライン＋UI、data_quality、スキーマ検証、Capabilityトークン/ポリシー、planner セマンティックキャッシュ

### 未実装／未配線（＝残タスク。詳細は IMPLEMENTATION_PLAN.md）
- Visualization：ggplot2 の**仕様のみ**（実行可能R・実図なし）
- Reporting：**テンプレのみ**（LLM/ナレッジ未使用）
- ユーザー指定フォーマット（`target_journal_style`）読まれず、選択UIなし
- **Skill を誰も適用していない**（core も user も。SkillLoader 呼出しゼロ）
- メタSkill／自己改善ループ（SKILL.md のみ、reviewer→提案→承認→更新 未接続）
- 評価ステージ（`cie/evaluation/*` はワークフロー未接続、evaluationノード素通り）
- decisionノードのルーティング（`rules` 評価コードなし）
- フルDAGのE2E（承認/再開・下流キー整合が未完）
- 継続解析（対話的リファインメント）

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
`intake(planner)` → validate_dataset/classify_variables/detect_missing/detect_outliers(data_quality) → **select_analysis(decision, statistics)** → assumption_check(statistics) → **decision_assumption(decision, ルーティング未実装)** → generate_r_script or select_nonparametric(statistics) → **security_review(approval, 人間承認で一時停止)** → runtime_execution(runtime) → visualization → reporting → reviewer → **evaluation(agentなし＝現状素通り)**

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
- **現状 600 passed / 15 failed**。15件は本作業前から存在する既存失敗（`test_audit`, `test_database`, `test_skill_lifecycle` の SQLAlchemy/DB系、`test_planner::test_input_schema_ref`）。**新規失敗を出さないこと**が回帰の基準

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

### フェーズ2: Visualization 実生成 ← 次はここ
- 対象: `cie/agents/visualization.py`
- パターン: statistics の LLM R生成を踏襲。コンストラクタに `llm_client`, `reference_library`, `script_cache`（任意）を追加（app.py の生成箇所も更新）
- 入力: `statistical_results`（フェーズ1で供給済）＋intent_object
- ナレッジ: `knowledge/official/visualization/ggplot2_best_practices.md`, `chart_selection_guide.md`
- 生成: 実行可能な ggplot2 R（`WORKSPACE_DIR/dataset.csv` を読み、`OUTPUT_DIR/figure_*.png` を `ggsave` で保存）。`output_payload["r_script"]` に格納し、DAG順で runtime が実行 → `figure_manifest` に実PNGパス
- 注意: DAG では visualization ノードが runtime_execution の後段。可視化用Rも runtime で実行させる設計にするか、visualization 内で別途 runtime_provider を呼ぶか要判断（既存 figure_manifest 出力キーに合わせる）
- 検証: ハーネスで実PNG生成

### フェーズ3: Reporting 実生成＋標準フォーマット
- 対象: `cie/agents/reporting.py`
- LLM＋ナレッジ（`reporting/manuscript_structure_guide.md`, `result_interpretation_guide.md`, `reporting_checklists.md`）で実原稿生成。**数値は statistical_results 由来のみ（捏造禁止、RP-001）**
- フォーマット: `payload.get("reporting_checklist_id")`＋**新規に `payload.get("target_journal_style")` を読む**。未指定は study_design から推論（既存 `_CHECKLIST_BY_STUDY_DESIGN`）
- `cie/reporting/result_formatter.py` を journal_style 対応に拡張可
- 検証: ハーネスで APA＋STROBE 原稿

### フェーズ4: Skill適用層
- 対象: statistics/visualization/reporting、`cie/skills/loader.py`（SkillLoader）
- 各エージェントに `SkillLoader` 注入。タスク対応 Skill を `skills/user/ > skills/core/` 優先で解決し、SKILL.md 指示を生成プロンプトへ合成
- 例: `skills/core/reporting/table-one/SKILL.md`, `skills/core/statistics/t-test/SKILL.md`
- 検証: 同じ解析で user Skill 上書きにより出力が変わることを確認

### フェーズ5: フォーマット選択UI
- 対象: `cie/ui/app.py`＋新規/既存スクリーン。チェックリスト＋雑誌スタイル＋登録済みユーザーSkill を選択し reporting コンテキストへ伝搬

### フェーズ6(A): オーケストレーション完成＋フルDAG
- 対象: `cie/workflow/orchestrator.py`, `cie/ui/app.py`, 新規 evaluation エージェント
- decisionノード `rules` 評価（`decision_assumption` の正規性分岐）。現状 decision/evaluation ノードは agent_id 無しだと素通り
- evaluationノード＝評価エージェント新規（`cie/evaluation/*` の correctness/statistical/security/usability をラップ）。agent_registry と AGENT_ALLOWED_SCOPES に登録
- app.py：`security_review`（approval）停止時にRを承認パネル表示 → 承認で `orchestrator.resume_workflow(execution_id, human_decision)`（既存メソッド）
- 検証: 実オーケストレータ・ハーネスで intent→…→evaluation 完走

### フェーズ7(C): 継続解析ループ
- statistics/visualization が `prior_statistical_results`＋`prior_r_script` を受理する任意入力を追加
- 継続プロンプト分岐。前回 result.json/データを読み直して積み上げ
- UI：結果の下に「この結果を踏まえ追加解析を相談」入力＋会話ループ、`session_state` に解析履歴保持

### フェーズ8: Skill自己改善
- メタSkill python実装（`skills/meta/skill-evaluator`, `skill-proposer` は現状 SKILL.md のみ）
- reviewer 発見・評価スコア → Skill改善提案 → **必ず人間承認**（ADR-0002）→ `cie/skills/lifecycle.py` の SkillLifecycleService で version 更新・旧版 archive
- 検証: 更新後に同解析の出力/スコア改善

---

## 7. 本セッションで変更/新規したファイル

### 新規
- `cie/agents/runtime.py` — RuntimeAgent（R実行＋result.jsonパース→statistical_results、捏造防止）
- `cie/knowledge/reference_library.py` — MarkdownReferenceLibrary（.mdをRAG検索）
- `cie/cache/r_script_cache.py` — RScriptCache（Rスクリプトのトークン節約キャッシュ）
- `cie/reporting/__init__.py`, `cie/reporting/result_formatter.py` — 結果整形
- `schemas/task-context.schema.json` — ディスパッチ用寛容スキーマ
- `schemas/analysis-plan.schema.json`, `visualization-plan.schema.json`, `manuscript-section.schema.json` — 欠落していた出力スキーマ（寛容）
- `tests/unit/test_result_formatter.py`
- `IMPLEMENTATION_PLAN.md`, `docs/DEVELOPER_HANDOFF.md`（本書）

### 変更
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
