import Editor from "@monaco-editor/react";
import { useState } from "react";
import type { Theme } from "../theme";
import { Pane } from "./Pane";

interface EditorPaneProps {
  value: string;
  onChange: (value: string) => void;
  theme: Theme;
}

/** Center-top: Monaco R editor with Code / Result tabs
 *  (spec/ui/ide-workbench-spec.md §3.2). "▶ Run" / "選択範囲を実行" are wired in
 *  Phase 3; here the editor is fully editable and holds the working script so
 *  chat "スクリプトへ挿入" has a target in the next phase. */
export function EditorPane({ value, onChange, theme }: EditorPaneProps) {
  const [tab, setTab] = useState("code");

  return (
    <Pane
      title="スクリプト"
      tabs={[
        { id: "code", label: "Code" },
        { id: "result", label: "Result" },
      ]}
      activeTab={tab}
      onTabChange={setTab}
      flush
    >
      {tab === "code" ? (
        <div className="editor-host" data-testid="editor-host">
          <Editor
            height="100%"
            defaultLanguage="r"
            language="r"
            theme={theme === "dark" ? "vs-dark" : "light"}
            value={value}
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
          <div className="placeholder">
            <span className="badge-phase">Phase 3</span>
            直近実行の統計結果をここに整形表示します（POST /api/run の結果）。
          </div>
        </div>
      )}
    </Pane>
  );
}
