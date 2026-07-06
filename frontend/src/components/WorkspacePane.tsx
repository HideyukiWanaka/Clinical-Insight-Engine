import { useState } from "react";
import type { RunResponse } from "../api/types";
import { Pane, PhasePlaceholder } from "./Pane";

interface WorkspacePaneProps {
  result: RunResponse | null;
}

/** Right-bottom: Workspace/Data + Output & Format
 *  (spec/ui/ide-workbench-spec.md §3.5). Workspace/Data shows the R variables
 *  and generated files from the last POST /api/run (`workspace_summary` is
 *  surfaced ahead of Phase 4 when present). Output & Format stays Phase 6. */
export function WorkspacePane({ result }: WorkspacePaneProps) {
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
        <WorkspaceData result={result} />
      ) : (
        <PhasePlaceholder phase="Phase 6">
          報告チェックリスト / 雑誌スタイル / ユーザーSkill を選び「原稿に変換」
          （<code>POST /api/report</code>）します。
        </PhasePlaceholder>
      )}
    </Pane>
  );
}

function WorkspaceData({ result }: { result: RunResponse | null }) {
  const summary = result?.workspace_summary ?? null;
  const files = result?.generated_files ?? [];
  const vars = summary ? Object.entries(summary) : [];

  if (!result || (vars.length === 0 && files.length === 0)) {
    return (
      <div className="placeholder" data-testid="workspace-empty">
        直近実行後のR変数一覧（名前・型・要約）を表示します。永続ワークスペース
        （<code>.RData</code>）の可視化を兼ねます。
      </div>
    );
  }

  return (
    <div className="workspace" data-testid="workspace-data">
      {vars.length > 0 && (
        <dl className="kv workspace__vars">
          {vars.map(([name, desc]) => (
            <div className="workspace__var" key={name}>
              <dt>{name}</dt>
              <dd>{typeof desc === "string" ? desc : JSON.stringify(desc)}</dd>
            </div>
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
    </div>
  );
}
