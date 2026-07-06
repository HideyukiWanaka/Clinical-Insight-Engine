import { useState } from "react";
import { Pane, PhasePlaceholder } from "./Pane";

/** Center-bottom: R console (WS /ws/console) + plot output
 *  (spec/ui/ide-workbench-spec.md §3.3). Streaming + figures land in Phase 3;
 *  this is the tabbed frame. */
export function ConsolePane() {
  const [tab, setTab] = useState("console");
  return (
    <Pane
      title="コンソール"
      tabs={[
        { id: "console", label: "Console" },
        { id: "output", label: "Output" },
      ]}
      activeTab={tab}
      onTabChange={setTab}
    >
      {tab === "console" ? (
        <PhasePlaceholder phase="Phase 3">
          WS <code>/ws/console</code> のサニタイズ済みストリームをここに逐次表示します。
        </PhasePlaceholder>
      ) : (
        <PhasePlaceholder phase="Phase 3">
          <code>POST /api/visualize</code> で生成された図（PNG）を表示します。
        </PhasePlaceholder>
      )}
    </Pane>
  );
}
