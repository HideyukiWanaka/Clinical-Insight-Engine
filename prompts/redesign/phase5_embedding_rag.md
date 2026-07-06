# CIE 再設計 — Phase 5: ローカル埋め込みRAG＋安全な取り込み
# File: prompts/redesign/phase5_embedding_rag.md
# Version: 1.0.0

---

## PROMPT R5-0: ブランチ作成

```
git checkout main && git pull origin main
git checkout -b feature/redesign-phase-5-rag
```

---

## PROMPT R5-1: ローカル埋め込み検索（retriever差し替え）

```
キーワード検索をローカル埋め込みの意味検索へ差し替えます。呼び出し側は無改修。

### 読み込むべき仕様ファイル
- spec/knowledge/embedding-rag-spec.md（§2 埋め込み検索）
- cie/knowledge/reference_library.py（差し替え対象のシグネチャ: retrieve/ReferenceDoc）
- 呼び出し側: cie/agents/statistics.py（3箇所）, visualization.py（1）, reporting.py（1）

### 実装範囲
- ✅ cie/knowledge/embedding_index.py: official/**/*.md ＋ institutional/ をチャンク化・
     ローカル埋め込みでベクトル化・ファイルベースのベクトルストアに保存/ロード。
- ✅ EmbeddingReferenceLibrary.retrieve(query_terms: list[str], top_k) -> list[ReferenceDoc]
     を実装（MarkdownReferenceLibrary と同一シグネチャ）。DIで差し替え（services.py）。
- ✅ 埋め込みは完全ローカル（onnxruntime＋小型多言語モデル等）。初回のみ取得、以降オフライン。
- ✅ top_k を既定3〜5へ。0件時は空リスト。
- ✅ プロンプト制約の緩和（statistics のRエ生成プロンプト）: 「参照を根拠にしつつ、
     統計的に必要なら補ってよい（矛盾はしない）」へ。
- ❌ 呼び出し側（statistics/visualization/reporting）は原則無改修。

### 踏襲パターン
- 差し替え面は「list[str]入力 / list[ReferenceDoc]出力 / .title を provenance へ /
  list を message builder へ」の4部契約（reference_library.py の retrieve）。

### ハーネス（実データE2E, オフライン確認）
```python
# scratchpad/harness_embedding_rag.py
# 1. official/ の md を索引化（外部通信を監視: 発生しないこと）
# 2. クエリ「Mann-Whitney U test / wilcox.test」で意味検索 → 適切な参照docが上位
# 3. 表記ゆれ（"Mann-Whitney" vs mann_whitney_u_test）でも当たることを確認
# 4. statistics._generate_r_script を差し替え版retrieverで実行し provenance に references
```

### 仕様→実装マッピング（完了基準）
| 項目 | 実装 | 状態 |
|------|------|------|
| チャンク化・索引 | embedding_index.py | ⬜ |
| retrieve 差し替え | EmbeddingReferenceLibrary | ⬜ |
| DI差し替え | cie/api/services.py | ⬜ |
| プロンプト緩和 | statistics.py プロンプト | ⬜ |
| 呼び出し側無改修 | statistics/visualization/reporting | ⬜ |

### 検証（必須）
- 表記ゆれクエリでキーワード方式より的確な参照を返す（before/after比較）。
- 索引化・検索中に外部通信ゼロ（オフライン確認）。
- 呼び出し側の既存ユニットテストが無改修で緑。
```

---

## PROMPT R5-2: 取り込み時PIIスキャン強化＋入口分離

```
参考資料の取り込みで患者データを未然に弾きます。

### 読み込むべき仕様ファイル
- spec/knowledge/embedding-rag-spec.md（§3 安全な取り込み）
- cie/knowledge/ingestion_guard.py（_check_pii, ALLOWED_EXTENSIONS, 5チェック）
- cie/security/pii_detector.py / pii_filter.py / context_guard.py（流用する資産）

### 実装範囲
- ✅ IngestionGuard._check_pii を強化: PIIDetectorLayer1.detect_column_name /
     PIIFilter.run_on_prompt / ContextGuard.sanitize_stdout のロジックで本文走査。
     検出時 IngestionError(failed_checks=[...]) で pending/ にすら書かない。
- ✅ 入口分離: 参考資料は pdf/md/txt/docx のみ受理。csv/tsv/xlsx/sav/dta 等は拒否
     （弱い1枚目の壁）。UI/APIで「解析データ」と「参考資料」を別導線に。
- ✅ 承認後に埋め込み索引を増分更新（/api/knowledge/approve → reindex）。
- ❌ 人間承認フロー自体は既存（ADR-0003）を流用。作り直さない。

### ハーネス（実データE2E）
- 論文PDF（PII無し）→ 取り込み成功→ pending/ にドラフト、承認で institutional/ 登録、索引更新。
- 患者データ入りダミー文書（氏名・生年月日・患者ID）→ 取り込み拒否（pending/ に残らない）。
- csv を参考資料入口へ→ 拡張子で拒否。

### 仕様→実装マッピング（完了基準）
| 項目 | 実装 | 状態 |
|------|------|------|
| 本文PIIスキャン | ingestion_guard._check_pii | ⬜ |
| 入口分離・拡張子拒否 | ingestion_guard + API/UI | ⬜ |
| 承認後 reindex | /api/knowledge/approve | ⬜ |

### 検証（必須）
- 患者データ入り文書が確実に拒否される（回帰テストを tests/ に追加）。
- 既存の取り込みパイプライン（ADR-0003）テストが緑。
- 埋め込み索引が承認後に更新される。
```
