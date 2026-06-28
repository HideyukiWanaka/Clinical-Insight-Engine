# CIE Platform — Claude Code Implementation Prompts
# Phase 9: Streamlit UI
# File: prompts/phase9_ui.md
# Version: 1.1.0

---

## PROMPT 9-0: ブランチ作成

```
# Phase 8 が main に merge 済みであることを確認してから実行してください。
git checkout main
git pull origin main
git checkout -b feature/phase-9-ui
```

---

## PROMPT 9-1: UIアプリ基盤とレイアウト

```
CIE PlatformのStreamlit UIの基盤を実装してください。
3ペイン構成とステータスバーを実装します。

### 読み込むべき仕様ファイル
- architecture/ui-model.md (全体レイアウト構成)
- spec/ui/ui-principles.md (UP-001〜UP-010)
- spec/ui/component-library.md (StatusBar, AgentActivityFeed)

### 前提
- Phase 1〜8の実装が完了しています
- streamlit >= 1.30 がインストール済みです

### 作成するもの

1. `cie/ui/app.py` を作成してください：

```python
# メインアプリエントリポイント。
# 実行コマンド: streamlit run cie/ui/app.py
#
# ページ設定:
#   - page_title: "CIE Platform"
#   - layout: "wide"
#   - initial_sidebar_state: "expanded"
#
# カラーパレット（ui-model.md Section 4 準拠）:
# CSS変数を st.markdown で inject する:
#   --cie-blue-700: #1D4E89
#   --cie-blue-500: #2E74C0
#   --cie-blue-100: #DBEAFE
#   --cie-gray-900: #111827
#   --cie-gray-600: #4B5563
#   --cie-gray-200: #E5E7EB
#   --cie-gray-50:  #F9FAFB
#   --cie-success:  #059669
#   --cie-warning:  #D97706
#   --cie-critical: #DC2626
#   --cie-approval: #7C3AED
#   --cie-ai-teal:  #0D9488
#
# レイアウト構成:
#   - ステータスバー: st.columns([8,1,1,1]) でプロジェクト名・接続状態・セキュリティ
#   - 3ペイン: st.columns([1, 3, 1.3]) で左・中央・右
#   - 左ペイン: st.session_state["current_screen"] に応じてナビゲーション表示
#   - 中央ペイン: render_main_content() で画面をルーティング
#   - 右ペイン: render_right_pane() で常時コンテキスト情報表示
#
# セッション状態の初期化:
#   st.session_state に以下を初期化（存在しない場合のみ）:
#   - current_screen: "dashboard"  # dashboard | intent | workflow | quality
#                                  # analysis | results | audit
#   - execution_id: None
#   - workflow_state: None
#   - agent_activity_log: []       # AgentActivityFeedのエントリリスト
#   - approval_pending: False
#   - connection_status: "online"  # online | offline | checking
#   - security_events: []
```

2. `cie/ui/components/status_bar.py` を作成してください：

```python
# def render_status_bar(
#     project_name: str | None,
#     execution_id: str | None,
#     connection_status: str,
#     security_events: list[dict],
#     workflow_state: str | None
# ) -> None:
#
# Streamlitでの実装:
#   - 1行のカラムレイアウト（幅比率: [4,2,1,1]）
#   - 左: "CIE Platform  |  {project_name}"
#   - 中: "実行ID: {execution_id[:8]}..." (Noneなら非表示)
#   - 右端1: 接続状態インジケーター
#     online  → 🟢 オンライン (st.success風)
#     offline → ⚫ オフライン (st.warning風)
#     checking → 🔄 確認中
#   - 右端2: セキュリティアイコン
#     BREACHイベントあり → 🔴 （赤テキスト）
#     CRITICALイベントあり → 🟠
#     問題なし → 🔒
#   - UP-004準拠: BREACHの場合は全画面オーバーレイを表示
#     st.error() で全幅の赤ブロックを表示
#     "🚨 セキュリティ違反が検出されました" + エラーコード + タイムスタンプ
```

3. `cie/ui/components/right_pane.py` を作成してください：

```python
# def render_right_pane(
#     workflow_state: str | None,
#     agent_activity_log: list[dict],
#     approval_pending: bool,
#     approval_context: dict | None
# ) -> None:
#
# 表示要素（上から順）:
#
# 1. 承認パネル（approval_pending=Trueの場合のみ・折りたたみ不可）
#    UP-002準拠:
#    st.markdown("### 🟣 HUMAN APPROVAL REQUIRED")
#    st.warning(approval_context["title"])
#    if approval_context.get("is_irreversible"):
#        st.error("⚠️ この操作は取り消せません")
#    confirmed = st.checkbox("内容を確認しました")
#    col1, col2 = st.columns(2)
#    col2.button("承認して実行",
#                disabled=not confirmed,
#                type="primary",
#                key="approve_btn")
#    col1.button("キャンセル", key="cancel_btn")
#
# 2. Agent アクティビティフィード
#    st.subheader("Agent アクティビティ")
#    各エントリを以下の形式で表示:
#      "[HH:MM:SS]  {agent_id:<12}  {action:<20}  {summary}"
#    フォント: monospace (st.code 風だがインタラクティブなし)
#    WARNING行: st.warning()
#    CRITICAL/BREACH行: st.error()
#    最新50件のみ表示（古いものは切り捨て）
```

4. `tests/unit/test_ui_components.py` を作成してください：

```python
# Streamlitのテストはst.testingを使用（streamlit >= 1.30）:
# from streamlit.testing.v1 import AppTest
#
# - test_status_bar_online_indicator: connection_status="online"で🟢表示
# - test_status_bar_breach_overlay: BREACH eventで赤ブロック表示
# - test_approval_panel_button_disabled: checkbox未チェック時にボタンが無効
# - test_approval_panel_button_enabled: checkbox済みでボタンが有効
# - test_activity_feed_max_50: 51件のログで50件のみ表示
```

### 制約事項
- ビジネスロジックをUIコンポーネントに含めないこと
  （component-library.md: "Presentation Layer contains no business logic"）
- st.session_stateの直接操作はapp.pyのみに限定し、
  コンポーネント関数は戻り値でUIイベントを通知すること
- 承認パネルはapproval_pending=Trueの間、st.stop()等で折りたたみを防止しないこと
  （Streamlitの仕様上、再レンダリングで状態を保持する設計にする）
```

