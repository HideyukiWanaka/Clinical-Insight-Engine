import { useState } from "react";
import { Pane, PhasePlaceholder } from "./Pane";

/** Right-bottom: Workspace/Data + Output & Format
 *  (spec/ui/ide-workbench-spec.md §3.5). R variable list (POST /api/run
 *  workspace_summary) and the report format panel are wired in Phase 3/4/6;
 *  this is the tabbed frame. */
export function WorkspacePane() {
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
        <PhasePlaceholder phase="Phase 3/4">
          直近実行後のR変数一覧（名前・型・要約）を表示します。永続ワークスペース
          （<code>.RData</code>）の可視化を兼ねます。
        </PhasePlaceholder>
      ) : (
        <PhasePlaceholder phase="Phase 6">
          報告チェックリスト / 雑誌スタイル / ユーザーSkill を選び「原稿に変換」
          （<code>POST /api/report</code>）します。
        </PhasePlaceholder>
      )}
    </Pane>
  );
}
