# Component Library
# File: spec/ui/component-library.md
# Version: 1.0.0
# Status: Draft
# Parent: architecture/ui-model.md
# Related: spec/ui/ui-principles.md, spec/ui/screen-specifications.md

---

## 目的

本文書はCIE Platformで使用するUIコンポーネントの定義・Props仕様・
状態定義・使用規則を定める。

コンポーネントはPresentation Layer専用であり、
ビジネスロジックを持たない（component-model.md準拠）。
すべてのデータはAgentの出力スキーマから受け取り、表示のみを行う。

---

## コンポーネント一覧

| グループ | コンポーネント | 使用画面 |
|---------|-------------|---------|
| Layout | StatusBar, LeftPane, RightPane | 全画面 |
| Navigation | ProjectCard, WorkflowStepCard | SCR-01, SCR-03 |
| Approval | ApprovalPanel, ConfirmDialog | SCR-02, 05, 06 |
| Data | MissingValueChart, QualityIssueCard | SCR-04 |
| Analysis | AssumptionChecklist, MethodCard | SCR-05 |
| Results | TraceableValue, AIContentBlock, UnresolvedItem | SCR-06 |
| Audit | AuditTimeline, AuditEventRow | SCR-07 |
| Common | StatusBadge, ConfidenceIndicator, AgentActivityFeed | 複数画面 |

---

## Layout コンポーネント

### StatusBar

全画面共通のヘッダーバー。

**Props:**
```typescript
interface StatusBarProps {
  projectName: string | null;
  executionId: string | null;
  connectionStatus: 'online' | 'offline' | 'checking';
  securityEvents: SecurityEvent[];
  workflowState: WorkflowState | null;
}
```

**表示仕様:**
```
┌────────────────────────────────────────────────────────────────┐
│ CIE  [プロジェクト名]  |  実行ID: ex-001  |  ● オンライン  |  🔒  │
└────────────────────────────────────────────────────────────────┘
```

- `connectionStatus = 'offline'`: グレードット + テキスト色 `--cie-gray-600`
- `securityEvents`にCRITICAL/BREACHが含まれる場合: バー全体が点滅
- 高さ: 40px固定

---

### AgentActivityFeed

右ペインに常時表示されるリアルタイムActivity Feed。

**Props:**
```typescript
interface AgentActivityFeedProps {
  events: AgentEvent[];
  maxItems?: number;        // default: 50
  autoScroll?: boolean;     // default: true
}

interface AgentEvent {
  timestamp: string;        // ISO8601
  agentId: string;
  action: string;
  status: 'success' | 'failed' | 'running' | 'waiting';
  summary: string;
  severity: 'INFO' | 'WARNING' | 'CRITICAL' | 'BREACH';
}
```

**表示仕様:**
```
14:32:07  planner      intent_extracted   confidence=0.91
14:32:15  data-quality quality_gate       ✓ passed
14:32:31  statistics   method_selected    welch_t_test
```

- フォント: JetBrains Mono, 12px
- WARNING行: 背景 `#FFF7ED`
- CRITICAL行: 背景 `#FEF2F2`
- BREACH行: 背景 `#DC2626`, テキスト白

---

## Navigation コンポーネント

### ProjectCard

SCR-01のプロジェクト一覧に表示される1プロジェクトのカード。

**Props:**
```typescript
interface ProjectCardProps {
  projectId: string;
  projectName: string;
  workflowState: WorkflowState;
  lastUpdated: string;
  approvalPendingCount: number;
  qualityScore: number | null;
  onClick: () => void;
}

type WorkflowState =
  | 'draft' | 'validated' | 'planned' | 'running'
  | 'waiting_for_human' | 'retrying' | 'completed'
  | 'failed' | 'cancelled' | 'archived';
```

**状態別スタイル:**
```typescript
const cardBorderColors: Record<WorkflowState, string> = {
  completed:         'var(--cie-success)',
  running:           'var(--cie-blue-500)',
  waiting_for_human: 'var(--cie-approval)',
  failed:            'var(--cie-critical)',
  retrying:          'var(--cie-warning)',
  draft:             'var(--cie-gray-200)',
  // ...
};
```

**承認待ちバッジ:**
- `approvalPendingCount > 0` のとき、紫バッジ（`--cie-approval`）でカウントを表示
- `approvalPendingCount = 0` のとき非表示

---

