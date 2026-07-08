# CIE 再設計 — Phase 8: フロント未配線ギャップの解消（データ投入・ファイル閲覧・追加対話）
# File: prompts/redesign/phase8_frontend_gaps.md
# Version: 1.0.0
# Design: docs/redesign/phase8_frontend_gaps_design.md
# 前提: Phase 1〜6 マージ済み。バックエンド14ルートは実装済・本フェーズは frontend/ のみ変更。

---

## PROMPT R8-0: ブランチ作成

```
git checkout main && git pull origin main
git checkout -b feature/redesign-phase-8-frontend-gaps
```

---

## PROMPT R8-1: データセット投入口（POST /api/dataset 配線）

```
「自分のデータで解析」を成立させます。CSVアップロードUIを追加し、以降の Planner 呼び出しに
列メタが渡るようにします。バックエンドは無改修。

### 読み込むべき仕様ファイル
- spec/ui/ide-workbench-spec.md（§3.1 前提, §5 解析データ入口・生データ非表示）
- spec/api/rest-api-contract.md（§3.1 /api/dataset は intent の前提, dataset 節）
- docs/redesign/phase8_frontend_gaps_design.md（§2）
- cie/api/routes/dataset.py（res契約: dataset_id/row_count/column_count/columns, 集計のみ）
- cie/api/routes/intent.py（サーバが app.state.dataset_context を自動参照する点）
- frontend/src/api/client.ts（fetch/ApiError/readErrorEnvelope パターン）
- frontend/src/components/Header.tsx（「解析データ」ダミーボタン）
- frontend/src/components/ChatPane.tsx（dataset_uploaded:false ハードコード箇所）

### 実装範囲
- ✅ client.uploadDataset(file: File): POST /api/dataset を multipart で送信。
     X-CIE-Token のみ付与し **Content-Type は手動設定しない**。非2xxは既存 ApiError 整形。
- ✅ types.ts: DatasetUploadResponse / DatasetColumn（columns は build_dataset_context 出力を素直に写す）。
- ✅ components/DatasetModal.tsx（新規）: Header「解析データ」で開く。ファイル選択→アップロード→
     **列メタ（名前・型・要約統計）をテーブル表示**。行データは絶対に表示しない（§5）。
     失敗（422 PII拒否含む）は ApiError.detail を表示（無言失敗禁止 §5）。
- ✅ App.tsx: datasetInfo 状態を保持。Header に onOpenDataset、ChatPane に datasetUploaded を供給。
- ✅ Header.tsx: 「解析データ」ボタンに onClick 配線（取り込み済みバッジは任意）。
- ✅ ChatPane.tsx: dataset_uploaded を props.datasetUploaded に置換。
- ❌ バックエンド・build_dataset_context・intent の payload は無改修。

### 踏襲パターン
- 送信/エラーは client.ts の post()/readErrorEnvelope と同じ作法（ApiError＋detail を UI に出す）。
- 入口分離は §5（解析データと参考資料は別入口）。

### ハーネス（実データE2E）
- Playwright + 実API:
  1. Header「解析データ」→モーダル→sample_data.csv をアップロード→列メタが表示される
  2. その後チャットで意図入力→ POST /api/intent の body に dataset_uploaded:true が載る
  3. 行データ（セル値）が DOM に一切出ないことを確認（集計メタのみ）
  4. わざと空CSV/不正で 400/422 → 理由が画面に出る（無言失敗しない）

### 仕様→実装マッピング（完了基準）
| 項目 | 実装 | 状態 |
|------|------|------|
| アップロードAPI | client.uploadDataset | ⬜ |
| 投入モーダル | DatasetModal.tsx | ⬜ |
| Header配線 | Header onOpenDataset | ⬜ |
| dataset_uploaded 実状態化 | ChatPane props | ⬜ |
| 生データ非表示 | 列メタのみ描画 | ⬜ |

### 検証（必須）
- アップロード後、intent に dataset_uploaded:true が載る。
- 生データ行が UI に出ない（§5）。失敗理由が必ず表示される。
- 既存E2E回帰なし・tsc/vite build 成功・バックエンド pytest 緑を維持。
```

