# CIE 再設計 — Phase 9 設計図: 知識取り込みUI（参考資料パイプライン）
# File: docs/redesign/phase9_knowledge_ui_design.md
# Version: 1.0.0
# Basis: decisions/ADR-0003.md（知識取り込み）/ ADR-0002.md（人間承認）/ ADR-0005.md（原則4: 入口分離）
# Refs: spec/api/rest-api-contract.md §3.8/§3.9 / spec/ui/ide-workbench-spec.md §5
# Status: Design（実装指示は別途 prompts/redesign/phase9_knowledge_ui.md）

---

## 0. 背景と目的

バックエンドには「参考資料（論文・ガイドライン等）を取り込んで、AIの知識ベース（RAG）に
加える」知識取り込みパイプライン（KIP）の API が **5 本すべて実装済み**だが、Web フロントに
対応 UI が**皆無**（ヘッダ「参考資料」ボタンは現状ダミー）。本フェーズはこの UI を新設する。

Phase 8（データ投入・ファイル閲覧・追加対話）が ide-workbench の **4 ペイン中核動線**だったのに対し、
本機能は spec が **§5 で「参考資料の入口は別ペイン/別モーダルとして明確に分離」**（ADR-0005 原則4）と
規定する**別動線**。ゆえに独立フェーズ（Phase 9）として切り出す。

**中核原則（統治文書）:**
- **人間承認が必須**（ADR-0002/0003）。AI はドラフト提案まで。`institutional/` への登録は必ず人間が承認。
  `approved_by_human` はサーバ側で常に True（`knowledge.py` の approve）。
- **患者データ混入は取り込み時に拒否**（PIIスキャン → `422` ＋ `failed_checks`）。参考資料に
  患者データを混ぜない。
- **解析データ入口（Phase 8 ①）とは明確に分離**（§5）。ユーザーが「患者データ」と「文献」を
  取り違えない UI にする。
- **スコープは frontend/ のみ**。Agent・スキーマ・セキュリティは無改修。

### 対応表（バックエンド実装済 ⇄ フロント新設）

| # | API（実装済・無改修） | フロント新設 |
|---|----------------------|-------------|
| a | `POST /api/knowledge/ingest`（multipart, 422=PII拒否） | アップロード → ドラフト受領 |
| b | `POST /api/knowledge/approve`（draft_id/domain/trust_level/corrections） | ドラフトレビュー → 承認 |
| c | `POST /api/knowledge/reject`（draft_id/reason） | 却下 |
| d | `GET /api/knowledge`（登録済み一覧） | レジストリ一覧（**読み取り専用**） |
| e | `POST /api/knowledge/reindex`（{status,chunks}） | 手動「再索引」 |

---

## 1. 全体アーキテクチャ

```
Header「参考資料」ボタン（現状ダミー）─ onClick ─▶ KnowledgeModal（新規・別モーダル）
                                                    │
  ┌───────────────── KnowledgeModal の3セクション ──────────────────┐
  │ ① アップロード   file(pdf/md/txt/docx) ─POST /api/knowledge/ingest│
  │                    └─ 422(PII) → failed_checks を明示             │
  │ ② ドラフトレビュー 原典情報 / 抽出知識(confidence) / 抽出の限界     │
  │                    domain・trust_level セレクタ(修正可)            │
  │                    [✅承認]→approve  [❌却下]→reject(理由)          │
  │ ③ レジストリ一覧   GET /api/knowledge（読み取り専用）             │
  │                    [🔄 再索引]→reindex                            │
  └───────────────────────────────────────────────────────────────┘
        │ 既存エンドポイント（無改修）
        ▼
/api/knowledge/{ingest,approve,reject,(list),reindex}
```

**解析データ入口（Phase 8 ①）との分離（§5）:** 別モーダル・別ボタン・別配色/アイコンで、
「これは患者データではなく参考文献の入口」であることを常時明示。ヘッダは
「解析データ」＝患者データ、「参考資料」＝文献、の2ボタンを視覚的に区別する。

