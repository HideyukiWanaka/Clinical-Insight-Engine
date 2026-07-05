# CIE 再設計 — Phase 7: デスクトップ枠（任意・最終）
# File: prompts/redesign/phase7_desktop_packaging.md
# Version: 1.0.0
# Note: このフェーズは「必要になったら」着手。ローカルWebアプリ（Phase 1-6）で
#       体験・オフライン・セキュリティは達成済み。ここは配布形態の追加のみ。

---

## PROMPT R7-0: ブランチ作成

```
git checkout main && git pull origin main
git checkout -b feature/redesign-phase-7-desktop
```

---

## PROMPT R7-1: Tauri でデスクトップ枠に包む

```
Phase 2-6 の React フロントを Tauri でデスクトップアプリ化します。UIは作り直しません。

### 読み込むべき仕様ファイル
- decisions/ADR-0005.md（原則1: 段階戦略。同一フロントを包む）
- spec/api/rest-api-contract.md（sidecar として起動する既存API）

### 実装範囲
- ✅ Tauri プロジェクトを frontend/ に統合。既存 React ビルドを WebView で表示。
- ✅ Python(API)を sidecar として同梱・起動（アプリ起動時に uvicorn をローカルポートで spawn、
     終了時に停止）。ポートは 127.0.0.1 のランダムポート。セッショントークンをアプリ内で受け渡し。
- ✅ 埋め込みモデル・R検出のオンボーディング（Rが見つからない場合の案内）。
- ✅ Win/Mac 向けインストーラ生成。
- ❌ 業務ロジック・UIロジックの変更はしない（Phase 1-6 の成果をそのまま使う）。

### 難所（事前に織り込む）
- Python同梱: PyInstaller 等で API＋依存（pydantic/sqlalchemy/httpx/onnxruntime 等）を固める。
  埋め込みモデルの同梱容量に注意（torch は避け onnxruntime＋小型モデル）。
- コード署名・自動更新は別タスクとして分離してよい。

### ハーネス（配布物確認）
- ビルドしたアプリを起動→ sidecar API が立ち上がり→ フロントが疎通→
  「男女の血圧を比べたい」の一連（提案→挿入→実行→結果→原稿）がデスクトップ枠で動く。
- ネットワーク: 外部通信は LLM 呼び出しのみ（埋め込み・R実行はローカル）。

### 仕様→実装マッピング（完了基準）
| 項目 | 実装 | 状態 |
|------|------|------|
| Tauri 統合 | frontend/src-tauri | ⬜ |
| Python sidecar 起動/停止 | Tauri コマンド | ⬜ |
| R検出オンボーディング | 起動時チェック | ⬜ |
| インストーラ | tauri build | ⬜ |

### 検証（必須）
- 配布ビルドが起動し、ゴールデンパスが動く。
- localhost 以外にポートを開かない（漏洩リスク確認）。
- オフラインで埋め込み・R実行が動く。
```
