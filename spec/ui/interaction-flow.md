# Interaction Flow
# File: spec/ui/interaction-flow.md
# Version: 1.0.0
# Status: Draft
# Parent: architecture/ui-model.md
# Related: spec/ui/screen-specifications.md, spec/workflow.yaml

---

## 目的

本文書はCIE Platformにおけるユーザーの操作フローと画面遷移を定義する。
主要ジャーニー・エラーフロー・人間承認フローを網羅する。

遷移条件はspec/workflow.yamlのワークフロー定義と整合している。

---

## 1. 主要ジャーニー: 新規解析の完遂

```
[ユーザー操作]                     [システム処理]                 [画面]
      │                                  │                          │
      ▼                                  │                          │
アプリ起動                               │                   SCR-01 Dashboard
      │                                  │
「+ 新規プロジェクト」クリック           │
      │                                  │
      ▼                                  │                   SCR-02 Intent Entry
研究目的を入力                           │
      │                             (500ms debounce)
      │                        ─────────────────────▶
      │                             Planner Agent実行
      │                        ◀─────────────────────
      │                          intent_object生成
      │
intent_objectを確認・修正（右ペイン）
      │
「解析を開始する」クリック
      │
      ├─ intent_objectに未確認項目あり
      │       → 「未確認の項目があります」警告
      │         → 項目を確認・解消
      │
      └─ 全項目確認済み
              ↓
        [ApprovalPanel表示]
        「この解釈で解析を開始します」
              │
              │（承認）
              ▼
      ワークフロー開始              SCR-03 Workflow View
              │                    │
              │                    │ intake ⟳ → ✓
              │                    │ validate_dataset ⟳
              │                    │
              │           quality_gate_passed = false?
              │                    ├─ YES → SCR-04 Quality Review
              │                    │          (Critical Issue解消 or 承認)
              │                    │          → ワークフロー再開
              │                    │
              │                    └─ NO (passed=true)
              │                              │
              │                              ↓
              │                    select_analysis → assumption_check
              │                              │
              │                    security_review ノードに到達
              │                              │
              │                    [ApprovalPanel: 実行承認]   SCR-05 Analysis
              │                              │
              │                              │（承認）
              │                              ▼
              │                    runtime_execution ⟳
              │                    visualization ⟳
              │                    reporting ⟳
              │                    reviewer ⟳
              │                    evaluation ⟳
              │                              │
              │                    evaluation_score >= 90?
              │                              ├─ NO → SCR-06 Results
              │                              │        (reviewerスコア不足)
              │                              │        エクスポートボタン非活性
              │                              │
              │                              └─ YES
              │                                        │
              ▼                                        ▼
        SCR-06 Results & Report              エクスポート承認
              │                             [ApprovalPanel]
              │（エクスポート承認）
              ▼
        エクスポート完了
              │
        SCR-07 Audit（随時参照可能）
```

---

## 2. 人間承認フロー詳細

CIEには3種類の人間承認ポイントが存在する。
すべてspec/workflow.yamlの`human_approval.required`と対応する。

### 承認フロー共通手順

```
①  承認ノードに到達
      ↓
②  ワークフロー状態 → waiting_for_human
   右ペイン: ApprovalPanel表示（折りたたみ不可）
   左ペインのステップ: 🟣 waiting_for_human バッジ
      ↓
③  ユーザーがコンテンツを確認
   （画面によってはSCR-04/05の詳細情報を参照）
      ↓
④  チェックボックス: 「内容を確認しました」にチェック
   → 承認ボタンが活性化
      ↓
⑤  「承認して実行」クリック
      ↓
⑥  ConfirmDialog表示
   「[操作内容]を実行します。よろしいですか？」
      ↓
⑦  「実行する」クリック
      ↓
⑧  承認イベントを監査ログに記録
   ワークフロー状態 → running
   ApprovalPanel → 承認済み表示に変化
```

### 承認ポイント別の詳細

