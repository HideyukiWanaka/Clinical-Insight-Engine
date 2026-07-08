# CIE 再設計 — Phase 8 設計図: フロント未配線ギャップの解消
# File: docs/redesign/phase8_frontend_gaps_design.md
# Version: 1.0.0
# Basis: decisions/ADR-0005.md / spec/api/rest-api-contract.md / spec/ui/ide-workbench-spec.md
# Status: Design (実装は prompts/redesign/phase8_frontend_gaps.md の指示に従う)

---

## 0. 背景と目的

Phase 1〜6 でバックエンド（FastAPI API層）は 14 ルートすべてが実装済みだが、
Web フロント（`frontend/`）が**未配線**の機能が 3 点残っている。いずれも
「バックエンド先行・フロント未接続」であり、**フロントが叩いて存在しない API は 0 件**
（＝壊れた呼び出しはない）。本フェーズはこの 3 ギャップを埋め、
ide-workbench-spec の理想「1 画面で 対話 → 実行 → 確認 → 出力」を成立させる。

| # | ギャップ | 仕様根拠 | バックエンド | フロント現状 |
|---|---------|---------|------------|------------|
| ① | データセット投入口 | §3.1 前提 / §5 入口 | `POST /api/dataset`（実装済） | UIなし・`dataset_uploaded:false` ハードコード |
| ② | ファイルツリー | §3.4 | `GET /api/files(/content)`（実装済） | `FileTree.tsx` はプレースホルダ |
| ③ | 追加対話（会話継続） | §3.1 / §3.2 / §4 step5 | `POST /api/propose`（継続対応済） | 初回 `intent_object` のみ送信 |

**非対象（本フェーズ外）:** 知識取り込みUI（`/api/knowledge/*`, §3.8/§3.9）は
ide-workbench §3 の 4 ペインに含まれず「別ペイン/別モーダル」扱いのため、別フェーズに切り出す。

**遵守する統治文書:** CLAUDE.md の絶対ルール（`inject_raw_data_rows` は常に False、
Capability Token は try/finally で失効＝**API層で対応済・無改修**）、PROJECT_RULES.md S.4
（API層は薄いラッパ、業務ロジックを持たない）、§5（生データ行はフロントに返さない）。
本フェーズは**フロントのみ**の変更で、バックエンド・Agent・スキーマは無改修を原則とする。

---

## 1. 全体アーキテクチャ（変更の位置づけ）

```
┌──────────────────────────── frontend/src ────────────────────────────┐
│ App.tsx                                                               │
│  ├─ datasetInfo state ①  ── Header「解析データ」→ DatasetModal ①(新規) │
│  │      └─ dataset_uploaded を ChatPane へ供給                        │
│  ├─ runner (useRunner)                                                │
│  │      ├─ lastIntent（既存）                                         │
│  │      ├─ lastScript ③(新規: 実行したコードを保持)                   │
│  │      └─ result.statistical_results（既存: 継続の prior）           │
│  ├─ ChatPane ③ ── 初回=intent / 実行後=continuation_query に分岐      │
│  └─ FileTree ② ── GET /api/files 一覧 + content プレビュー(新規)      │
│         └─ refreshKey（run 完了で bump → 生成物を反映）               │
│                                                                       │
│ api/client.ts  ← uploadDataset① / listFiles② / fetchFileContent② 追加 │
│ api/types.ts   ← Dataset/Files 型 追加                                 │
└───────────────────────────────────────────────────────────────────────┘
        │ 既存エンドポイント（無改修で利用）
        ▼
POST /api/dataset① · GET /api/files② · GET /api/files/content② · POST /api/propose③
```

原則: **既存の `CieApiClient` パターン**（`X-CIE-Token` ヘッダ付与、非 2xx は
`ApiError`＋`detail` を投げる、無言失敗を作らない §5）を全追加メソッドで踏襲する。

---

## 2. ギャップ①: データセット投入口

### 2.1 契約（既存・無改修）
- `POST /api/dataset` … `multipart/form-data` の `file`（CSV）。
  res: `{ dataset_id, row_count, column_count, columns: [...] }`（**集計メタのみ・生データ行なし**、
  `cie/api/routes/dataset.py`）。サーバは `app.state.dataset_context` に保持し、
  以降の `POST /api/intent` が `dataset_structural_metadata` として自動参照する
  （`cie/api/routes/intent.py`）。**フロントは列メタを表示するだけ**でよい。

### 2.2 フロント変更
- `api/client.ts`:
  ```ts
  async uploadDataset(file: File): Promise<DatasetUploadResponse>
  ```
  `fetch(POST /api/dataset)` に `X-CIE-Token` のみ付与（**Content-Type は付けない**＝
  ブラウザが multipart 境界を設定）。非 2xx は既存 `readErrorEnvelope` → `ApiError`。
