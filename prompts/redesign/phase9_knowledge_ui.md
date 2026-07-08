# CIE 再設計 — Phase 9: 知識取り込みUI（参考資料パイプライン）
# File: prompts/redesign/phase9_knowledge_ui.md
# Version: 1.0.0
# Design: docs/redesign/phase9_knowledge_ui_design.md
# 前提: バックエンドの /api/knowledge/* 5本は実装済・無改修。本フェーズは frontend/ のみ。
#       参考資料入口は解析データ入口（Phase 8 ①）と明確に分離する（§5, ADR-0005 原則4）。

---

## PROMPT R9-0: ブランチ作成

```
git checkout main && git pull origin main
git checkout -b feature/redesign-phase-9-knowledge-ui
```

---

## PROMPT R9-1: 取り込み〜人間承認フロー（ingest / draft review / approve・reject）

```
参考資料を取り込み、AI抽出ドラフトを人間がレビューして承認/却下する中核フローを実装します。
AIは提案まで・登録は必ず人間（ADR-0002/0003）。患者データ混入は422で拒否される。

### 読み込むべき仕様ファイル
- decisions/ADR-0003.md（知識取り込み・人間承認・Soft Delete）/ ADR-0002.md（承認必須）
- spec/api/rest-api-contract.md（§3.8 ingest/approve/reject）
- spec/ui/ide-workbench-spec.md（§5 参考資料入口の分離・生データ非表示）
- docs/redesign/phase9_knowledge_ui_design.md（§2 契約, §3 フロント, §4 承認/セキュリティ）
- cie/api/routes/knowledge.py（ingest→422 failed_checks / approve→entry_id / reject の契約）
- cie/api/models.py（Knowledge* の req/res 型）
- cie/ui/components/knowledge_review.py（踏襲: 原典情報/知識項目/confidence 0.7閾値/trust・domain選択肢）
- frontend/src/api/client.ts（fetch/ApiError/readErrorEnvelope パターン、multipart 送信作法）

### 実装範囲
- ✅ client.ts: ingestKnowledge(file)（multipart, **Content-Type 手動指定なし**）,
     approveKnowledge({draft_id,domain,trust_level,corrections?}), rejectKnowledge({draft_id,reason})。
     非2xxは既存 ApiError 整形。422（PII拒否）は failed_checks を保持して UI へ渡す。
- ✅ types.ts: KnowledgeIngestResponse{draft_id,extracted{source_info,domain,trust_level,knowledge_items[]},
     extraction_limitations[]}, KnowledgeApprove/Reject の req/res（models.py と一致）。
- ✅ components/KnowledgeModal.tsx（新規, 別モーダル）— 本プロンプトでは①②を実装:
     - **① アップロード**: file(pdf/md/txt/docx) → ingestKnowledge。
       422 は「患者データ検出のため取り込めません」等を **failed_checks 付きで赤系明示**（無言失敗禁止）。
     - **② ドラフトレビュー**: 原典情報(title/year/doi/url)、抽出知識(statement/direct_quote/
       confidence/caveats、**confidence<0.7 は 🟡**)、抽出の限界(extraction_limitations)を表示。
       trust_level・domain セレクタ（抽出値を初期選択、人間が修正可）。
       **[✅ 承認]→approveKnowledge**（選択 domain/trust_level を送信。corrections は v1 最小で可）、
       **[❌ 却下]→rejectKnowledge**（理由入力必須）。処理中/失敗は detail 表示。
- ❌ KnowledgeIngestionAgent / LifecycleService を直接 import しない（UIは callback/API経由のみ）。
     approved_by_human はフロントで送らない（サーバが常に True 付与）。バックエンド無改修。

### 踏襲パターン
- レビュー表示・trust/domain 選択肢・confidence 0.7 閾値は knowledge_review.py に一致させる。
- 送信/エラーは client.ts の post()/readErrorEnvelope と同じ作法（ApiError＋detail を UI に出す）。

### ハーネス（実データE2E）
- Playwright + 実API:
  1. 参考文献(md/txt)をアップロード→ドラフトレビューに原典情報・知識項目・限界・confidence 🟡 が出る
  2. 患者データ混入ファイル→422→failed_checks が明示され、ドラフトに進まない
  3. domain/trust_level を修正して [承認]→ approve body に選択値が載り entry_id 受領
  4. [却下]→理由必須、rejected を確認
  5. 全失敗経路で理由が表示される（無言失敗しない）

### 仕様→実装マッピング（完了基準）
| 項目 | 実装 | 状態 |
|------|------|------|
| ingest/approve/reject 配線 | client.ts | ⬜ |
| Knowledge 型 | types.ts | ⬜ |
| アップロード＋422明示 | KnowledgeModal ① | ⬜ |
| ドラフトレビュー | KnowledgeModal ② | ⬜ |
| 承認/却下 | approve/reject 呼び出し | ⬜ |

### 検証（必須）
- 人間承認フロー（提案→人間承認→登録）が UI 上で成立。PII拒否(422)を明示。
- 生データ行を UI に出さない（§5）。失敗理由が必ず表示される。
- 既存E2E回帰なし・tsc/vite build 成功・バックエンド pytest 緑を維持。
```

