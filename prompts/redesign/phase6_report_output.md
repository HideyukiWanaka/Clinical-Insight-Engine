# CIE 再設計 — Phase 6: 報告書フォーマット出力
# File: prompts/redesign/phase6_report_output.md
# Version: 1.0.0

---

## PROMPT R6-0: ブランチ作成

```
git checkout main && git pull origin main
git checkout -b feature/redesign-phase-6-report
```

---

## PROMPT R6-1: Output & Format パネルと原稿生成

```
統計結果を、利用者が普段使う報告書フォーマットへ出力します。既存Reporting資産を接続。

### 読み込むべき仕様ファイル
- spec/ui/ide-workbench-spec.md（§3.5 Output & Format）
- spec/api/rest-api-contract.md（§3.5 /api/report）
- cie/agents/reporting.py（payload契約: statistical_results, intent_object,
  reporting_checklist_id, target_journal_style, reporting_skill_id）
- cie/ui/screens/format_selection.py（チェックリスト/雑誌スタイル/ユーザーSkillの選択肢）

### 実装範囲
- ✅ フロント Output & Format ペイン: 報告チェックリスト（CONSORT/STROBE/…）、
     雑誌スタイル（APA/AMA/Vancouver）、ユーザーSkill を選択。format_selection.py の
     選択肢定義をフロントに移植（値は同一）。
- ✅ 「原稿に変換」ボタン → POST /api/report → manuscript_sections を表示。
     コピー可能な形（テキスト/コードブロック）。自動クリップボード連携はしない。
- ✅ ユーザーSkill登録時はそれが優先（既存 ReportingAgent の reporting_skill_id 経由）。
- ❌ 新しいフォーマットロジックは作らない。既存 ReportingAgent をそのまま呼ぶ。

### 踏襲パターン
- 選択肢の値・ラベルは cie/ui/screens/format_selection.py:21-45 と一致させる。
- Reporting呼び出しは Phase 1 の /api/report ハンドラ（直接呼び出しパターン）を使う。

### ハーネス（実データE2E）
- 統計結果（実 or スタブ）→ APA/STROBE を選択→「原稿に変換」→
  manuscript_sections が生成・表示される。
- ユーザーSkill を登録した状態→そのスタイルが反映されることを確認。

### 仕様→実装マッピング（完了基準）
| 項目 | 実装 | 状態 |
|------|------|------|
| フォーマット選択UI | FormatPane.tsx | ⬜ |
| 原稿生成 | /api/report 連動 | ⬜ |
| ユーザーSkill優先 | reporting_skill_id 配線 | ⬜ |
| コピー可能表示 | 原稿表示コンポーネント | ⬜ |

### 検証（必須）
- 選択フォーマットで原稿セクションが生成される。
- ユーザーSkill優先が効く。
- pytest 緑を維持。
```