- `api/types.ts`: `DatasetUploadResponse { dataset_id; row_count; column_count; columns: DatasetColumn[] }`
  （`columns` の要素は `build_dataset_context` 出力の集計メタ形。値は over-spec せず素直に写す）。
- **新規 `components/DatasetModal.tsx`**: Header「解析データ」ボタンで開くモーダル。
  ファイルピッカー → `uploadDataset` → **列メタ（名前・型・要約統計）をテーブル表示**。
  行データは一切表示しない（§5）。失敗時は `ApiError.detail` を表示（無言失敗禁止）。
  取り込み PII 拒否（422）等もメッセージ表示。
- `App.tsx`: `datasetInfo: DatasetUploadResponse | null` を保持。Header へ `onOpenDataset`、
  ChatPane へ `datasetUploaded={datasetInfo != null}` を供給。
- `components/Header.tsx`: 「解析データ」ボタンに `onClick={onOpenDataset}` を配線
  （現状は無反応のダミー）。取り込み済みなら簡易バッジ表示可。
- `components/ChatPane.tsx`: `dataset_uploaded: false`（ハードコード）を
  `dataset_uploaded: props.datasetUploaded` に置換。

### 2.3 セキュリティ／ADR 遵守
- `inject_raw_data_rows` はサーバ側で常に False（`intent.py`）。フロントは列メタのみ受領・表示。
- モーダルは「解析データ」入口専用（§5: 参考資料入口と明確に分離）。

---

## 3. ギャップ②: ファイルツリー（§3.4）

### 3.1 契約（既存・無改修）
- `GET /api/files` … res `{ files: [{ path, size_bytes, modified, kind }] }`
  （`kind` は image/code/data/text 等。`cie/api/routes/files.py`。**読み取り専用**）。
- `GET /api/files/content?path=` … テキストは `{ text, language }`、画像は `image/png` バイト。
  **パストラバーサルはサーバ側で拒否**（フロントは workspace 相対 path を渡すだけ）。

### 3.2 フロント変更
- `api/client.ts`:
  ```ts
  listFiles(): Promise<FilesResponse>
  fetchFileContent(path: string): Promise<FileContentResponse>   // {text, language}
  // 画像は既存 fetchImageObjectUrl(path) を流用（要 revoke）
  ```
  `listFiles`/`fetchFileContent` は GET＋`X-CIE-Token` ヘッダ（`post()` と同様のエラー整形を
  共通化 or 個別実装）。
- `api/types.ts`: `FileEntry`/`FilesResponse`/`FileContentResponse` を追加（models.py と一致）。
- **`components/FileTree.tsx` 全面実装**（プレースホルダを置換）:
  - マウント時 + 「更新」ボタン + `refreshKey` 変化時に `listFiles()`。
  - `path` を `/` で分割して簡易ツリー表示（フォルダ折りたたみは任意、最低限フラット可）。
  - クリックでプレビュー: `kind==='image'` → `fetchImageObjectUrl` を `<img>`（unmount/切替で revoke）、
    それ以外 → `fetchFileContent` の `text` を `<pre><code>`（language ラベル付き、csv は先頭数行）。
  - **ダウンロード**: 取得済みバイト/テキストから `Blob` → `<a download>`。
  - **読み取り専用**（削除UIを置かない §3.4）。失敗は `ApiError.detail` 表示（無言失敗禁止）。
- `App.tsx`: `refreshKey` を持ち、`runner.result` 変化（＝実行完了で `generated_files` が増え得る）で
  bump して FileTree に渡す。手動更新ボタンも用意。

### 3.3 注意
- 一覧は最新順・上限あり（サーバ既定）。フロントは受領順を尊重。
- 画像 object URL は必ず revoke（`useRunner` の figures と同じ規律）。

---

## 4. ギャップ③: 追加対話（会話継続 §3.1/§3.2/§4 step5）

### 4.1 契約（既存・無改修）
- `POST /api/propose`:
  - 初回: `{ intent_object }`
  - 継続: `{ continuation_query, prior_statistical_results, prior_r_script }`
  - res 共通: `{ analysis_proposal{ explanation_markdown, code_candidates[], recommended_candidate_id },
    r_script_provenance{ …, reason } }`（**失敗時も `reason` 必須**、§5）。
  型は `api/types.ts` に既存（`ProposeRequest.continuation_query / prior_*`）。

### 4.2 フロント変更（要・状態設計）
継続には「直近実行の統計結果」と「直近実行した R スクリプト」が要る。
- `useRunner.ts`: 既存 `lastIntent` に倣い **`lastScript: string`** を追加
  （`runCode(code)` で実行したコードを保持）。返り値に含める。
- `App.tsx`: ChatPane へ以下を供給:
  - `priorStats={runner.result?.statistical_results ?? null}`
  - `priorScript={runner.lastScript}`
