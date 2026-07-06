import { Pane, PhasePlaceholder } from "./Pane";

/** Right-top: read-only workspace file tree (spec/ui/ide-workbench-spec.md §3.4).
 *  Listing/preview via GET /api/files(/content) is wired in a later phase; this
 *  is the frame. Note §3.4: read-only — no delete UI. */
export function FileTree() {
  return (
    <Pane title="ファイル">
      <PhasePlaceholder phase="Phase 3+">
        <code>GET /api/files</code> の一覧をツリー表示します（dataset.csv, *.R,
        output/ 等）。読み取り専用。
      </PhasePlaceholder>
    </Pane>
  );
}
