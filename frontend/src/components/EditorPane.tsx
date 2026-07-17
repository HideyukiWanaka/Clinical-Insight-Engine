import Editor, { type OnMount } from "@monaco-editor/react";
import { forwardRef, useImperativeHandle, useRef } from "react";
import type { editor } from "monaco-editor";
import type { RunResponse } from "../api/types";
import type { Theme } from "../theme";
import { explainRunError } from "../runErrorGuidance";
import { Pane } from "./Pane";

/** Imperative surface the chat uses to insert code at the cursor (§3.2). */
export interface EditorHandle {
  insertAtCursor: (text: string) => void;
}

interface EditorPaneProps {
  value: string;
  onChange: (value: string) => void;
  theme: Theme;
  /** Run the whole editor, or the current selection (spec/ui §3.2). */
  onRunCode: (code: string) => void;
  running: boolean;
  result: RunResponse | null;
  tab: string;
  onTabChange: (tab: string) => void;
}

/** Center-top: Monaco R editor with Code / Result tabs
 *  (spec/ui/ide-workbench-spec.md §3.2). "▶ Run" posts the whole editor to
 *  /api/run; "選択範囲を実行" posts the current selection. Chat "スクリプトへ挿入"
 *  targets the cursor position via the exposed EditorHandle. */
export const EditorPane = forwardRef<EditorHandle, EditorPaneProps>(function EditorPane(
  { value, onChange, theme, onRunCode, running, result, tab, onTabChange },
  ref,
) {
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);

  const onMount: OnMount = (ed) => {
    editorRef.current = ed;
  };

  useImperativeHandle(ref, () => ({
    insertAtCursor(text: string) {
      const ed = editorRef.current;
      if (!ed) {
        // Editor not mounted yet — fall back to appending so nothing is lost.
        onChange(`${value.replace(/\n+$/, "")}\n\n${text}\n`);
        return;
      }
      const selection = ed.getSelection();
      const snippet = text.endsWith("\n") ? text : `${text}\n`;
      ed.executeEdits("chat-insert", [
        { range: selection!, text: snippet, forceMoveMarkers: true },
      ]);
      ed.focus();
    },
  }));

  function runAll() {
    onRunCode(editorRef.current?.getValue() ?? value);
  }

  function runSelection() {
    const ed = editorRef.current;
    const sel = ed?.getSelection();
    const selected = sel ? (ed!.getModel()?.getValueInRange(sel) ?? "") : "";
    onRunCode(selected.trim() ? selected : (ed?.getValue() ?? value));
  }

  return (
    <Pane
      title="スクリプト"
      tabs={[
        { id: "code", label: "Code" },
        { id: "result", label: "Result" },
      ]}
      activeTab={tab}
      onTabChange={onTabChange}
      flush
      headerExtra={
        <div className="pane__toolbar">
          <button
            className="mini-btn mini-btn--run"
            data-testid="editor-run"
            disabled={running}
            onClick={runAll}
            title="エディタ全体を実行 (POST /api/run)"
          >
            ▶ Run
          </button>
          <button
            className="mini-btn"
            data-testid="editor-run-selection"
            disabled={running}
            onClick={runSelection}
            title="選択範囲を実行"
          >
            選択範囲を実行
          </button>
        </div>
      }
    >
      {tab === "code" ? (
        <div className="editor-host" data-testid="editor-host">
          <Editor
            height="100%"
            defaultLanguage="r"
            language="r"
            theme={theme === "dark" ? "vs-dark" : "light"}
            value={value}
            onMount={onMount}
            onChange={(v) => onChange(v ?? "")}
            options={{
              fontSize: 13,
              minimap: { enabled: false },
              lineNumbers: "on",
              scrollBeyondLastLine: false,
              automaticLayout: true,
              tabSize: 2,
            }}
          />
        </div>
      ) : (
        <div className="pane__body">
          <ResultView result={result} />
        </div>
      )}
    </Pane>
  );
});

