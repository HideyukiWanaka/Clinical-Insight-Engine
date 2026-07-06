import type { ReactNode } from "react";

interface PaneTab {
  id: string;
  label: string;
}

interface PaneProps {
  title: string;
  tabs?: PaneTab[];
  activeTab?: string;
  onTabChange?: (id: string) => void;
  flush?: boolean;
  /** Optional controls rendered in the header (e.g. the editor Run toolbar). */
  headerExtra?: ReactNode;
  children: ReactNode;
}

/** Shared pane chrome: a titled header with optional tabs + a scrollable body.
 *  Matches the tabbed panes described in spec/ui/ide-workbench-spec.md §3. */
export function Pane({
  title,
  tabs,
  activeTab,
  onTabChange,
  flush,
  headerExtra,
  children,
}: PaneProps) {
  return (
    <section className="pane" aria-label={title}>
      <div className="pane__header">
        <span>{title}</span>
        {headerExtra}
        {tabs && tabs.length > 0 && (
          <div className="pane__tabs" role="tablist">
            {tabs.map((t) => (
              <button
                key={t.id}
                role="tab"
                aria-selected={activeTab === t.id}
                className={
                  "pane__tab" + (activeTab === t.id ? " pane__tab--active" : "")
                }
                onClick={() => onTabChange?.(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className={"pane__body" + (flush ? " pane__body--flush" : "")}>
        {children}
      </div>
    </section>
  );
}

/** A "frame only" placeholder body for panes wired up in later phases. */
export function PhasePlaceholder({
  phase,
  children,
}: {
  phase: string;
  children: ReactNode;
}) {
  return (
    <div className="placeholder">
      <span className="badge-phase">{phase}</span>
      {children}
    </div>
  );
}