---

## PROMPT R8-2: ファイルツリー（GET /api/files(/content) 配線, §3.4）

```
右上ペインのプレースホルダを実装に置換します。生成物の一覧・プレビュー・DLを可能に。読み取り専用。

### 読み込むべき仕様ファイル
- spec/ui/ide-workbench-spec.md（§3.4 ファイルツリー・読み取り専用・削除UIなし）
- spec/api/rest-api-contract.md（§3.6 /api/files, §3.7 /api/files/content・パストラバーサル禁止）
- docs/redesign/phase8_frontend_gaps_design.md（§3）
- cie/api/routes/files.py（一覧/コンテンツの res 契約, kind の値）
- frontend/src/api/client.ts（fetchImageObjectUrl の revoke 規律を流用）
- frontend/src/components/FileTree.tsx（置換対象のプレースホルダ）
- frontend/src/useRunner.ts / App.tsx（run 完了を検知して更新する導線）

### 実装範囲
- ✅ client.listFiles(): GET /api/files → FilesResponse。
     client.fetchFileContent(path): GET /api/files/content → {text, language}。
     画像は既存 fetchImageObjectUrl を流用（object URL は必ず revoke）。GET も X-CIE-Token 付与。
- ✅ types.ts: FileEntry / FilesResponse / FileContentResponse（models.py と一致）。
- ✅ FileTree.tsx 全面実装:
     - マウント時 + 「更新」ボタン + refreshKey 変化で listFiles()。
     - path を分割した簡易ツリー（最低限フラット可）。
     - クリックでプレビュー: image→<img>（revoke）, それ以外→<pre><code>（language付, csvは先頭数行）。
     - ダウンロード（Blob→<a download>）。**読み取り専用（削除UIを置かない §3.4）**。
     - 失敗は ApiError.detail 表示（無言失敗禁止）。
- ✅ App.tsx: refreshKey を持ち、runner.result 変化（generated_files 増加）で bump→FileTree へ。
- ❌ バックエンド無改修。パス検証はサーバ側に委ねる（フロントは相対 path を渡すだけ）。

### 踏襲パターン
- object URL の revoke は useRunner の figures と同じ規律。
- 読み取り専用は §3.4（現行 file_browser.py と同思想）。

### ハーネス（実データE2E）
- Playwright + 実API（+可能なら実Rで png/csv を生成）:
  1. run で図/ファイル生成 → 一覧に現れる（refreshKey）
  2. テキスト(.R/.json)をクリック→コードプレビュー、png をクリック→画像表示
  3. ダウンロードボタンが機能する / 削除UIが存在しない
  4. 不正 path（例: ../etc）で content 取得→サーバ 400→理由表示（無言失敗しない）

### 仕様→実装マッピング（完了基準）
| 項目 | 実装 | 状態 |
|------|------|------|
| 一覧取得 | client.listFiles | ⬜ |
| コンテンツ取得 | client.fetchFileContent | ⬜ |
| ツリー+プレビュー | FileTree.tsx | ⬜ |
| 実行後の更新 | App refreshKey | ⬜ |
| 読み取り専用 | 削除UIなし | ⬜ |

### 検証（必須）
- 一覧・プレビュー・DLが動作、削除UIが無い。run 後に一覧が更新される。
- 画像 object URL が revoke される。失敗理由が必ず表示される。
- 既存E2E回帰なし・tsc/vite build 成功・バックエンド pytest 緑を維持。
```

---

## PROMPT R8-3: 追加対話（continuation_query 配線, §3.2/§4 step5）

