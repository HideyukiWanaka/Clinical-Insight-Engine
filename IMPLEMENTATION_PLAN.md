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

### ⬜ フェーズ2: Visualization 実生成
- LLM＋reference_library 注入、ナレッジ（ggplot2_best_practices/chart_selection_guide）参照
- 実行可能な ggplot2 R を生成 → runtime実行 → PNG出力、`figure_manifest` に実パス
- 検証: ハーネスで実PNG生成／リスク: 中

### ⬜ フェーズ3: Reporting 実生成＋標準フォーマット
- LLM＋ナレッジ（manuscript_structure/result_interpretation/reporting_checklists）で実原稿生成（数値は statistical_results 由来のみ）
- `reporting_checklist_id`（CONSORT/STROBE…）＋`target_journal_style`（APA/AMA/Vancouver）反映。未指定は study_design から推論
- 検証: ハーネスで APA＋STROBE 原稿／リスク: 中

### ⬜ フェーズ4: Skill適用層（「Skillで賢くなる」核心）
- statistics/visualization/reporting に SkillLoader 注入
- `skills/user/ > skills/core/` の優先で SKILL.md 指示を生成プロンプトへ合成
- ユーザー独自フォーマット/手法Skillが生成に効くことを確認／リスク: 中

### ⬜ フェーズ5: フォーマット選択UI
- UIに「チェックリスト＋雑誌スタイル＋登録済みユーザーSkill」の選択、reporting へ伝搬／リスク: 低

### ⬜ フェーズ6（A）: オーケストレーション完成＋フルDAG
- decisionノードのルーティング（rules評価、正規性分岐）
- evaluationノード＝評価エージェント新規（cie/evaluation/* をラップ）
- アプリの承認/再開（security_review 停止→resume_workflow）
- 残る下流キー整合、フルDAGをE2E完走／リスク: 高

### ⬜ フェーズ7（C）: 継続解析ループ（AIアドバイザー核心）
- statistics/visualization が前回 statistical_results＋前回スクリプトを受理
- 継続プロンプト（前回結果を踏まえ次の解析を提案・生成）
- 対話UI：結果の下で追加解析を相談、解析履歴を保持／リスク: 中

### ⬜ フェーズ8: Skill自己改善ループ
- メタSkillのpython実装（skill-evaluator/proposer）
- reviewer 発見・評価スコア → Skill改善提案 → **必ず人間承認**（ADR-0002）→ SkillLifecycle で version更新・旧版archive
- 更新後に出力/スコア改善を確認／リスク: 中〜高

## 全フェーズ共通の安全策
- 各フェーズ末で `python3 -m pytest tests/unit/`（現状600件パス／既存失敗15件はDB系の元からの失敗で不変）
- ADR絶対ルール厳守：Planner に workflow_id を出さない／全Skill更新に人間承認／`inject_raw_data_rows=False`／Capabilityトークンは try/finally で失効
- 捏造防止：数値は必ず実R実行の result.json 由来のみ
