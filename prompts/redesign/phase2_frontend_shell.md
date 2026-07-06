# CIE 再設計 — Phase 2: React+Monaco 4ペイン骨格
# File: prompts/redesign/phase2_frontend_shell.md
# Version: 1.0.0

---

## PROMPT R2-0: ブランチ作成

```
git checkout main && git pull origin main
git checkout -b feature/redesign-phase-2-frontend
```

---

## PROMPT R2-1: フロント足場と4ペインレイアウト

```
React+TypeScript+Monaco で spec/ui/ide-workbench-spec.md の4ペイン骨格を作ります。

### 読み込むべき仕様ファイル
- spec/ui/ide-workbench-spec.md（§2 レイアウト, §3 各ペイン）
- spec/api/rest-api-contract.md（§2 認証, §3 REST）
- spec/ui/ui-principles.md（思想の継承: 意図中心・人間が決定・セキュリティ可視化）

### 実装範囲
- ✅ frontend/ を Vite + React + TypeScript で初期化。@monaco-editor/react,
     react-resizable-panels を導入。
- ✅ 4ペイン + ヘッダのレイアウト骨格（リサイズ可能）。ライト/ダーク対応。
- ✅ APIクライアント（frontend/src/api/client.ts）: X-CIE-Token を付与、
     base URL は http://127.0.0.1:<port>。エラー時は error_detail を UI に伝播。
- ✅ 左チャットペイン: 入力→POST /api/intent→（確定後）POST /api/propose の疎通まで。
     AI応答の explanation_markdown を吹き出し表示、code_candidates をコードブロック表示。
- ❌ 「挿入」「実行」ボタンの実挙動・WSコンソール・図表示は Phase 3。ここは表示疎通まで。

### 踏襲パターン
- ペインの役割・配置は spec/ui/ide-workbench-spec.md §2 の図に厳密に従う。
- 失敗時に reason を必ず見せる方針は、現行 workbench.py の _render_output_pane の
  「error_detail を出す」思想を踏襲（cie/ui/screens/workbench.py）。

### ハーネス（実挙動確認）
- Playwright で: 起動→チャットに「男女の血圧を比べたい」入力→
  AI応答（説明＋候補コード）が表示されることを確認。
- APIはPhase 1の実物 or スタブサーバに接続。

### 仕様→実装マッピング（完了基準）
| ペイン | コンポーネント | 状態 |
|--------|--------------|------|
| ヘッダ | Header.tsx | ⬜ |
| 左チャット | ChatPane.tsx | ⬜ |
| 中上エディタ | EditorPane.tsx（Monaco） | ⬜ |
| 中下コンソール | ConsolePane.tsx（枠のみ） | ⬜ |
| 右上ファイル | FileTree.tsx（枠のみ） | ⬜ |
| 右下Workspace/Format | WorkspacePane.tsx / FormatPane.tsx（枠のみ） | ⬜ |
| APIクライアント | api/client.ts | ⬜ |

### 検証（必須）
- `npm run dev` で起動、Playwright で4ペイン表示・チャット応答表示を確認・スクショ取得。
- 例外・未捕捉エラーがコンソールに出ないこと。
- Phase 1 API と結線した状態で intent→propose が通ること。
```