- `components/ChatPane.tsx`: **「継続を既定＋明示リセット」モデル**で送信先を決める（R-1 で確定）。
  - **既定は継続**: 直近実行で `priorStats`（統計結果）が有る間は、以降の送信を自動的に
    **追加解析（continuation_query）**として扱う。毎ターンの分類操作は課さない。
  - **明示リセット**: チャット上部に常時 **「＋ 新しい解析」** コントロールを置く。押すと
    文脈（priorStats/priorScript の紐付け）を解除し、**次の1通を新規 intent** に戻す。
    その後 run が走れば再び継続が既定になる（新しい系譜に対して sticky）。
  - **土台チップ（基準の可視化）**: composer 直上に「いま何を土台にしているか」を常時表示。
    文言は既存 `intentSummary()`（`natural_language_summary`／objective 等）＋直近の検定名などから
    生成（例: 「土台: 男女間で収縮期血圧を比較 / t検定」）。土台チップ横に「新しい解析」を併置。
  - **継続の実行**: `client.propose({ continuation_query: text,
    prior_statistical_results: priorStats, prior_r_script: priorScript })` を呼び、
    返った `analysis_proposal` を**既存の proposal 描画（候補＋挿入/実行ボタン）で再利用**。
    候補の実行時 intent は `runner.lastIntent` を引き継ぐ。
  - **継続が使えない場合**: 直近 run が失敗／統計結果なし（`priorStats` が空）のときは継続を有効化せず、
    intent モードのまま（土台チップに「統計結果なし」を示す）。
  - 生成失敗は既存同様 `r_script_provenance.reason` を吹き出し表示（無言失敗禁止）。

### 4.3 会話フロー（確定像: 継続既定＋リセット）
```
[初回]        user prompt ─POST /api/intent→ confirm/clarify ─→ propose(intent_object)
                           → 候補 → 挿入/実行 → run → statistical_results
[結果あり]    以降の送信は既定で継続:
              user「タイトルを変えて」─POST /api/propose(continuation_query, prior_stats, prior_script)
                           → 候補 → 実行 → 新しい statistical_results（土台が更新される）
[話題を変える] [＋ 新しい解析] を押す → 文脈リセット → 次の1通は POST /api/intent（新規系譜へ）
```
ユーザーが意識的に操作するのは**話題を変える瞬間だけ**。現在の土台はチップで常時可視化される。

---

## 5. リスクと設計判断

| ID | 論点 | 判断 / 推奨 |
|----|------|------------|
| R-1 | 継続 vs 新規の判定 | **確定: 継続を既定＋明示「新しい解析」リセット＋土台チップ**。毎ターン分類させず、話題変更時のみ1操作。現在の基準はチップで常時可視化し意図ズレに即気づける（自動判定＝誤爆大、毎回2択＝操作過多を排す）。 |
| R-2 | データ投入の入口形態 | §5「別入口」に沿い **Header「解析データ」→モーダル**（ペイン増設より軽い）。 |
| R-3 | ファイルプレビューの重さ | テキストは `<pre>` で十分（Monaco 読み取り専用は任意）。画像 object URL は revoke 必須。 |
| R-4 | multipart 送信 | `uploadDataset` で **Content-Type を手動設定しない**（境界崩れ防止）。 |
| R-5 | 生データ露出 | dataset res は集計メタのみ。**行データを描画するコードを書かない**（§5, CLAUDE.md）。 |
| R-6 | バックエンド無改修 | 3 ギャップとも既存 API で充足。**Agent/スキーマ/セキュリティは触らない**。 |

---

## 6. テスト計画（Playwright E2E, API はスタブ／実データはハーネス）

- **①** モーダルで CSV アップロード → 列メタ表示 / 以後の `POST /api/intent` に
  `dataset_uploaded:true` が載る / 422（PII拒否）で理由表示。行データが DOM に出ないことを確認。
- **②** `GET /api/files` 一覧表示 → テキスト/画像プレビュー → ダウンロード可 / 削除UIが無い /
  run 後に一覧が更新される（refreshKey）。パス不正時のエラー表示。
- **③** run で `statistical_results` 取得後、「追加解析として送信」→
  `POST /api/propose` の body に `continuation_query`＋`prior_*` が載る / 候補が描画される /
  「新しい解析」選択時は `POST /api/intent` に戻る / 失敗時 `reason` 表示。
- 既存 E2E（shell/phase3/phase4/phase6）を**回帰なしで維持**。`tsc`・`vite build`・
  バックエンド pytest（report/api）緑を維持。

---

## 7. 完了の定義（本フェーズ）

- 3 ギャップがフロントで配線され、上記 E2E が緑。
- 既存テスト回帰なし、`tsc -b --noEmit` と `vite build` 成功。
- バックエンド・Agent・スキーマ・セキュリティ**無改修**（差分は `frontend/` のみ）。
- 生データ行を UI に出さない（§5）／`dataset_uploaded` が実状態を反映。
- 実装は `prompts/redesign/phase8_frontend_gaps.md` の R8-1〜R8-3 に従う。
