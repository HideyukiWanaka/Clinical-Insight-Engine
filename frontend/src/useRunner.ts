// Run coordinator for the workbench (spec/ui/ide-workbench-spec.md §4).
//
// A single `runCode` drives the whole "実行" flow the mockup shows:
//   - WS /ws/console streams the sanitized execution log → Console tab.
//   - POST /api/run returns the structured result → Result tab + Workspace.
//   - POST /api/visualize turns statistical_results into figures → Output tab.
//
// Failure is never silent (§5): every failure path pushes a reason into the
// console AND leaves it on `result.error_detail` so the Result pane shows it —
// including "Rscript が無い" when R is not installed.

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type CieApiClient } from "./api/client";
import type { ConsoleMessage, RunResponse } from "./api/types";

export type ConsoleStream = "stdout" | "stderr" | "exit" | "info";

export interface ConsoleLine {
  id: number;
  stream: ConsoleStream;
  text: string;
}

export interface RunFigure {
  title: string;
  /** Object URL for the fetched PNG, or null while loading / on failure. */
  url: string | null;
}

export interface Runner {
  running: boolean;
  consoleLines: ConsoleLine[];
  result: RunResponse | null;
  figures: RunFigure[];
  runCode: (code: string, intent?: Record<string, unknown>) => void;
  clearConsole: () => void;
  resetWorkspace: () => void;
}

let lineSeq = 0;

export function useRunner(client: CieApiClient): Runner {
  const [running, setRunning] = useState(false);
  const [consoleLines, setConsoleLines] = useState<ConsoleLine[]>([]);
  const [result, setResult] = useState<RunResponse | null>(null);
  const [figures, setFigures] = useState<RunFigure[]>([]);

  // Track the live socket and any object URLs so we can tear them down cleanly.
  const wsRef = useRef<WebSocket | null>(null);
  const objectUrlsRef = useRef<string[]>([]);

  const push = useCallback((stream: ConsoleStream, text: string) => {
    setConsoleLines((prev) => [...prev, { id: ++lineSeq, stream, text }]);
  }, []);

  const revokeFigures = useCallback(() => {
    for (const url of objectUrlsRef.current) URL.revokeObjectURL(url);
    objectUrlsRef.current = [];
  }, []);

  const clearConsole = useCallback(() => setConsoleLines([]), []);

  useEffect(
    () => () => {
      wsRef.current?.close();
      revokeFigures();
    },
    [revokeFigures],
  );

  const streamConsole = useCallback(
    (code: string) => {
      wsRef.current?.close();
      wsRef.current = client.streamConsole({
        rScript: code,
        onMessage: (msg: ConsoleMessage) => {
          if (msg.type === "exit") {
            const exitCode = msg.exit_code;
            push("exit", exitCode == null ? "[実行終了]" : `[終了コード ${exitCode}]`);
          } else {
            push(msg.type, msg.text);
          }
        },
        onError: (message) => push("stderr", message),
        onClose: () => {
          wsRef.current = null;
        },
      });
    },
    [client, push],
  );

  const loadFigures = useCallback(
    async (result: RunResponse, intent: Record<string, unknown>) => {
      const stats = result.statistical_results;
      if (!stats) return;
      try {
        const res = await client.visualize({
          statistical_results: stats,
          intent_object: intent,
        });
        if (res.error_detail) {
          push("stderr", `図の生成に失敗しました: ${res.error_detail}`);
          return;
        }
        // Resolve each figure path to a token-authenticated object URL.
        const loaded: RunFigure[] = await Promise.all(
          res.figures.map(async (f) => {
            if (!f.path) return { title: f.title, url: null };
            try {
              const url = await client.fetchImageObjectUrl(f.path);
              objectUrlsRef.current.push(url);
              return { title: f.title, url };
            } catch {
              return { title: f.title, url: null };
            }
          }),
        );
        setFigures(loaded);
      } catch (err) {
        push("stderr", `図の生成に失敗しました: ${describeError(err)}`);
      }
    },
    [client, push],
  );

  const runCode = useCallback(
    (code: string, intent: Record<string, unknown> = {}) => {
      const script = code.trim();
      if (!script || running) return;

      revokeFigures();
      setFigures([]);
      setResult(null);
      clearConsole();
      setRunning(true);
      push("info", "> 実行中…");

      // Console log stream (independent of the structured result call).
      streamConsole(script);

      void (async () => {
        try {
          // Persist the workspace across runs (.RData) so derived variables
          // from a prior run remain available (workspace-persistence spec §2).
          const res = await client.run({ r_script: script, persist_workspace: true });
          setResult(res);
          if (res.error_detail) {
            // Mirror the reason into the console so it is impossible to miss (§5).
            push("stderr", res.error_detail);
          } else {
            await loadFigures(res, intent);
          }
        } catch (err) {
          const detail = describeError(err);
          setResult({
            execution_id: "",
            execution_result: {},
            error_detail: detail,
          });
          push("stderr", detail);
        } finally {
          setRunning(false);
        }
      })();
    },
    [client, running, revokeFigures, clearConsole, push, streamConsole, loadFigures],
  );

  const resetWorkspace = useCallback(() => {
    if (running) return;
    void (async () => {
      try {
        const res = await client.resetWorkspace();
        // Drop the stale variable listing from the pane immediately.
        setResult(null);
        const removed = res.removed.length
          ? res.removed.join(", ")
          : "（削除対象なし）";
        push("info", `ワークスペースをリセットしました: ${removed}`);
      } catch (err) {
        push("stderr", `ワークスペースのリセットに失敗しました: ${describeError(err)}`);
      }
    })();
  }, [client, running, push]);

  return { running, consoleLines, result, figures, runCode, clearConsole, resetWorkspace };
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return err.detail ? `${err.message}（${err.detail}）` : err.message;
  }
  return String((err as Error)?.message ?? err);
}
