import { useEffect, useRef } from "react";
import type { ConsoleLine, RunFigure } from "../useRunner";
import { Pane, PhasePlaceholder } from "./Pane";

interface ConsolePaneProps {
  lines: ConsoleLine[];
  figures: RunFigure[];
  tab: string;
  onTabChange: (tab: string) => void;
}

/** Center-bottom: R console (WS /ws/console) + plot output
 *  (spec/ui/ide-workbench-spec.md §3.3). The Console tab shows the sanitized
 *  streamed log; the Output tab shows figures from POST /api/visualize. */
export function ConsolePane({ lines, figures, tab, onTabChange }: ConsolePaneProps) {
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (tab === "console") logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [lines, tab]);

  return (
    <Pane
      title="コンソール"
      tabs={[
        { id: "console", label: "Console" },
        { id: "output", label: "Output" },
      ]}
      activeTab={tab}
      onTabChange={onTabChange}
      flush
    >
      {tab === "console" ? (
        <div className="console" data-testid="console-log" ref={logRef}>
          {lines.length === 0 ? (
            <div className="placeholder" style={{ padding: 12 }}>
              コードを実行すると、<code>/ws/console</code>{" "}
              のサニタイズ済みログをここに逐次表示します。
            </div>
          ) : (
            lines.map((l) => (
              <div key={l.id} className={`console__line console__line--${l.stream}`}>
                {l.text}
              </div>
            ))
          )}
        </div>
      ) : (
        <div className="pane__body">
          {figures.length === 0 ? (
            <PhasePlaceholder phase="Output">
              統計結果から生成された図（<code>POST /api/visualize</code>）をここに表示します。
            </PhasePlaceholder>
          ) : (
            <div className="figures" data-testid="figure-output">
              {figures.map((f, i) => (
                <figure className="figure" key={i}>
                  {f.url ? (
                    <img src={f.url} alt={f.title} className="figure__img" />
                  ) : (
                    <div className="placeholder">図を読み込めませんでした: {f.title}</div>
                  )}
                  <figcaption className="figure__caption">{f.title}</figcaption>
                </figure>
              ))}
            </div>
          )}
        </div>
      )}
    </Pane>
  );
}
