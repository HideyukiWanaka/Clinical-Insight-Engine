# CIE 再設計（IDE型UI + ローカルRAG + Rワークスペース永続化）実装プロンプト集
# File: prompts/redesign/README.md
# Version: 1.0.0
# Basis: decisions/ADR-0005.md

---

## これは何か

現行 Streamlit UI を、画像で示された **RStudio + AIアシスタント** 型のIDEへ刷新するための、
フェーズ別・実装指示プロンプト集。既存のバックエンド（Agent・セキュリティ・R実行）は温存し、
API層とWebフロントを新設する。目標④のRAGはローカル埋め込み検索へ強化し、実行をまたぐ変数
保持を `.RData` 可視ファイルで実現する。

**必ず先に読む仕様書:**
- `decisions/ADR-0005.md` — 統治決定（4原則）
- `spec/api/rest-api-contract.md` — API契約
- `spec/ui/ide-workbench-spec.md` — 4ペインIDE
- `spec/knowledge/embedding-rag-spec.md` — ローカル埋め込みRAG＋安全な取り込み
- `spec/runtime-workspace-persistence.md` — `.RData` 永続化
- `docs/AI_IMPLEMENTATION_LESSONS.md` — スケルトン化防止の6策（各プロンプトが従う）

---

## フェーズ一覧と順序

| # | ファイル | 内容 | 成果物が動く状態 |
|---|---------|------|----------------|
| 0 | phase0_adr_specs.md | ADR/spec/MANIFEST整合、依存追加、足場 | pytest緑・spec整合 |
| 1 | phase1_api_layer.md | FastAPI API層（既存Agentを直接呼び出しでラップ） | curl/httpxで各API疎通 |
| 2 | phase2_frontend_shell.md | React+Monacoの4ペイン骨格＋チャット疎通 | ブラウザで画面表示・チャット応答 |
| 3 | phase3_seamless_editor.md | 「スクリプトへ挿入」「実行」＋WSコンソール | 挿入→実行→結果/図/変数表示 |
| 4 | phase4_workspace_persistence.md | `.RData` 保存/復元＋Workspace/Data表示 | 変数が実行をまたいで残る |
| 5 | phase5_embedding_rag.md | ローカル埋め込み検索＋取り込みPIIスキャン強化 | 意味検索・患者データ資料拒否 |
| 6 | phase6_report_output.md | 報告書フォーマット出力（既存Reporting接続） | 選択フォーマットで原稿生成 |
| 7 | phase7_desktop_packaging.md | Tauriデスクトップ枠（任意・最終） | インストーラ生成 |

**進め方:** 各フェーズは独立ブランチで実装し、フェーズ末に「動く成果物＋テスト緑」を満たして
から次へ。途中で止めてもローカルWebアプリとして完成品が残る（デスクトップ枠は最後）。

---

## 各プロンプト共通の必須構成（AI_IMPLEMENTATION_LESSONS.md 準拠）

各プロンプトは以下5点を必ず含む:
1. **実装範囲**（✅やる / ❌やらない の線引き）
2. **踏襲パターン**（既存コードのどのパターンを真似るか、file:line付き）
3. **ハーネス雛形**（実データでE2Eに動くまで完了と見なさない）
4. **仕様→実装マッピング表**（完了基準）
5. **検証手順**（pytest緑＋Playwright/実成果物の生成確認）

---

## セキュリティの不変条件（全フェーズ共通）
- 生データ行はLLMにもAPIレスポンスにも出さない（`var_n` 匿名化維持）。
- LLM生成呼び出し以外の外部通信を作らない（offline_first）。埋め込みはローカル。
- Capabilityトークンは try/finally で必ず revoke。
- API/WSは `127.0.0.1` 束縛＋セッショントークン検証。
- 参考資料の取り込みは本文PIIスキャンで患者データを拒否。
