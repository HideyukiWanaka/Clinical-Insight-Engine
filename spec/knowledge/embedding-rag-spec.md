# CIE Platform — ローカル埋め込みRAG ＋ 安全な取り込み 仕様
# File: spec/knowledge/embedding-rag-spec.md
# Version: 1.0.0
# Governs: cie/knowledge/embedding_index.py (新規), cie/knowledge/ingestion_guard.py (強化)
# Basis: ADR-0005 原則3・原則4 / ADR-0003 (取り込みパイプライン)

---

## 1. 目的

目標④「ナレッジ参照による高いコード精度」を、キーワード検索から**ローカル埋め込みによる
意味検索**へ引き上げる。同時に、大量資料（論文・教科書）を安全に取り込むため、取り込み時の
PIIスキャンを強化する。

**重要な区別（誤解防止）:** ローカル化するのは *検索用の埋め込みモデル* のみ。
Rコードを *生成* するLLMは従来どおりクラウドの高性能モデル（Claude等）。埋め込みは
「文をベクトル化して類似検索する」専門タスクなので小型ローカルモデルで十分。

---

## 2. 埋め込み検索（retriever差し替え）

### 2.1 差し替え面（呼び出し側は無改修）
現行 `cie/knowledge/reference_library.py` の
`MarkdownReferenceLibrary.retrieve(query_terms: list[str], top_k) -> list[ReferenceDoc]`
と**同一シグネチャ**の `EmbeddingReferenceLibrary.retrieve(...)` を実装し、DIで差し替える。

呼び出し側（無改修で動くこと）:
- `cie/agents/statistics.py` — 3箇所（fresh / conversational / continuation）
- `cie/agents/visualization.py` — 1箇所
- `cie/agents/reporting.py` — 1箇所（自然文クエリ。埋め込みの恩恵が最大）

`ReferenceDoc`（`title/domain/path/content`＋`.excerpt()`）は返り値型として維持する。

### 2.2 索引（cie/knowledge/embedding_index.py 新規）
- 対象: `knowledge/official/**/*.md`（現状 `MarkdownReferenceLibrary` のみが使用。
  `KnowledgeLoader` はMETADATA.yaml不在のため official を読めていない点に留意）＋
  institutional/ の登録エントリ本文。
- 手順: 文書をチャンク分割（見出し境界＋最大トークン）→ ローカル埋め込みでベクトル化 →
  ベクトルストアに保存（ファイルベース、offline）。
- 索引はディスク上に永続化し、起動時ロード。`POST /api/knowledge/reindex` /
  知識承認後に増分更新。

### 2.3 検索
- `query_terms` を連結して1クエリベクトル化 → コサイン類似度上位を返す。
- `top_k` は意味検索前提で引き上げ（既定3〜5）。0件時は空リスト（従来同様、
  「参照なし」でプロンプトはグラウンディングを求めない）。
- provenance: 呼び出し側は従来どおり `[r.title for r in references]` を記録できる。

### 2.4 埋め込みモデルの制約（offline_first厳守）
- 完全ローカル実行。推奨: `onnxruntime` ＋ 小型多言語埋め込みモデル（日本語＋英語＋
  統計/R語彙に対応するもの）。torch同梱の肥大化は避ける。
- 初回のみモデル取得、以降オフライン。実行時に外部へ本文を送らない。
- すべて新規依存（現状 pyproject に埋め込み/ベクトル系はゼロ）。`pdf` 同様の optional extra
  `rag` として `pyproject.toml` に追加。

### 2.5 プロンプト制約の調整
現行の「参照に矛盾するな」という強い縛りは、弱い検索と組むと逆効果。埋め込み導入後は
「参照を根拠にしつつ、統計的に必要なら補ってよい（ただし矛盾はしない）」へ緩める
（`cie/agents/statistics.py` の `_R_GEN_SYSTEM_PROMPT` / 会話モードプロンプト）。

---

## 3. 安全な取り込み（PIIスキャン強化）

### 3.1 入口の分離
- 「解析データ（患者データ）」と「参考資料」のアップロード口をUI/APIで分離
  （`POST /api/dataset` と `POST /api/knowledge/ingest`）。
- 参考資料側は**表形式/統計データ拡張子を拒否**: csv/tsv/xlsx/xls/sav/dta/por/sas7bdat 等。
  受理は pdf/md/txt/docx のみ（`IngestionGuard.ALLOWED_EXTENSIONS` を踏襲・明確化）。
  ※ これは「弱い1枚目の壁」。本命は 3.2。

### 3.2 本文PIIスキャン（IngestionGuard._check_pii 強化）
現行の最小限 `_PII_TEXT_PATTERNS` に加え、既存PII資産を本文走査に活用:
- `PIIDetectorLayer1.detect_column_name` / `PIIFilter.run_on_prompt` — 患者ID・生年月日・
  氏名・電話・住所・メール等のキーワード/パターン検出。
- `ContextGuard.sanitize_stdout` の redaction ロジック — 任意テキストの走査プリミティブとして流用可。
- 検出時は `IngestionError(failed_checks=[...])` を送出し、**`pending/` にすら書かない**。
- 既存の5チェック（拡張子・サイズ・重複・埋め込みスクリプト・PII）の枠組みを維持。

### 3.3 人間承認ゲート（ADR-0003 維持）
- 取り込みは `KnowledgeIngestionAgent.ingest()` → `pending/` のみ書き込み。
- 承認は `cie/ui/components/knowledge_review.py`（またはReact相当）＋
  `KnowledgeLifecycleService.register_knowledge()` → institutional/。
- `approved_by_human=True` はスキーマ `const`。承認後に埋め込み索引を更新。

### 3.4 残存リスクと必須性
検索でヒットした参照チャンクは、生成時にプロンプトへ入り**外部LLMへ送られる**。
よって取り込み時PIIスキャンは必須。これを固めることで「患者データ入り資料は知識ベースに
入らない＝検索ヒットして外部に出ることもない」を保証する。

---

## 4. スキーマ拡張
`schemas/knowledge-entry.schema.json` は `additionalProperties:false` を持たず拡張可能。
`embedding`（ベクトル）またはチャンク単位のベクトル参照フィールドを追加してよい。
`source_info` の DOI/URL 必須（`SourceInfo.__post_init__`）は維持。

---

## 5. 検証観点
- 論文PDFを数点取り込み → 意味検索が的確なチャンクを返す（キーワード方式より改善）。
- 患者データ入りダミー文書 → 取り込み拒否（`pending/` に残らない）。
- 埋め込み処理中に外部通信が発生しない（オフライン確認）。
- 既存の retrieve 呼び出し側（statistics/visualization/reporting）が無改修で動作。
