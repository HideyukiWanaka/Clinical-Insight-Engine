# CIE 再設計 — Phase 3: シームレス連携（挿入/実行）＋Rコンソール
# File: prompts/redesign/phase3_seamless_editor.md
# Version: 1.0.0

---

## PROMPT R3-0: ブランチ作成

```
git checkout main && git pull origin main
git checkout -b feature/redesign-phase-3-seamless
```

---

## PROMPT R3-1: 「スクリプトへ挿入」「実行」とコンソールストリーム

```
画像の核心挙動（挿入→実行→結果/図/変数）を実装します。目標③の中心。

### 読み込むべき仕様ファイル
- spec/ui/ide-workbench-spec.md（§3.1〜3.3, §4 主要インタラクション）
- spec/api/rest-api-contract.md（§3.3 /api/run, §4 /ws/console）

### 実装範囲
- ✅ チャットの各コード候補に2ボタン:
     「✓ スクリプトへ挿入」= Monacoのカーソル位置へ挿入（実行しない）、
     「▶ 実行」= 挿入せず即 POST /api/run。
- ✅ エディタツールバーの「▶ Run」= エディタ全体を POST /api/run。「選択範囲を実行」。
- ✅ WS /ws/console 購読: 実行ログを Console タブに逐次表示（サニタイズ済み）。
- ✅ 実行結果の反映: 統計値→Result タブ、図→Output タブ（POST /api/visualize 連動）、
     生成変数→Workspace/Data（Phase 4の summary を先取りで表示できるなら表示）。
- ✅ 失敗時: execution_result.detail / statistical_results_reason / r_script_provenance.reason
     を Console と結果ペインに必ず表示（無言失敗の恒久対策）。
- ❌ .RData 永続化そのものは Phase 4（ここでは単発実行でよい）。

### 踏襲パターン（挙動の意味）
- 「挿入」と「実行」を分ける2段階は spec/ui §4 の通り。現行 workbench の
  「候補を実行」ボタン（cie/ui/screens/workbench.py の run_candidate）を、
  「挿入」と「実行」の2挙動に分割する発想。

### ハーネス（実データE2E, R必須）
- Playwright + 実API + 実R（Rscript導入環境）で:
  1. チャット「男女の血圧を比べたい」→候補コード表示
  2. 「✓ スクリプトへ挿入」→エディタにコードが入る
  3. 「▶ Run」→Console にログがストリーム、Result に p値等、Output に図
  4. わざとエラーになるコードを実行→error_detail が画面に出る
  ※ R未導入環境では「Rscript が無い」旨が error_detail に出ることを確認（無言失敗しない）。

### 仕様→実装マッピング（完了基準）
| 挙動 | 実装 | 状態 |
|------|------|------|
| 候補→挿入 | ChatPane→EditorPane.insertAtCursor | ⬜ |
| 候補→実行 | ChatPane→runCode | ⬜ |
| エディタRun/選択実行 | EditorPane toolbar | ⬜ |
| コンソールストリーム | ConsolePane + ws | ⬜ |
| 図表示 | OutputTab + /api/visualize | ⬜ |
| 失敗理由表示 | 各ペインで error_detail/reason | ⬜ |

### 検証（必須）
- 上記ハーネスが通る（実R環境）。
- R未導入環境でも「無言で結果なし」にならず理由が出る。
- pytest（バックエンド）緑を維持。
```