### WorkflowStepCard

SCR-03のワークフローDAGに表示される各ステップカード。

**Props:**
```typescript
interface WorkflowStepCardProps {
  nodeId: string;
  nodeName: string;
  nodeType: 'task' | 'decision' | 'approval' | 'evaluation';
  agentId: string;
  status: WorkflowState;
  elapsedSeconds: number | null;
  hasDecisionBranch: boolean;
  onClickDetail: () => void;
}
```

**表示仕様（状態別）:**

| status | アイコン | 背景色 | 追加要素 |
|--------|---------|--------|---------|
| pending | ○ グレー | 白 | — |
| running | ⟳ アニメ | `--cie-blue-100` | 経過時間カウンター |
| completed | ✓ 緑 | 白 | — |
| failed | ✕ 赤 | `#FEF2F2` | エラー概要（1行） |
| waiting_for_human | 🟣 紫 | `#F3F4FF` | 「承認が必要」テキスト |

**タイムアウト警告:**
- `elapsedSeconds > 270` (残り30秒): カウンター赤表示
- `elapsedSeconds > 240` (残り60秒): カウンターオレンジ表示

---

## Approval コンポーネント

### ApprovalPanel

人間承認が必要な全場面で使用される統一コンポーネント。UP-002の実装。

**Props:**
```typescript
interface ApprovalPanelProps {
  title: string;                    // 承認対象の説明
  isIrreversible: boolean;          // true: 「取り消せません」を表示
  requiresCheckbox: boolean;        // default: true
  checkboxLabel?: string;           // default: "内容を確認しました"
  onApprove: () => void;
  onCancel: () => void;
  isLoading?: boolean;              // 承認処理中
  children?: ReactNode;             // 追加の詳細情報
}
```

**レンダリング:**
```
┌────────────────────────────────────────────────────┐
│ 🟣  HUMAN APPROVAL REQUIRED                       │  ← bg: #7C3AED, text: white
├────────────────────────────────────────────────────┤
│                                                    │
│  {title}                                           │
│                                                    │
│  {isIrreversible && "この操作は取り消せません。"}  │  ← 赤テキスト
│                                                    │
│  {children}                                        │
│                                                    │
│  ☐  {checkboxLabel}                               │
│                                                    │
│  [キャンセル]                   [承認して実行]     │  ← 承認ボタンはcheckbox=trueで活性
└────────────────────────────────────────────────────┘
```

**承認ボタンの活性化条件:**
```typescript
const isApproveEnabled = !requiresCheckbox || isChecked;
```

**使用規則:**
- 右ペインに配置する（全画面統一）
- `waiting_for_human`状態の間は右ペインを折りたたみ不可にする
- 承認完了後に `onApprove` を呼び出す前に確認ダイアログを表示する

---

### ConfirmDialog

ApprovalPanel内の最終確認ダイアログ。

**Props:**
```typescript
interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmLabel?: string;   // default: "実行する"
  cancelLabel?: string;    // default: "キャンセル"
  onConfirm: () => void;
  onCancel: () => void;
}
```

**WAI-ARIA:**
```html
<div role="alertdialog" aria-modal="true" aria-labelledby="dialog-title">
```

---

## Data コンポーネント

### MissingValueChart

SCR-04で使用する欠損値可視化チャート。

**Props:**
```typescript
interface MissingValueChartProps {
  columns: ColumnMetadata[];
  criticalThreshold?: number;   // default: 20.0
  warningThreshold?: number;    // default: 5.0
}

interface ColumnMetadata {
  varN: string;                 // e.g. "var_1"
  missingRatePct: number;
}
```

**表示仕様:**
- Rの`okabe_ito`カラーパレットに対応したWeb配色を使用
- `missingRatePct >= criticalThreshold`: `--cie-critical` (赤バー)
- `missingRatePct >= warningThreshold`: `--cie-warning` (オレンジバー)
- それ以外: `--cie-success` (緑バー)
- 閾値ラインは縦破線で表示

---

### QualityIssueCard

Critical IssueまたはWarningを1件表示するカード。

**Props:**
```typescript
interface QualityIssueCardProps {
  finding: Finding;
  onAcknowledge?: () => void;   // "理解した上で進む"の場合のみ
}

interface Finding {
  findingId: string;
  severity: 'critical' | 'advisory';
  description: string;
  affectedComponent: string;
  humanResolutionRequired: boolean;
}
```

