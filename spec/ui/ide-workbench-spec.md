# CIE Platform — IDEワークベンチ UI仕様（RStudio型）
# File: spec/ui/ide-workbench-spec.md
# Version: 1.0.0
# Governs: frontend/ (新規, React + TypeScript + Monaco)
# Basis: ADR-0005 原則1 / spec/api/rest-api-contract.md
# Supersedes (体験面): 現行 Streamlit SCR-01〜07 のうち解析フロー部分

---

## 1. 目的

「AIと対話 → 提案コードを確認/編集 → その場で実行 → 結果・図・変数・ファイルを確認 →
報告書フォーマットに出力」を**1画面**で完結させる。参照デザインは提供された
Ratudio AI モックアップ（4ペイン構成、「スクリプトへ挿入」導線）。

既存の UI原則（`spec/ui/ui-principles.md` UP-001〜010）は思想として引き継ぐ:
意図中心、人間が決定、セキュリティの可視化、AI生成物の明示。

---

## 2. 全体レイアウト（4ペイン + ヘッダ）

```
┌─────────────────────────────────────────────────────────────────┐
│ ヘッダ: プロジェクト名 / メニュー / 接続状態 / セキュリティ状態    │
├───────────────┬─────────────────────────────┬───────────────────┤
│ 左: AIチャット │ 中上: コードエディタ(Monaco)  │ 右上: ファイルツリー│
│  (会話履歴+   │       Code / Result タブ      │  (workspace配下)   │
│   コード候補+ ├─────────────────────────────┤───────────────────┤
│   挿入/実行)  │ 中下: R コンソール + プロット  │ 右下: Workspace/Data│
│               │       Console / Output タブ   │  + Output & Format │
└───────────────┴─────────────────────────────┴───────────────────┘
```

- ペインは**リサイズ可能**（`react-resizable-panels` 等）。
- テーマはライト/ダーク両対応。

---

## 3. 各ペインの仕様

### 3.1 左: AIチャット
- ネイティブなチャットUI（吹き出し＋入力欄）。会話履歴を保持。
- **初回入力** → `POST /api/intent`（Planner）。曖昧なら clarification をチャットで提示。
- **意図確定後** → `POST /api/propose`（Statistics 会話モード）。応答は:
  - `explanation_markdown` を吹き出しに表示。
  - 各 `code_candidates` を Monaco 風のコードブロックで表示し、各ブロックに
    **「✓ スクリプトへ挿入」**（中央エディタのカーソル位置に挿入、実行しない）と
    **「▶ 実行」**（挿入せず即 `POST /api/run`）の2ボタン。
- **2回目以降** → `continuation_query` として `POST /api/propose`。
- 生成失敗時は `r_script_provenance.reason` を必ず吹き出しに表示（例:「APIキー未設定」）。

### 3.2 中上: コードエディタ（Monaco）
- Rシンタックスハイライト・行番号・カーソル・複数行編集。
- 「スクリプトへ挿入」はカーソル位置にテキスト挿入。
- ツールバー: **「▶ Run」**（エディタ全体を `POST /api/run`）、「選択範囲を実行」、保存。
- タブ: **Code**（編集）/ **Result**（直近実行の統計結果を整形表示）。

### 3.3 中下: Rコンソール + プロット
- **Console** タブ: `WS /ws/console` のストリームを逐次表示（サニタイズ済み）。
  入力行（`>`）＋出力を時系列で。
- **Output** タブ: 生成された図（PNG）を表示。`POST /api/visualize` の `figures[].path`。

### 3.4 右上: ファイルツリー（Project / Files）
- `GET /api/files` の一覧をツリー表示（dataset.csv, *.R, output/ 等）。
- クリックで `GET /api/files/content` を呼びプレビュー（.R/.json→コード, .png→画像,
  .csv→先頭数行）。ダウンロードボタン。**読み取り専用**（削除UIなし）。

### 3.5 右下: Workspace/Data ＋ Output & Format
- **Workspace/Data**: 直近実行後のR変数一覧（名前・型・要約）。
  `POST /api/run` の `workspace_summary` を表示（例: `iris (150 obs, 5 variables)`,
  `p (ggplot object)`）。永続ワークスペース（.RData）の可視化を兼ねる。
- **Output & Format**: 既存 `render_format_selection` 相当（報告チェックリスト/雑誌スタイル/
  ユーザーSkill）＋「原稿に変換」ボタン → `POST /api/report`。生成原稿はコピー可能な形で表示。

---

## 4. 主要インタラクション（画像準拠）

1. チャットで「iris の種類別ヒストグラムを作って」と入力。
2. AIが説明＋ggplot2コード候補を提示。
3. 利用者が **「✓ スクリプトへ挿入」** → 中央エディタに挿入。
4. **「▶ Run」** → コンソールに実行ログがストリーム、Outputに図、Workspaceに `p` 変数。
5. 追加で「タイトルを変えて」→ チャットが `continuation_query` で新コードを提案。
6. Output & Format で PDF/Academic Report を選び「原稿に変換」。

---

## 5. セキュリティ表示（UP-004 継承）
- 患者データは「解析データ」入口からのみ投入し、フロントには**匿名化後のメタデータ**のみ返る
  （生データ行はAPIも返さない）。
- 参考資料の入口は別ペイン/別モーダルとして明確に分離（ADR-0005 原則4）。
- PII検出・セキュリティイベントはヘッダのインジケータで可視化。

---

## 6. 非対象（この仕様の範囲外）
- デスクトップ枠（Tauri）は spec 上「同一フロントを包む」とのみ規定。詳細は Phase 7。
- 常駐Rプロセスは採用しない（永続化は .RData ファイル方式、ADR-0005 原則2）。