---

## 2. 契約詳細（既存・無改修）

### a. `POST /api/knowledge/ingest`（multipart `file`）
- 成功: `{ draft_id, extracted: { source_info, domain, trust_level, knowledge_items }, extraction_limitations }`
  - `source_info`: `{ title, year, doi, url, ... }`（抽出メタ）
  - `knowledge_items[]`: `{ statement, direct_quote, confidence(0..1), caveats }`
- **PII拒否**: `422` ＋ `{ error_code, message, failed_checks: [name...] }`（`IngestionError`）。
- **ドラフトはサーバの `app.state.knowledge_drafts` にインメモリ保持**（プロセス内・揮発）。
  → フロント再読込では残るが**サーバ再起動で消える**。UI は「保留中ドラフトは今セッション内で承認/却下」を前提に。

### b. `POST /api/knowledge/approve`
- req: `{ draft_id, domain, trust_level, corrections? }`。
  - `corrections.source_info` / `corrections.knowledge_items` で人間修正を上書き可（任意）。
- 承認後、サーバが埋め込み索引を best-effort で再構築（`_reindex_quietly`）。res: `{ entry_id }`。

### c. `POST /api/knowledge/reject` → `{ draft_id, status:"rejected" }`（`reason` 必須）。

### d. `GET /api/knowledge` → `{ entries: [{ entry_id, domain, status, trust_level, title }] }`。
- **注意**: REST の一覧は上記5項目のみ（version/related_entries/created_by は返らない）。

### e. `POST /api/knowledge/reindex` → `{ status:"reindexed", chunks }`（retriever非対応時 `501`）。

### 列挙値（`cie/ui/components/knowledge_review.py` と一致させる）
- trust_level: `regulatory` / `peer_reviewed` / `institutional` / `experimental`（バッジ 🟢🔵🟡🔴）
- domain: `statistics` / `clinical` / `reporting` / `R` / `Python` / `visualization`
- 低確信度しきい値: `confidence < 0.7` は 🟡 で強調（レビュー注意喚起）

---

## 3. フロント変更

- `api/client.ts`（既存パターン踏襲: `X-CIE-Token`、非2xxは `ApiError`＋detail）:
  ```ts
  ingestKnowledge(file: File): Promise<KnowledgeIngestResponse>   // multipart, Content-Type手動指定なし
  approveKnowledge(body): Promise<KnowledgeApproveResponse>       // {draft_id,domain,trust_level,corrections?}
  rejectKnowledge(body): Promise<KnowledgeRejectResponse>         // {draft_id,reason}
  listKnowledge(): Promise<KnowledgeListResponse>
  reindexKnowledge(): Promise<{status:string; chunks:number}>
  ```
- `api/types.ts`: 上記 req/res 型（`cie/api/models.py` の Knowledge* と一致）。
- **新規 `components/KnowledgeModal.tsx`**（3セクション。1コンポーネント内タブ or 縦積み）:
  - **① アップロード**: `file`（pdf/md/txt/docx）→ `ingestKnowledge`。**422 は `failed_checks` を
    赤系で明示**（例:「患者データが検出されたため取り込めません」）。成功でドラフトを②へ。
  - **② ドラフトレビュー**: 原典情報（title/year/doi/url）、抽出知識（statement/direct_quote/
    confidence/caveats、`<0.7` は 🟡）、抽出の限界（`extraction_limitations`）を表示。
    `trust_level`・`domain` セレクタ（抽出値を初期選択、人間が修正可）。
    **[✅ 承認]→approve**（選択した domain/trust_level を送信。corrections は任意で v1 は最小）、
    **[❌ 却下]→reject**（理由入力必須）。処理中/失敗は detail 表示（無言失敗禁止 §5）。
  - **③ レジストリ一覧**: `listKnowledge` を trust バッジ付きで表示（**読み取り専用**）。
    **[🔄 再索引]→reindexKnowledge**（結果 chunks 数を表示。501 は「対応retriever未配線」を明示）。