/** Result tab: last run's statistics, or its failure reason (never silent, §5). */
function ResultView({ result }: { result: RunResponse | null }) {
  if (!result) {
    return (
      <div className="placeholder" data-testid="result-empty">
        コードを実行すると、直近の統計結果をここに表示します（<code>POST /api/run</code>）。
      </div>
    );
  }

  if (result.error_detail) {
    const guidance = explainRunError(result.error_detail);
    return (
      <div className="result-error" data-testid="result-error">
        <strong>実行に失敗しました。</strong>
        <div className="result-error__detail">理由: {result.error_detail}</div>
        {guidance && (
          <div className="result-fix" data-testid="result-fix">
            <div className="result-fix__title">💡 {guidance.title}</div>
            <div className="result-fix__row">
              <span className="result-fix__label">原因</span>
              <span>{guidance.cause}</span>
            </div>
            <div className="result-fix__row">
              <span className="result-fix__label">対処</span>
              <span>{guidance.fix}</span>
            </div>
            {guidance.example && (
              <pre className="result-fix__example">{guidance.example}</pre>
            )}
          </div>
        )}
      </div>
    );
  }

  const stats = result.statistical_results as Record<string, unknown> | null | undefined;
  const exec = result.execution_result ?? {};
  // Multiple outcome variables (e.g. systolic + diastolic BP — see
  // cie/agents/statistics.py's outcome_results contract) make the raw JSON
  // dump noticeably bulkier (a duplicated flat summary plus a full per-outcome
  // array). Show a compact table first and tuck the raw JSON behind <details>
  // instead, without dropping any number a single-outcome result already showed.
  const outcomeResults = Array.isArray(stats?.outcome_results)
    ? (stats!.outcome_results as Record<string, unknown>[])
    : null;
  const hasMultipleOutcomes = !!outcomeResults && outcomeResults.length > 1;
  const multipleComparison = stats?.multiple_comparison as
    | { method?: string; n_comparisons?: number }
    | undefined;

  return (
    <div className="result" data-testid="result-view">
      <dl className="kv">
        {exec.status && (
          <>
            <dt>status</dt>
            <dd>{exec.status}</dd>
          </>
        )}
        {typeof exec.duration_ms === "number" && (
          <>
            <dt>duration</dt>
            <dd>{exec.duration_ms} ms</dd>
          </>
        )}
      </dl>
      {stats ? (
        <>
          {hasMultipleOutcomes && (
            <div className="result__summary" data-testid="result-outcome-summary">
              {multipleComparison && (
                <p className="result__summary-note">
                  {outcomeResults!.length}個のアウトカムを比較（多重比較補正:{" "}
                  {multipleComparison.method ?? "-"}）
                </p>
              )}
              <table className="result__summary-table">
                <thead>
                  <tr>
                    <th>アウトカム</th>
                    <th>検定</th>
                    <th>p値</th>
                    <th>補正後p値</th>
                    <th>効果量</th>
                  </tr>
                </thead>
                <tbody>
                  {outcomeResults!.map((r, i) => (
                    <tr key={i}>
                      <td>{String(r.outcome_variable ?? "-")}</td>
                      <td>{String(r.test_name ?? "-")}</td>
                      <td>{formatStatNumber(r.p_value)}</td>
                      <td>{formatStatNumber(r.p_value_adjusted)}</td>
                      <td>
                        {formatStatNumber(r.effect_size)}
                        {r.effect_size_measure ? ` (${r.effect_size_measure})` : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <details className="result__raw" open={!hasMultipleOutcomes}>
            <summary>詳細JSON</summary>
            <pre className="result__json" data-testid="result-stats">
              {JSON.stringify(stats, null, 2)}
            </pre>
          </details>
        </>
      ) : (
        <div className="placeholder">
          統計結果は返りませんでした
          {result.statistical_results_reason
            ? `（理由: ${result.statistical_results_reason}）`
            : "。"}
        </div>
      )}
    </div>
  );
}

/** Round a raw statistic to 3 decimals for the summary table; the full-precision
 *  value is still available in the raw JSON <details> right below it. */
function formatStatNumber(value: unknown): string {
  return typeof value === "number" ? value.toFixed(3) : String(value ?? "-");
}