| 承認ポイント | 画面 | 承認後の処理 |
|------------|------|------------|
| intent確認 | SCR-02 | ワークフロー開始 |
| Critical Issue承認 | SCR-04 | quality_gate通過・次ステップへ |
| security_review（実行承認） | SCR-05 | Rスクリプト実行開始 |
| エクスポート承認 | SCR-06 | ファイル生成・転送開始 |

### 承認キャンセル時の動作

```
「キャンセル」クリック
      ↓
ワークフロー状態: waiting_for_human のまま維持
ApprovalPanel: そのまま表示
右ペインのAgentActivityFeed: 「承認待ち: [タイムスタンプ]から継続中」を表示

注: キャンセルはワークフローを中断しない。
    ユーザーはいつでも戻って承認できる。
    ワークフローを明示的に中断する場合は「実行を中止」ボタンを使用する。
```

---

## 3. エラーフロー

### 3.1 RECOVERABLE エラー（自動リトライ対象）

spec/workflow.yamlの`failure_policy.recoverable`に対応:
`runtime_timeout` | `temporary_io_failure` | `runtime_busy`

```
エラー発生（例: runtime_timeout）
      ↓
ワークフロー状態 → retrying
SCR-03のステップカード: ↻ リトライ中（試行 2/3）
右ペイン AgentActivityFeed:
  「[タイムスタンプ]  runtime  retrying  attempt=2/3 (runtime_timeout)」
      ↓
リトライ成功 → 通常フローへ復帰
      │
      └─ 3回失敗 → NON-RECOVERABLE エラーフローへ
```

### 3.2 NON-RECOVERABLE エラー

spec/workflow.yamlの`failure_policy.non_recoverable`に対応:
`schema_validation_failure` | `permission_denied` | `security_violation` | `corrupted_dataset`

```
NON-RECOVERABLE エラー発生
      ↓
ワークフロー状態 → failed
SCR-03の該当ステップカード: ✕ 失敗（赤）
中央ペインに エラー詳細パネル展開:

┌────────────────────────────────────────────────────┐
│ ❌  [エラー種別の日本語説明]                       │
│                                                    │
│  [何が起きたかの説明]                             │
│                                                    │
│  対処方法:                                         │
│  ① [具体的なステップ]                             │
│                                                    │
│  ▼ 技術的詳細                                     │
│    エラーコード: SCHEMA_VALIDATION_FAILED          │
│    Agent: statistics                               │
│    タイムスタンプ: 2025-06-27T14:32:31Z           │
│                                                    │
│  [監査ログを表示]      [ワークフローを再開する]    │
└────────────────────────────────────────────────────┘

注: 「ワークフローを再開する」は問題を解決した後にのみ有効。
    問題が未解決のまま再開を試みても同じ箇所で失敗する旨をツールチップで説明。
```

### 3.3 SECURITY BREACH

```
BREACHイベント検出（security.yaml参照）
      ↓
全アクティブトークンを即時失効
ワークフロー状態 → failed
      ↓
全画面オーバーレイ表示（UP-004のBREACH仕様）:

┌─────────────────────────────────────────────────────────────┐
│  [赤背景 rgba(220,38,38,0.95)]                              │
│                                                             │
│  🚨  セキュリティ違反が検出されました                      │
│                                                             │
│  実行中のワークフローを中断しました。                       │
│  監査ログを確認し、管理者に報告してください。               │
│                                                             │
│  エラーコード: [BREACH_EVENT_CODE]                         │
│  発生時刻: 2025-06-27T14:32:31Z                            │
│                                                             │
│  [監査ログを表示]          [アプリを再起動]                 │
└─────────────────────────────────────────────────────────────┘

すべての操作をブロック（上記2ボタン以外）。
```

---

## 4. paired設計の検出フロー

intent_object.pairedの判定に関するUIフロー。