**Critical IssueはデフォルトExpanded、WarningはデフォルトCollapsedでWarningSummaryのみ表示。**

---

## Results コンポーネント

### TraceableValue

SCR-06で統計値をクリック可能な参照リンクとして表示するインラインコンポーネント。

**Props:**
```typescript
interface TraceableValueProps {
  displayValue: string;         // 表示するテキスト (e.g. "p = 0.021")
  sourceField: string;          // execution_resultのフィールドパス
  sourceValue: unknown;         // 実際の値
  executionId: string;
}
```

**表示仕様:**
- インラインで**太字**表示 + 下線（`border-bottom: 1px dashed --cie-blue-500`）
- ホバー時: `cursor: help` + ツールチップに「クリックで出典を表示」
- クリック時: TraceabilityPopoverを表示

---

### AIContentBlock

AI生成テキストセクションを囲むラッパーコンポーネント。

**Props:**
```typescript
interface AIContentBlockProps {
  isEdited: boolean;            // 人間が編集した場合はtrue
  children: ReactNode;
}
```

**表示仕様:**
- `isEdited = false`: 左ボーダー `4px solid --cie-ai-teal` + ヘッダー右端に 🤖
- `isEdited = true`: ボーダー・アイコンを消去して通常テキスト表示

---

### UnresolvedItem

SCR-06の右マージンに表示されるunresolved_itemアノテーション。

**Props:**
```typescript
interface UnresolvedItemProps {
  itemId: string;
  description: string;
  anchorRef: string;            // 本文中のアンカー要素ID
  onResolve: () => void;
}
```

**表示仕様:**
- 黄色背景 `#FFFBEB` + オレンジ左ボーダー
- 「解決済みにする」ボタン: クリックでグレーアウト + 取り消し線

---

## Common コンポーネント

### StatusBadge

ワークフロー状態・品質スコアを一貫して表示するバッジ。

**Props:**
```typescript
interface StatusBadgeProps {
  type: 'workflow' | 'quality';
  value: WorkflowState | number;
  size?: 'sm' | 'md';   // default: 'md'
}
```

**Workflow状態バッジ:**

| WorkflowState | ラベル | 色 |
|------------|------|-----|
| completed | ✓ 完了 | `--cie-success` |
| running | ⟳ 実行中 | `--cie-blue-500` |
| waiting_for_human | 🟣 承認待ち | `--cie-approval` |
| failed | ✕ 失敗 | `--cie-critical` |
| retrying | ↻ リトライ中 | `--cie-warning` |
| draft | ○ 準備中 | `--cie-gray-400` |

**品質スコアバッジ:**

| スコア範囲 | ラベル | 色 |
|-----------|------|-----|
| 90〜100 | PASS | `--cie-success` |
| 70〜89 | REVIEW | `--cie-warning` |
| 0〜69 | FAIL | `--cie-critical` |

---

### ConfidenceIndicator

Planner Agentのconfidence_scoreを視覚的に表示するコンポーネント。

**Props:**
```typescript
interface ConfidenceIndicatorProps {
  score: number;        // 0.0 - 1.0
  field: string;        // どのフィールドの信頼度か
}
```

**表示仕様:**
- `score >= 0.8`: 緑ドット + スコア
- `0.6 <= score < 0.8`: 黄ドット + スコア + 「確認推奨」
- `score < 0.6`: 赤ドット + 「人間による確認が必要です」
- `score = null`: グレードット + 「未評価」（paired=nullなど）

---

## 実装上の禁止事項（全コンポーネント共通）

1. **ビジネスロジックの禁止:** コンポーネントはAgentの出力を表示するのみ。
   統計計算・方法論判断・セキュリティポリシーの判断をコンポーネント内で行ってはならない。

2. **直接APIコール禁止:** コンポーネントはOrchestratorへのリクエストを
   直接発行しない。全リクエストはViewModelまたはStoreを経由する。

3. **ハードコーディング禁止:** カラー値・閾値・ラベルは
   CSS変数またはconfigから参照する。

4. **承認パネルの転用禁止:** `ApprovalPanel`コンポーネントは
   `permissions.yaml`の`requires_human_approval: true`に対応する
   操作にのみ使用する。

5. **状態定義の独自拡張禁止:** `WorkflowState`の値はorchestrator.yamlの
   `valid_states`と完全に同期させる。
