import Editor, { type OnMount } from "@monaco-editor/react";
import { forwardRef, useImperativeHandle, useRef } from "react";
import type { editor } from "monaco-editor";
import type { RunResponse } from "../api/types";
import type { Theme } from "../theme";
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
    return (
      <div className="result-error" data-testid="result-error">
        <strong>実行に失敗しました。</strong>
        <div className="result-error__detail">理由: {result.error_detail}</div>
      </div>
    );
  }

  const stats = result.statistical_results;
  const exec = result.execution_result ?? {};
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
        <pre className="result__json" data-testid="result-stats">
          {JSON.stringify(stats, null, 2)}
        </pre>
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