---

## PROMPT 9-2: SCR-01 ダッシュボードとSCR-02 意図入力画面

```
CIE PlatformのSCR-01（プロジェクトダッシュボード）と
SCR-02（研究意図入力画面）を実装してください。

### 読み込むべき仕様ファイル
- spec/ui/screen-specifications.md (SCR-01, SCR-02 セクション)
- spec/ui/interaction-flow.md (主要ジャーニー: 新規解析の完遂 / Section 2)

### 前提
- PROMPT 9-1の app.py, status_bar.py, right_pane.py が存在します

### 作成するもの

1. `cie/ui/screens/dashboard.py` を作成してください：

```python
# def render_dashboard(projects: list[dict]) -> dict | None:
#   # projects: WorkflowInstanceのリスト（DBから取得済み）
#   # 戻り値: 選択されたproject dict、または None（新規作成の場合は別途判定）
#
#   # 表示要素:
#   # 1. ヘッダ: "CIE Platform" + "＋ 新規プロジェクト" ボタン
#   # 2. 承認待ちバナー（waiting_for_human状態のプロジェクトがある場合）
#   #    st.warning(f"承認待ちのプロジェクトが {count} 件あります")
#   # 3. ProjectCardグリッド（st.columns(3)）
#   #
#   # ProjectCardの実装:
#   #   with st.container(border=True):
#   #     左ボーダーはcssで模擬（st.markdownでstyleを付与）
#   #     表示項目: プロジェクト名、状態バッジ、最終更新、承認待ちカウント
#   #     クリックすれば該当プロジェクトを返す
#   #
#   # 状態バッジのスタイル:
#   #   completed        → ✅ 完了      (st.success風テキスト)
#   #   running          → ⟳ 実行中    (st.info風)
#   #   waiting_for_human → 🟣 承認待ち (紫テキスト)
#   #   failed           → ❌ 失敗      (st.error風)
#   #   draft            → ○ 準備中    (グレーテキスト)
#   #
#   # waiting_for_humanプロジェクトをグリッド先頭に並べること
```

2. `cie/ui/screens/intent_entry.py` を作成してください：

```python
# def render_intent_entry(
#     on_submit: Callable[[str, bytes | None], None]
# ) -> None:
#   # on_submit: (prompt_text, csv_bytes) -> None
#
#   # 表示要素（screen-specifications.md SCR-02準拠）:
#   # 1. テキストエリア（200px以上、自動拡張）
#   #    placeholder:
#   #    "研究目的を自然な言葉で記述してください。\n\n"
#   #    "例）「治療群Aと対照群Bの術後90日死亡率を比較したい」\n"
#   #    "    「BMIと血圧の相関を調べたい」\n"
#   #    "    「介入前後の痛みスコアを同一患者で比較したい」"
#   #    height=200
#
#   # 2. データセットアップロード
#   #    st.file_uploader("データセット（CSV/TSV/XLSX）",
#   #                     type=["csv","tsv","xlsx"],
#   #                     key="dataset_upload")
#   #    アップロード後: ファイル名・推定行数・列数を表示
#   #    PIIリスク注記をst.info()で表示:
#   #    "🔒 このデータは安全に処理されます。raw dataはAIに送信されません。"
#
#   # 3. Intent解析結果プレビュー（右ペインに表示するためsession_stateに格納）
#   #    テキスト入力後500ms（Streamlitでは入力完了を検知してPlanner呼び出し）
#   #    実際の実装: st.button("研究意図を解析") で明示的にトリガー
#
#   # 4. 「解析を開始する →」ボタン
#   #    intent_object が未確認の場合は disabled=True
#   #    UP-002準拠: クリック時に承認パネルをsession_stateに設定して
#   #               right_pane.pyの承認フローへ

