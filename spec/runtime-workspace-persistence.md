# CIE Platform — Rワークスペース永続化 仕様
# File: spec/runtime-workspace-persistence.md
# Version: 1.0.0
# Governs: cie/runtime/ の実行ラッパ（executorは無改修）
# Basis: ADR-0005 原則2 / spec/runtime.yaml

---

## 1. 目的

「実行と実行をまたいで変数を保持する」（例: 1回目で `data$new_col` を作成 → 2回目で参照）
を、常駐Rプロセスを持たずに実現する。方式は `OUTPUT_DIR` 配下の `.RData` の保存/復元。

**PROJECT_RULES.md Section 6（hidden state 禁止）との関係:** `.RData` はユーザーに見え・
監査でき・削除できる**可視ファイル**であり、隠れた状態ではない。よって禁止に当たらない
（ADR-0005 原則2）。

---

## 2. 実装方式（executor は無改修）

`cie/runtime/r_executor.py` はスクリプト本文を改変してはならない（RT-002）。よって
`load()`/`save.image()` の付与は **上流のスクリプト生成/テンプレラッパ**で行う。

### 2.1 ラッパが付与するコード（`persist_workspace=True` のとき）
- 冒頭:
  ```r
  .cie_img <- file.path(Sys.getenv("OUTPUT_DIR"), ".RData")
  if (file.exists(.cie_img)) load(.cie_img)
  ```
- 末尾:
  ```r
  save.image(file.path(Sys.getenv("OUTPUT_DIR"), ".RData"))
  ```
- 変数一覧の可視化（Workspace/Data パネル用）:
  ```r
  .cie_ws <- lapply(ls(), function(n) {
    obj <- get(n); list(name=n, class=class(obj)[1],
      summary=tryCatch(paste(capture.output(str(obj, max.level=0)), collapse=" "),
                       error=function(e) ""))
  })
  jsonlite::write_json(.cie_ws,
    file.path(Sys.getenv("OUTPUT_DIR"), "workspace_summary.json"), auto_unbox=TRUE)
  ```

### 2.2 既存ガードとの整合（重要）
- `--vanilla`（`spec/runtime.yaml:58` mandatory）は既定の `.RData` 自動復元/保存を無効化する。
  よって**明示的な `load()`/`save.image()`** が必須。
- `Sys.setenv(` は禁止パターン → env 変更は不可。`Sys.getenv("OUTPUT_DIR")` を読むのは可。
- 絶対パス（`/home/`,`/etc/`,`/var/`,`/usr/`,`C:\`,`C:/`）は禁止 → パスは必ず
  `file.path(Sys.getenv("OUTPUT_DIR"), ...)` で構築する。
- `source(` は禁止だが `load(` / `save.image(` は禁止リストに無く、静的検証を通過する。
- `OUTPUT_DIR` は `spec/runtime.yaml` で `ephemeral: false`（永続）。`WORKSPACE_DIR` は
  `ephemeral: true` なので `.RData` の置き場所として使わない。

---

## 3. ライフサイクル / リセット
- 「セッション/プロジェクト単位」で `.RData` を持つ。プロジェクト切替時は別の `OUTPUT_DIR`。
- UIに **「ワークスペースをリセット」** を用意し、`.RData` と `workspace_summary.json` を削除
  （物理削除可。知識の soft-delete 制約とは別領域）。
- 再現性の担保: `.RData` はあくまで利便性のためのキャッシュ。**元データ + 実行した
  Rスクリプト列**が再現の真実源であり、監査ログに残る（PROJECT_RULES.md S.2 再現性）。

---

## 4. セキュリティ
- `.RData` にはユーザーのデータ由来オブジェクトが含まれうるため、`OUTPUT_DIR` は
  既存のサンドボックス権限内に留める。外部送信は一切しない。
- コンソール出力は従来どおり `ContextGuard.sanitize_stdout`（RT-004）でサニタイズ後に配信。

---

## 5. 検証観点
- 実Rで「1回目: 派生列作成 → 2回目: 派生列を参照する解析」がCSV再読込なしに通る。
- `workspace_summary.json` に変数名・型・要約が出力され、UIのWorkspace/Dataに表示される。
- `.RData` パスが絶対パス禁止/`Sys.setenv`禁止に抵触せず静的検証を通過する。
- 「リセット」で `.RData` が消え、次回実行が空ワークスペースから始まる。