```
実行後の「タイトルを変えて」等の追加解析を、intent 再解析ではなく会話継続として往復させます。

### 読み込むべき仕様ファイル
- spec/ui/ide-workbench-spec.md（§3.1 2回目以降, §3.2, §4 step5）
- spec/api/rest-api-contract.md（§3.2 /api/propose の継続契約・reason 必須）
- docs/redesign/phase8_frontend_gaps_design.md（§4, リスク R-1）
- frontend/src/api/types.ts（ProposeRequest.continuation_query / prior_* は定義済）
- frontend/src/components/ChatPane.tsx（現状は初回 intent_object のみ送信）
- frontend/src/useRunner.ts（lastIntent の追加パターンを踏襲）

### 実装範囲
- ✅ useRunner.ts: lastScript を追加（runCode で実行したコードを保持）。返り値に含める。
- ✅ App.tsx: ChatPane へ priorStats(=runner.result?.statistical_results) と
     priorScript(=runner.lastScript) を供給。
- ✅ ChatPane.tsx: 送信モード分岐。
     - 実行結果が有る間は「追加解析として送信」/「新しい解析として送信」の**明示切替**（R-1: 暗黙推論しない）。
     - 追加解析時: client.propose({continuation_query, prior_statistical_results, prior_r_script}) を呼び、
       返った analysis_proposal を**既存の proposal 描画（候補＋挿入/実行）で再利用**。候補実行の intent は lastIntent を継承。
     - 新規時: 従来の intent→propose フロー。
     - 生成失敗は r_script_provenance.reason を吹き出し表示（無言失敗禁止）。
- ❌ バックエンド・propose の契約は無改修（型は既存を使用）。

### 踏襲パターン
- lastScript は lastIntent（Phase 6 で追加）と同じ「runCode で状態保持→返却」パターン。
- proposal の描画・挿入/実行ボタンは既存 MessageView を再利用（新規ロジックを作らない）。

### ハーネス（実データE2E）
- Playwright + 実API:
  1. 初回 intent→propose→run で statistical_results 取得
  2. 「追加解析として送信」で追送→ POST /api/propose body に
     continuation_query＋prior_statistical_results＋prior_r_script が載る
  3. 新しい候補が描画され、挿入/実行が従来通り動く
  4. 「新しい解析として送信」を選ぶと POST /api/intent に戻る
  5. 生成失敗時に reason が表示される（無言失敗しない）

### 仕様→実装マッピング（完了基準）
| 項目 | 実装 | 状態 |
|------|------|------|
| lastScript 保持 | useRunner | ⬜ |
| prior_* 供給 | App→ChatPane | ⬜ |
| 継続/新規の明示切替 | ChatPane | ⬜ |
| propose 継続呼び出し | client.propose(continuation) | ⬜ |
| 候補描画の再利用 | 既存 MessageView | ⬜ |

### 検証（必須）
- 追加解析で continuation_query＋prior_* が API に載る。新規選択で intent に戻る。
- 失敗時に reason が必ず表示される。
- 既存E2E回帰なし・tsc/vite build 成功・バックエンド pytest 緑を維持。
```

---

## PROMPT R8-4: 仕上げ（回帰・整合）

```
### 実装範囲
- ✅ frontend E2E 全緑（shell/phase3/phase4/phase6 + 新規 phase8-* の3本）。
- ✅ tsc -b --noEmit / vite build 成功。バックエンド pytest（report/api）緑を維持。
- ✅ 差分は frontend/ のみ（バックエンド・Agent・スキーマ・セキュリティ無改修）を確認。
- ✅ docs/redesign/phase8_frontend_gaps_design.md の完了定義（§7）を満たす。
- ❌ 知識取り込みUI（/api/knowledge/*）は本フェーズ対象外（別フェーズ）。

### 検証（必須）
- 生データ行が UI に出ない（§5）。全失敗経路で理由が表示される（無言失敗禁止）。
- README（prompts/redesign）フェーズ表に Phase 8 を追記（任意）。
```
