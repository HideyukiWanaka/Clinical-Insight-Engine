// Run-error explainer (presentation layer, §5「失敗を明示」).
//
// The runtime's static security validator (cie/runtime/r_executor.py) rejects a
// script BEFORE execution and returns a terse, security-worded reason such as
// "Hard-coded Unix absolute path (string literal starting with /)". Those words
// are accurate for an auditor but opaque to a first-time analyst — the same
// guard fires for a harmless `gsub("/", "-", x)` as for a real path traversal.
//
// This module never changes detection (that stays in the backend, the single
// source of truth). It only TRANSLATES a matched reason into an actionable
// cause + fix + example so the human knows immediately what to change. Matching
// is on stable substrings emitted by the validator; anything unmatched falls
// through to `null` and the raw reason is still shown verbatim.

export interface RunErrorGuidance {
  /** Short human title of the category. */
  title: string;
  /** Why the script was rejected, in plain language. */
  cause: string;
  /** Concrete fix the analyst can apply now. */
  fix: string;
  /** Optional before→after snippet. */
  example?: string;
  /** How likely this is to appear in ordinary (non-malicious) analysis. */
  likelihood: "high" | "medium" | "low";
}

interface Matcher {
  test: (reason: string) => boolean;
  guidance: RunErrorGuidance;
}

// Ordered by specificity. Substrings are copied from the validator's messages
// (_FORBIDDEN in r_executor.py) so a message wording change is easy to re-sync.
const MATCHERS: Matcher[] = [
  {
    test: (r) => r.includes("warning suppression not permitted"),
    guidance: {
      title: "警告の全体抑制は使えません",
      cause:
        "options(warn=-1) などで警告をまとめて消す書き方が含まれています。監査性のため全体抑制は禁止されています。",
      fix: "options(warn=…) を削除してください。特定の式だけ静めたい場合は suppressWarnings(...) でその式を包みます（こちらは許可されています）。",
      example: 'options(warn=-1); x <- as.numeric(v)\n→  x <- suppressWarnings(as.numeric(v))',
      likelihood: "high",
    },
  },
  {
    test: (r) =>
      r.includes("string literal starting with /") ||
      r.includes("Unix absolute path"),
    guidance: {
      title: '文字列が「/」で始まっています（絶対パス保護）',
      cause:
        "「/」で始まる文字列リテラルが検出されました。区切り文字やラベル・置換パターンの「/」でも同じ保護に触れます（例: gsub(\"/\", …)）。",
      fix: 'その「/」を別の記号にするか、先頭の「/」を避けてください。ファイルパスは file.path(Sys.getenv("WORKSPACE_DIR"), "ファイル名") で組み立てます（文字列に絶対パスを直書きしない）。',
      example: 'gsub("/", "-", x)\n→  gsub("[/]", "-", x)   または  chartr("/", "-", x)',
      likelihood: "medium",
    },
  },
  {
    test: (r) => r.includes("Windows absolute path"),
    guidance: {
      title: "Windows の絶対パスは直書きできません",
      cause: '"C:\\\\…" のようなドライブ付き絶対パスが文字列に含まれています。',
      fix: 'パスは file.path(Sys.getenv("WORKSPACE_DIR"), "ファイル名") で相対的に組み立ててください。',
      likelihood: "low",
    },
  },
  {
    test: (r) => r.includes("Home-directory shorthand") || r.includes("path.expand"),
    guidance: {
      title: "ホームディレクトリ（~）は使えません",
      cause: '"~/…" やホーム展開（path.expand）はサンドボックス外を指すため禁止です。',
      fix: 'file.path(Sys.getenv("WORKSPACE_DIR"), …) / file.path(Sys.getenv("OUTPUT_DIR"), …) を使ってください。',
      likelihood: "low",
    },
  },
  {
    test: (r) => r.includes("shell escape not permitted"),
    guidance: {
      title: "シェル呼び出しはできません",
      cause: "system() / system2() / shell() など OS シェルへ抜ける呼び出しが含まれています。",
      fix: "OS コマンドは使わず、R の関数だけで完結させてください（ファイル操作も read.csv 等 R 側で）。",
      likelihood: "low",
    },
  },
  {
    test: (r) => r.includes("unapproved installation") || r.includes("install.packages"),
    guidance: {
      title: "パッケージのインストールはできません",
      cause: "install.packages(...) が含まれています。実行環境ではオフラインで導入済みのパッケージのみ使えます。",
      fix: "install.packages(...) を削除し、library(...) で既存パッケージを読み込んでください。未導入のパッケージが必要な場合は管理者に追加を依頼します。",
      likelihood: "medium",
    },
  },
  {
    test: (r) =>
      r.includes("dynamic code execution") ||
      r.includes("dynamic code construction") ||
      r.includes("uncontrolled external code loading"),
    guidance: {
      title: "動的コード実行（eval/parse/source）は使えません",
      cause: "eval() / parse() / source() など、文字列からコードを生成・読込する処理が含まれています。",
      fix: "処理をそのまま R の式として書いてください（文字列を組み立てて実行しない）。",
      likelihood: "low",
    },
  },
  {
    test: (r) => r.includes("network access not permitted") || r.includes("network package call"),
    guidance: {
      title: "ネットワークアクセスはできません",
      cause: "download.file() / url() / httr・curl 等の通信呼び出しが含まれています。実行環境は完全オフラインです。",
      fix: "外部から取得せず、ワークスペース内のファイル（dataset.csv 等）を読み込んでください。",
      likelihood: "low",
    },
  },
  {
    test: (r) => r.includes("environment mutation"),
    guidance: {
      title: "環境変数の変更（Sys.setenv）はできません",
      cause: "Sys.setenv(...) が含まれています。環境変数の書き換えは禁止です（読み取りの Sys.getenv は可）。",
      fix: "Sys.setenv を削除してください。WORKSPACE_DIR / OUTPUT_DIR は Sys.getenv で読み取るだけにします。",
      likelihood: "low",
    },
  },
  {
    test: (r) =>
      r.includes("forbidden function name passed as a string") ||
      r.includes("backtick-quoted call"),
    guidance: {
      title: "禁止関数の間接呼び出しはできません",
      cause: "do.call/get や backtick を使って禁止関数を間接的に呼ぶ書き方が検出されました。",
      fix: "許可された関数を直接呼び出してください。",
      likelihood: "low",
    },
  },
];

/** Return actionable guidance for a run failure reason, or null if none maps.
 *  `reason` is `RunResponse.error_detail` (may include the [RUNTIME_…] envelope). */
export function explainRunError(
  reason: string | null | undefined,
): RunErrorGuidance | null {
  if (!reason) return null;
  // Only static security rejections carry a fixable, script-side cause. A plain
  // R runtime error (exit_code=1) is explained by the console stderr instead.
  const isSecurity = reason.includes("security validation");
  for (const m of MATCHERS) {
    if (m.test(reason)) return m.guidance;
  }
  if (isSecurity) {
    return {
      title: "セキュリティ検証で停止しました",
      cause:
        "実行前の静的チェックでスクリプトが拒否されました（下の理由を参照）。危険な関数呼び出しや絶対パスなどが対象です。",
      fix: "理由に挙がった箇所を、R の標準的な書き方（相対パス・許可関数のみ）に置き換えてください。",
      likelihood: "medium",
    };
  }
  return null;
}
