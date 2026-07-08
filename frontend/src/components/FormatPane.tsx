import { useState } from "react";
import { ApiError, type CieApiClient } from "../api/client";
import type { ManuscriptSection, RunResponse } from "../api/types";

// Reporting-checklist + journal-style option sets. Values MUST stay identical to
// cie/ui/screens/format_selection.py:21-45 (the Streamlit panel) so the same
// selections reach the unchanged ReportingAgent via POST /api/report (§3.5).
const CHECKLISTS: Array<{ value: string | null; label: string }> = [
  { value: null, label: "自動判定（study_design から推論）" },
  { value: "CONSORT", label: "CONSORT 2010 — ランダム化比較試験" },
  { value: "STROBE", label: "STROBE 2007 — 観察研究 (コホート / 症例対照 / 横断)" },
  { value: "TRIPOD", label: "TRIPOD+AI 2024 — 予測モデル開発・検証" },
  { value: "PRISMA", label: "PRISMA 2020 — システマティックレビュー・メタ解析" },
  { value: "STARD", label: "STARD 2015 — 診断精度研究" },
];

const JOURNAL_STYLES = ["APA", "AMA", "Vancouver"] as const;

const STYLE_EXAMPLES: Record<string, string> = {
  APA: "p = .034  /  p < .001  （7th edition, leading zero なし）",
  AMA: "P = .034  /  P < .001  （11th edition, 大文字 P）",
  Vancouver: "p = 0.034  /  p < 0.001  （leading zero あり）",
};

interface FormatPaneProps {
  client: CieApiClient;
  connected: boolean;
  /** Last run result — supplies statistical_results for the manuscript (§3.5). */
  result: RunResponse | null;
  /** intent_object of the last run — passed through to the Reporting agent. */
  intent: Record<string, unknown>;
}

/** Output & Format (spec/ui/ide-workbench-spec.md §3.5): choose a reporting
 *  checklist / journal style / user Skill, then "原稿に変換" → POST /api/report.
 *  The drafted sections render as copyable text blocks (no auto-clipboard). */
export function FormatPane({ client, connected, result, intent }: FormatPaneProps) {
  const [checklistId, setChecklistId] = useState<string | null>(null);
  const [journalStyle, setJournalStyle] = useState<string>("APA");
  const [skillId, setSkillId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [sections, setSections] = useState<ManuscriptSection[] | null>(null);
  const [error, setError] = useState<{ text: string; detail?: string | null } | null>(
    null,
  );

  const stats = result?.statistical_results ?? null;
  const hasStats = stats != null && Object.keys(stats).length > 0;
  const canGenerate = connected && hasStats && !busy;

  async function generate() {
    if (!canGenerate) return;
    setBusy(true);
    setError(null);
    try {
      const res = await client.report({
        statistical_results: stats ?? {},
        intent_object: intent,
        reporting_checklist_id: checklistId,
        target_journal_style: journalStyle,
        // A user Skill takes priority over the core skill (ADR-0002); an empty
        // field means "use the core reporting/manuscript-section skill".
        reporting_skill_id: skillId.trim() || null,
      });
      if (res.error_detail) {
        setSections(null);
        setError({ text: "原稿生成に失敗しました。", detail: res.error_detail });
        return;
      }
      setSections(res.manuscript_sections);
    } catch (err) {
      setSections(null);
      if (err instanceof ApiError) {
        setError({ text: err.message, detail: err.detail });
      } else {
        setError({
          text: "予期しないエラーが発生しました。",
          detail: String((err as Error)?.message ?? err),
        });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="format" data-testid="format-pane">
      <div className="format__controls">
        <label className="format__field">
          <span className="format__label">報告チェックリスト</span>
          <select
            data-testid="format-checklist"
            value={checklistId ?? ""}
            onChange={(e) => setChecklistId(e.target.value || null)}
          >
            {CHECKLISTS.map((c) => (
              <option key={c.value ?? "auto"} value={c.value ?? ""}>
                {c.label}
              </option>
            ))}
          </select>
        </label>

        <div className="format__field">
          <span className="format__label">雑誌スタイル（p 値フォーマット）</span>
          <div className="format__radios" role="radiogroup" aria-label="雑誌スタイル">
            {JOURNAL_STYLES.map((s) => (
              <label key={s} className="format__radio">
                <input
                  type="radio"
                  name="journal-style"
                  value={s}
                  checked={journalStyle === s}
                  onChange={() => setJournalStyle(s)}
                />
                {s}
              </label>
            ))}
          </div>
          <span className="format__hint">{STYLE_EXAMPLES[journalStyle]}</span>
        </div>

        <label className="format__field">
          <span className="format__label">ユーザーSkill（skill_id で上書き）</span>
          <input
            data-testid="format-skill"
            value={skillId}
            placeholder="例: my-hospital-manuscript（未入力ならコアSkill）"
            onChange={(e) => setSkillId(e.target.value)}
          />
          <span className="format__hint">
            登録済みのユーザーSkillの <code>skill_id</code> を入力すると、コアSkillより優先されます（ADR-0002）。
          </span>
        </label>

        <button
          type="button"
          className="btn"
          data-testid="format-generate"
          disabled={!canGenerate}
          onClick={() => void generate()}
          title={
            hasStats
              ? "選択したフォーマットで原稿セクションを生成します"
              : "先に解析を実行して統計結果を用意してください"
          }
        >
          {busy ? "生成中…" : "原稿に変換"}
        </button>
        {!hasStats && (
          <span className="format__hint" data-testid="format-nostats">
            解析を実行すると、その統計結果から原稿を生成できます。
          </span>
        )}
      </div>

      {error && (
        <div className="format__error" data-testid="format-error">
          <span className="msg__role">エラー</span>
          {error.text}
          {error.detail && (
            <div className="format__error-detail">理由: {error.detail}</div>
          )}
        </div>
      )}

      {sections && (
        <div className="format__sections" data-testid="format-sections">
          {sections.length === 0 ? (
            <div className="placeholder">生成された原稿セクションはありません。</div>
          ) : (
            sections.map((s) => (
              <section key={s.section_id} className="manuscript" data-testid="manuscript-section">
                <div className="manuscript__bar">
                  <span className="manuscript__title">{s.section_id}</span>
                  {s.is_ai_generated && <span className="manuscript__ai">AI生成</span>}
                </div>
                {/* Copyable text: a plain, selectable block — no auto-clipboard (§3.5). */}
                <pre className="manuscript__text">{s.text}</pre>
              </section>
            ))
          )}
        </div>
      )}
    </div>
  );
}
