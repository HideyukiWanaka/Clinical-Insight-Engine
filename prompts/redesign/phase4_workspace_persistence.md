# CIE 再設計 — Phase 4: Rワークスペース永続化（.RData）
# File: prompts/redesign/phase4_workspace_persistence.md
# Version: 1.0.0

---

## PROMPT R4-0: ブランチ作成

```
git checkout main && git pull origin main
git checkout -b feature/redesign-phase-4-workspace
```

---

## PROMPT R4-1: .RData 保存/復元 と Workspace/Data 表示

```
実行をまたいで変数を保持する仕組みを、可視ファイル(.RData)で実装します。

### 読み込むべき仕様ファイル
- spec/runtime-workspace-persistence.md（全体）
- cie/runtime/r_executor.py（RT-002 スクリプト無改変, 禁止パターン, --vanilla, env）
- spec/runtime.yaml（mandatory_flags, OUTPUT_DIR ephemeral:false）

### 実装範囲
- ✅ 実行ラッパ（cie/runtime のスクリプト生成/ラッパ層。executor 本体は無改修）に、
     persist_workspace=True のとき load()/save.image()/workspace_summary.json 出力の
     Rコードを **上流で付与**する（spec §2.1 のコードを使用）。
- ✅ API /api/run の persist_workspace を配線。既定はプロジェクト単位でTrue。
- ✅ フロント Workspace/Data ペイン: workspace_summary.json を読んで変数一覧
     （名前・型・要約）を表示。
- ✅ 「ワークスペースをリセット」: .RData と workspace_summary.json を削除するAPI＋UI。
- ❌ 常駐Rプロセスは作らない（ADR-0005 原則2）。

### 踏襲パターン / 制約（重要）
- executor はスクリプトを改変してはならない（RT-002）→ 付与は必ず上流ラッパで。
- パスは file.path(Sys.getenv("OUTPUT_DIR"), ".RData") のみ（絶対パス禁止, Sys.setenv禁止）。
- load(/save.image( は禁止リストに無く静的検証を通過する（source( は禁止なので使わない）。
- --vanilla のため明示的 load() が必須（自動復元は効かない）。

### ハーネス（実データE2E, R必須）
```r
# 1回目に投入するRコード:
data <- read.csv(file.path(Sys.getenv("WORKSPACE_DIR"),"dataset.csv"))
data$bmi_cat <- cut(data$bmi, c(0,18.5,25,30,100))
# 2回目に投入するRコード（CSV再読込しない）:
table(data$bmi_cat)          # 1回目の派生列が残っていれば動く
```
- ラッパ経由で1回目→2回目を実行し、2回目が bmi_cat を参照できることを確認。
- workspace_summary.json に data / bmi_cat 等が出て、UIに表示されることを確認。
- 「リセット」後、2回目が「オブジェクトが無い」で失敗する（空ワークスペース）ことを確認。

### 仕様→実装マッピング（完了基準）
| 項目 | 実装 | 状態 |
|------|------|------|
| load/save.image 付与 | runtime ラッパ層 | ⬜ |
| workspace_summary 出力 | ラッパ層のRコード | ⬜ |
| persist_workspace 配線 | /api/run | ⬜ |
| 変数一覧表示 | WorkspacePane.tsx | ⬜ |
| リセット | /api/workspace/reset + UI | ⬜ |

### 検証（必須）
- 上記ハーネスが実Rで通る。
- 生成される .RData パスが静的検証（絶対パス/ Sys.setenv 禁止）を通過する。
- pytest 緑を維持。再現性: 監査ログに実行スクリプト列が残ること。
```
