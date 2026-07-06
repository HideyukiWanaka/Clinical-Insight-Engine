import { useState } from "react";
import type { RunResponse } from "../api/types";
import { Pane, PhasePlaceholder } from "./Pane";

interface WorkspacePaneProps {
  result: RunResponse | null;
  /** Clears the persisted .RData + summary (POST /api/workspace/reset). */
  onResetWorkspace: () => void;
  /** Disable the reset control while a run is in flight. */
  resetting: boolean;
}

/** One variable descriptor from workspace_summary (name → {class, summary}). */
interface VarDescriptor {
  class?: string;
  summary?: string;
}

/** Right-bottom: Workspace/Data + Output & Format
 *  (spec/ui/ide-workbench-spec.md §3.5). Workspace/Data shows the persisted R
 *  variables (name・型・要約) and generated files from the last POST /api/run,
 *  reading `workspace_summary` written by the .RData wrapper
 *  (spec/runtime-workspace-persistence.md §2). Output & Format stays Phase 6. */
export function WorkspacePane({ result, onResetWorkspace, resetting }: WorkspacePaneProps) {
  const [tab, setTab] = useState("workspace");
  return (
    <Pane
      title="ワークスペース"
      tabs={[
        { id: "workspace", label: "Workspace/Data" },
        { id: "format", label: "Output & Format" },
      ]}
      activeTab={tab}
      onTabChange={setTab}
    >
      {tab === "workspace" ? (
        <WorkspaceData
          result={result}
          onResetWorkspace={onResetWorkspace}
          resetting={resetting}
        />
      ) : (
        <PhasePlaceholder phase="Phase 6">
          報告チェックリスト / 雑誌スタイル / ユーザーSkill を選び「原稿に変換」
          （<code>POST /api/report</code>）します。
        </PhasePlaceholder>
      )}
    </Pane>
  );
}

function WorkspaceData({
  result,
  onResetWorkspace,
  resetting,
}: {
  result: RunResponse | null;
  onResetWorkspace: () => void;
  resetting: boolean;
}) {
  const summary = result?.workspace_summary ?? null;
  const files = result?.generated_files ?? [];
  const vars = summary ? Object.entries(summary) : [];

  return (
    <div className="workspace" data-testid="workspace-data">
      <div className="workspace__toolbar">
        <span className="workspace__hint">
          永続ワークスペース（<code>.RData</code>）の変数一覧
        </span>
        <button
          type="button"
          className="workspace__reset"
          data-testid="workspace-reset"
          onClick={onResetWorkspace}
          disabled={resetting}
          title=".RData と workspace_summary.json を削除します"
        >
          ワークスペースをリセット
        </button>
      </div>

      {vars.length === 0 && files.length === 0 ? (
        <div className="placeholder" data-testid="workspace-empty">
          直近実行後のR変数一覧（名前・型・要約）を表示します。「リセット」で
          <code>.RData</code> を削除すると、次回実行は空ワークスペースから始まります。
        </div>
      ) : (
        <>
          {vars.length > 0 && (
            <dl className="kv workspace__vars">
              {vars.map(([name, desc]) => (
                <VarRow key={name} name={name} desc={desc} />
              ))}
            </dl>
          )}
          {files.length > 0 && (
            <div className="workspace__files">
              <div className="workspace__label">生成ファイル</div>
              <ul>
                {files.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function VarRow({ name, desc }: { name: string; desc: unknown }) {
  // workspace_summary maps name → {class, summary}. Fall back gracefully if an
  // older/other shape (plain string) shows up.
  let type = "";
  let text = "";
  if (desc && typeof desc === "object") {
    const d = desc as VarDescriptor;
    type = d.class ?? "";
    text = d.summary ?? "";
  } else if (typeof desc === "string") {
    text = desc;
  } else {
    text = JSON.stringify(desc);
  }
  return (
    <div className="workspace__var">
      <dt>
        {name}
        {type && <span className="workspace__type">{type}</span>}
      </dt>
      <dd>{text}</dd>
    </div>
  );
}