- `components/Header.tsx`: 「参考資料」ボタンに `onClick={onOpenKnowledge}` を配線。
  「解析データ」ボタン（Phase 8）とは**別アイコン・別配色**で分離を明示（§5）。
- `App.tsx`: `knowledgeOpen` 状態と開閉配線。

---

## 4. 人間承認とセキュリティ（統治遵守）

- **AI は提案のみ・登録は人間**（ADR-0002/0003）。承認ボタンが唯一の登録トリガー。フロントは
  `approved_by_human` を送らない（サーバが常に True 付与）。
- **PIIスキャン拒否（422）を握りつぶさない**。参考資料に患者データを混ぜない旨を UI が明言。
- **入口分離（§5, ADR-0005 原則4）**: 患者データ（解析データ入口）と参考資料を UI で峻別。
- **完全ローカル**（ADR-0003/0005）: 取り込み・索引は外部通信なし。UI は追加の外部呼び出しをしない。

---

## 5. リスクと設計判断

| ID | 論点 | 判断 / 推奨 |
|----|------|------------|
| K-1 | 入口の取り違え | 患者データ入口と**視覚的に強く分離**（別モーダル/色/アイコン/注意書き）。 |
| K-2 | ドラフトの揮発性 | `app.state` インメモリ保持＝サーバ再起動で消える。UI は「今セッションで承認/却下」を前提に、保留一覧を持つなら注意書きを添える。 |
| K-3 | 一覧が読み取り専用 | **REST にアーカイブ endpoint が無い**（Streamlit にはあるが未API化）。React 一覧は閲覧のみ。アーカイブが要るなら**別途バックエンド追加（別フェーズ）**。本フェーズはフロントのみ。 |
| K-4 | multipart 送信 | `ingestKnowledge` は **Content-Type を手動設定しない**（境界崩れ防止）。 |
| K-5 | corrections の範囲 | v1 は domain/trust_level の修正のみ確実に。source_info/knowledge_items の細粒度編集は任意（後続で拡張可）。 |
| K-6 | 再索引の失敗 | reindex 501/失敗でも承認自体は成立済み（サーバは best-effort）。UI はそれを正しく表現する。 |

---

## 6. テスト計画（Playwright E2E, API スタブ／実データはハーネス）

- **ingest 成功** → ドラフトレビューに原典情報・知識項目・限界・confidence 🟡 が出る。
- **ingest 422（PII）** → failed_checks が明示され、ドラフトに進まない。
- **approve** → body に選択 domain/trust_level が載り、entry_id を受領。一覧に反映（再取得）。
- **reject** → 理由必須、rejected を確認。
- **list** → trust バッジ付き読み取り専用（削除/アーカイブUIが無い）。
- **reindex** → chunks 表示 / 501 時にメッセージ。
- 全失敗経路で理由表示（無言失敗禁止 §5）。既存 E2E 回帰なし・tsc/vite build 成功・pytest 緑維持。

---

## 7. 完了の定義（本フェーズ）

- 5 API がフロントで配線され、上記 E2E が緑。
- 人間承認フロー（提案→人間承認→登録）が UI 上で成立。PII拒否を明示。
- 解析データ入口と参考資料入口が視覚的に分離（§5）。
- 差分は `frontend/` のみ（バックエンド・Agent・スキーマ・セキュリティ無改修）。
- 実装指示は `prompts/redesign/phase9_knowledge_ui.md`（R9-0〜）に従う。

---

## 8. 既知の非対称（バックエンド follow-up 候補・本フェーズ外）

- **アーカイブAPIが未提供**（K-3）。institutional/ の Soft Delete（ADR-0003）を UI から行うには
  `POST /api/knowledge/archive` 等の追加が必要。必要になった時点で ADR は不要（既存方針の実装）だが、
  API 追加のため別フェーズで扱う。