---

## PROMPT R9-2: レジストリ一覧＋再索引＋入口配線（list / reindex / Header）

```
登録済み知識の閲覧と索引再構築を追加し、ヘッダ「参考資料」からモーダルを開けるようにします。
一覧は読み取り専用（RESTにアーカイブAPIは無い）。解析データ入口と視覚的に分離。

### 読み込むべき仕様ファイル
- spec/api/rest-api-contract.md（§3.8 GET /api/knowledge, §3.9 reindex）
- spec/ui/ide-workbench-spec.md（§5 入口分離）
- docs/redesign/phase9_knowledge_ui_design.md（§3 ③, §5 K-3/K-6, §8 非対称）
- cie/api/routes/knowledge.py（list の 5項目 / reindex の {status,chunks} と 501）
- cie/ui/components/knowledge_review.py（trust バッジ 🟢🔵🟡🔴 の踏襲）
- frontend/src/components/Header.tsx（「参考資料」ダミーボタン, 「解析データ」との区別）
- frontend/src/App.tsx（モーダル開閉配線）

### 実装範囲
- ✅ client.ts: listKnowledge()→{entries:[{entry_id,domain,status,trust_level,title}]},
     reindexKnowledge()→{status,chunks}（501=対応retriever未配線 を ApiError で保持）。
- ✅ types.ts: KnowledgeListResponse / エントリ型（models.py と一致）。
- ✅ KnowledgeModal.tsx に **③ レジストリ一覧**: listKnowledge を **trust バッジ付きで読み取り専用表示**
     （削除/アーカイブUIは置かない — RESTに該当APIが無い K-3）。承認後は再取得で反映。
     **[🔄 再索引]→reindexKnowledge**（chunks 数を表示。501 は「対応retriever未配線」を明示。
     承認自体は成立済みなので再索引失敗を過大表現しない K-6）。
- ✅ Header.tsx: 「参考資料」ボタンに onClick={onOpenKnowledge} を配線。
     **「解析データ」ボタン（Phase 8 ①）とは別アイコン・別配色**で入口を峻別（§5, K-1）。
- ✅ App.tsx: knowledgeOpen 状態と開閉を配線。
- ❌ アーカイブUIは作らない（対応APIが無い＝別フェーズ）。バックエンド無改修。

### 踏襲パターン
- trust バッジ配色は knowledge_review.py の _TRUST_LEVEL_BADGE に一致。
- 入口分離は §5（患者データ＝解析データ、文献＝参考資料を UI で峻別）。

### ハーネス（実データE2E）
- Playwright + 実API:
  1. Header「参考資料」→ KnowledgeModal が開く（「解析データ」とは別入口として区別できる）
  2. 一覧が trust バッジ付きで表示され、削除/アーカイブUIが無い
  3. 承認済みエントリが一覧に現れる（再取得）
  4. [再索引]→chunks 表示 / 501 時に「未配線」メッセージ
  5. 全失敗経路で理由表示（無言失敗しない）

### 仕様→実装マッピング（完了基準）
| 項目 | 実装 | 状態 |
|------|------|------|
| list/reindex 配線 | client.ts | ⬜ |
| レジストリ一覧（読み取り専用） | KnowledgeModal ③ | ⬜ |
| 再索引 | reindexKnowledge | ⬜ |
| Header「参考資料」配線 | Header onOpenKnowledge | ⬜ |
| 入口分離 | 解析データと別アイコン/配色 | ⬜ |

### 検証（必須）
- 一覧は読み取り専用（削除/アーカイブUIなし）。承認後に反映。再索引の結果/失敗を正しく表示。
- 参考資料入口が解析データ入口と視覚的に分離（§5）。
- 既存E2E回帰なし・tsc/vite build 成功・バックエンド pytest 緑を維持。
```

---

## PROMPT R9-3: 仕上げ（回帰・整合）

```
### 実装範囲
- ✅ frontend E2E 全緑（既存 + 新規 phase9-knowledge-* ）。
- ✅ tsc -b --noEmit / vite build 成功。バックエンド pytest（api/knowledge）緑を維持。
- ✅ 差分は frontend/ のみ（バックエンド・Agent・スキーマ・セキュリティ無改修）を確認。
- ✅ docs/redesign/phase9_knowledge_ui_design.md の完了定義（§7）を満たす。
- ❌ アーカイブAPI（Soft Delete）追加は本フェーズ対象外（§8, 別フェーズでBE追加）。

### 検証（必須）
- 人間承認が唯一の登録トリガー / PII拒否を明示 / 生データ非表示（§5）。
- 全失敗経路で理由が表示される（無言失敗禁止）。
- README（prompts/redesign）フェーズ表に Phase 9 を追記（任意）。
```