# def render_intent_preview(intent_object: dict) -> None:
#   # 右ペインに表示するintent_objectプレビュー
#   # 各フィールドをst.metric()またはst.json()で表示
#   # confidence_scoreの表示:
#   #   >= 0.8: 🟢 {score}
#   #   0.6〜0.79: 🟡 {score} "確認推奨"
#   #   < 0.6: 🔴 "人間による確認が必要です"
#   # paired=null のフィールド: 🟡 "確認が必要" ラベルで黄色ハイライト
```

3. `cie/ui/screens/workflow_view.py` を作成してください：

```python
# def render_workflow_view(
#     workflow_definition: dict,
#     node_statuses: dict[str, str],   # node_id -> WorkflowState
#     node_outputs: dict[str, dict]    # node_id -> output_payload
# ) -> str | None:
#   # 戻り値: クリックされたnode_id（詳細表示用）、なければNone
#
#   # ワークフローDAGを水平ステップリストで表示:
#   # st.columns(len(nodes)) で各ノードを1列に
#   #
#   # 各ノードの表示（WorkflowStepCard準拠）:
#   # 状態アイコン:
#   #   pending          → ○
#   #   running          → ⟳ (テキストで代用)
#   #   completed        → ✅
#   #   failed           → ❌
#   #   waiting_for_human → 🟣
#   #   retrying         → 🔄
#   #
#   # クリック時: st.button(node_id) でクリックを検知し node_id を返す
#   #
#   # ノード詳細（クリック時に st.expander で展開）:
#   #   入力ペイロード: st.json(node_inputs)
#   #   出力ペイロード: st.json(node_outputs[node_id])  (完了ノードのみ)
#   #   agent_id, node_type を表示
```

### 制約事項
- ビジネスロジック（Planner呼び出し等）はUIコンポーネントに含めないこと
  （on_submit コールバックで呼び出し元に委譲）
- st.session_stateの直接書き込みはapp.py内のみで行うこと
- スクリーンの実装はspec/ui/screen-specifications.md の各SCR定義と一致すること
```

---

## PROMPT 9-3: SCR-04〜07 品質・解析・結果・監査画面