```
ユーザーが研究目的を入力:
「介入前後の痛みスコアを同一患者で比較したい」
      ↓
Planner Agent (PL-004) が paired=true を推定
subject_id_varを dataset_structural_metadata から探索
      │
      ├─ subject_id_var 特定できた場合
      │       右ペイン:
      │         paired: true ✓（緑）
      │         subject_id_var: var_5 ✓（緑）
      │         → 「同一患者の繰り返し測定と解釈しました」
      │
      └─ subject_id_var 特定できなかった場合（PL-005発動）
              右ペイン:
                paired: true ⚠（黄）
                subject_id_var: 未特定 ⚠
                → 「患者IDの列を特定できませんでした」
                [患者IDの列を指定する]ボタン
                      ↓
                ColumnSelectorDropdown表示
                （dataset_structural_metadataの列一覧）
                ユーザーが列を選択
                      ↓
                subject_id_var = "var_X" に確定
```

---

## 5. オフライン↔オンライン切替フロー

```
オンライン中 → オフライン検出
      ↓
ステータスバー: ● オフライン（グレー）にアニメーション変化
トースト通知（右下・4秒）:
  「オフラインになりました。ローカル機能のみ利用可能です。」
      ↓
外部依存ボタンの非活性化:
  - Google Driveエクスポートボタン: グレーアウト
  - ツールチップ: 「この機能はオンライン接続が必要です」
      ↓
（ローカル作業継続）
      ↓
オンライン復帰検出
      ↓
ステータスバー: ● オンライン（緑）にアニメーション変化
      ↓
エクスポートキューに保留タスクがある場合:
  トースト通知（右下・手動消去):
    「オンラインに復帰しました。
     保留中のエクスポート（1件）を処理しますか？
     [処理する] [スキップ]」
```

---

## 6. Progressive Disclosureのインタラクション

各コンポーネントの展開・折りたたみ操作の標準化。

### 展開トリガー

| トリガー | 動作 |
|---------|------|
| コンポーネント右上の「▼ 詳細を表示」クリック | レベル2コンテンツを展開（アニメーション200ms） |
| `Ctrl+Shift+D` | 全コンポーネントをレベル3まで一括展開 |
| Critical Issue検出 | 該当コンポーネントを自動展開（ユーザー操作不要） |
| ステップカードクリック | ステップ詳細モーダルを開く |

### 折りたたみトリガー

| トリガー | 動作 |
|---------|------|
| 「▲ 折りたたむ」クリック | レベル1に戻す |
| `Escape` | モーダルを閉じる |
| `Ctrl+B` | 左ペイン折りたたみ（レベル関係なし） |

### 展開状態の永続化

```typescript
// セッションストレージで展開状態を管理
const expansionState = {
  stepDetails: { [nodeId: string]: boolean },
  qualityIssues: { [findingId: string]: boolean },
  detailMode: boolean,   // Ctrl+Shift+D
};
// ページリロード後もセッション中は維持
// セッション終了（ブラウザ閉鎖）でリセット
```

---

## 7. キーボードナビゲーション標準

全画面共通のキーボード操作仕様。

```
Tab              : 次のインタラクティブ要素へフォーカス
Shift+Tab        : 前のインタラクティブ要素へフォーカス
Enter / Space    : フォーカスされたボタン/チェックボックスを実行
Escape           : モーダル・ドロップダウン・トーストを閉じる
Ctrl+B           : 左ペイン折りたたみトグル
Ctrl+P           : コマンドパレットを開く
Ctrl+Enter       : 現在のステップを実行（SCR-02: 解析を開始する）
Ctrl+Shift+D     : 詳細モード切替
Ctrl+S           : 手動保存
Arrow Keys       : ワークフローDAGのステップ間をナビゲート（SCR-03）
```

### モーダルのフォーカストラップ

モーダルダイアログが開いている間:
- Tabキーのフォーカスをモーダル内のみに制限する
- モーダル外の要素は`aria-hidden="true"`に設定する
- Escapeキーでモーダルを閉じ、トリガー要素にフォーカスを返す

**例外:** BREACHオーバーレイはEscapeで閉じない（UP-004のBREACH規則）