```
CIE PlatformのSCR-04〜SCR-07を実装してください。

### 読み込むべき仕様ファイル
- spec/ui/screen-specifications.md (SCR-04〜SCR-07 セクション)
- spec/ui/ui-principles.md (UP-003 Progressive Disclosure, UP-004 Security)

### 前提
- PROMPT 9-1〜9-2の全UIコンポーネントが存在します

### 作成するもの

1. `cie/ui/screens/quality_review.py` を作成してください：

```python
# def render_quality_review(
#     quality_report: dict,
#     column_alias_map: dict | None    # Noneの場合はマスク表示
# ) -> dict:
#   # 戻り値: {"proceed": bool, "acknowledged_findings": list[str]}
#
#   # 表示要素（SCR-04準拠）:
#   # 1. quality_gate_passed の表示
#   #    True:  st.success("✅ データ品質チェック: 通過")
#   #    False: st.error("❌ データ品質チェック: 未通過")
#
#   # 2. Critical Issues（デフォルト展開）
#   #    for finding in quality_report["critical_findings"]:
#   #      with st.expander(f"❌ {finding['affected_component']}: {finding['description'][:50]}", expanded=True):
#   #        st.write(finding['description'])
#   #        col1, col2 = st.columns(2)
#   #        col1.button("解消方法を確認")
#   #        if col2.button("理解した上で進む", key=f"ack_{finding['finding_id']}"):
#   #          → 確認ダイアログ（st.dialog または st.warning + checkbox）
#
#   # 3. MissingValueChart（st.bar_chart 使用）
#   #    X軸: 変数名(var_n)、Y軸: 欠損率(%)
#   #    20%ラインをst.markdown で赤点線注記
#
#   # 4. 右ペイン用: 列名マッピングパネル（UP-004準拠）
#   #    column_alias_map が None: "var_1: ---" 形式でマスク表示
#   #    Security Agentが復元済み: 元の列名を表示
#   #    PIIパネルスタイル: st.container(border=True) + 橙色のst.info()
#
#   # 5. 「次へ進む」ボタン
#   #    critical findingが未解消の場合: disabled=True
```

2. `cie/ui/screens/analysis_config.py` を作成してください：

```python
# def render_analysis_config(
#     analysis_plan: dict,
#     assumption_report: dict | None
# ) -> dict:
#   # 戻り値: {"approved": bool, "override_method": str | None, "override_reason": str | None}
#
#   # 表示要素（SCR-05準拠）:
#   # 1. 選択された統計手法カード
#   #    with st.container(border=True):
#   #      method_name_ja: method_usedを日本語表示にマッピング
#   #        例: "welch_t_test" -> "Welch t検定"
#   #      st.write(method_justification)
#   #      「変更する」expander
#   #
#   # 2. 仮定チェックリスト（REDCap風リスト）
#   #    if assumption_report:
#   #      for check in assumption_report checks:
#   #        icon = "✅" if check.passed else "⚠️"
#   #        st.write(f"{icon} {check.name}: {check.result_summary}")
#
#   # 3. 右ペインへの引き渡し（session_stateで承認パネルをセット）
#   #    UP-002: "Rスクリプトを実行します。この操作は取り消せません。"
#   #    is_irreversible=True
```

3. `cie/ui/screens/results.py` を作成してください：

```python
# def render_results(
#     execution_result: dict,
#     figures: list[dict],
#     manuscript_sections: dict,
#     review_result: dict
# ) -> dict:
#   # 戻り値: {"export_approved": bool, "export_type": str}
#
#   # タブ構成: st.tabs(["📊 結果", "🖼 図表", "📝 原稿"])
#
#   # 結果タブ:
#   #   主要数値をst.metric()で表示
#   #   数値にトレーサビリティポップオーバー（st.popover使用）:
#   #     st.popover(str(p_value)):
#   #       "出典: execution_result.primary_result.p_value"
#   #       "実行ID: {execution_id}"
#
#   # 図表タブ:
#   #   figures リストの各ファイルパスから st.image() または st.pyplot() で表示
#
#   # 原稿タブ:
#   #   各セクションをst.text_area()で編集可能に表示
#   #   AI生成テキストには "🤖 AI生成" ラベル + ティール色のst.info()背景
#   #   unresolved_itemsをst.warning()でコメントとして挿入
#   #
#   # エクスポートパネル（右ペインに表示するため戻り値で通知）:
#   #   reviewer_score = review_result.get("quality_score", 0)
#   #   export_disabled = reviewer_score < 90
#   #   st.metric("Reviewer Score", f"{reviewer_score}/100")
#   #   st.button("エクスポートを承認する", disabled=export_disabled)
```

4. `cie/ui/screens/audit_log.py` を作成してください：

```python
# def render_audit_log(
#     audit_events: list[dict],
#     workflow_id: str | None
# ) -> None:
#   # 表示要素（SCR-07準拠）:
#   # 1. フィルタ（左カラム）
#   #    agent_filter = st.multiselect("Agent", [...])
#   #    severity_filter = st.multiselect("重要度", ["INFO","WARNING","CRITICAL","BREACH"])
#
#   # 2. タイムラインテーブル（中央）
#   #    st.dataframe() でリスト表示
#   #    列: timestamp, agent_id, action, status, event_severity
#   #    クリックで右ペインにJSONを表示（st.session_stateで連動）
#   #    WARNING行: 橙背景 (pandas Stylerで設定)
#   #    CRITICAL/BREACH行: 赤背景
#
#   # 3. CSV出力ボタン
#   #    payload_hash のみ含むCSVを st.download_button() でダウンロード
#   #    ファイル名: f"audit_log_{execution_id[:8]}_{date}.csv"
```

### 制約事項
- UP-003: Critical Issueは常にexpanded=True、warningはexpanded=False
- UP-004: PII関連パネルは必ずst.container(border=True)に橙色注記を付けること
- 監査CSVにpayload本文を含めないこと（payload_hashのみ）
- SCR-06のエクスポートボタンはreviewer_score < 90の場合にdisabled=Trueにすること
```

---

## PROMPT 9-X: Phase 9 完了処理

```
Phase 9 の全実装（PROMPT 9-1〜9-4）が完了し、テストがすべてパスしたことを
確認してから、以下の手順でブランチを main へ統合してください。

### テスト確認
pytest tests/unit/test_ui_components.py -v

### コミット
git add -A
git commit -m "feat(phase9): streamlit UI — 3-pane layout, status bar, history, export"

### main へ merge
git checkout main
git merge --no-ff feature/phase-9-ui \
  -m "merge: phase-9-ui into main"

### 次フェーズのブランチを main から作成
git checkout -b feature/phase-10-integration
```
