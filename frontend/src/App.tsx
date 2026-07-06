import { useCallback, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { apiClient } from "./api/client";
import { ChatPane } from "./components/ChatPane";
import { ConsolePane } from "./components/ConsolePane";
import { EditorPane } from "./components/EditorPane";
import { FileTree } from "./components/FileTree";
import { Header } from "./components/Header";
import { WorkspacePane } from "./components/WorkspacePane";
import { applyTheme, getInitialTheme, type Theme } from "./theme";

const INITIAL_SCRIPT = `# CIE Workbench — R スクリプト
# チャットの提案コードを「スクリプトへ挿入」するとここに入ります（Phase 3）。
`;

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => {
    const t = getInitialTheme();
    applyTheme(t);
    return t;
  });
  const [script, setScript] = useState(INITIAL_SCRIPT);
  // Bumps whenever the session token changes so the header status refreshes.
  const [, setTokenTick] = useState(0);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      applyTheme(next);
      return next;
    });
  }, []);

  const insertCode = useCallback((code: string) => {
    // Cursor-position insertion is Phase 3; append for now.
    setScript((prev) => `${prev.replace(/\n+$/, "")}\n\n${code}\n`);
  }, []);

  const onConnectedChange = useCallback(() => setTokenTick((n) => n + 1), []);
  const connected = apiClient.hasToken();

  return (
    <div className="app">
      <Header
        projectName="CIE"
        connected={connected}
        apiBaseUrl={apiClient.getBaseUrl()}
        theme={theme}
        onToggleTheme={toggleTheme}
      />

      <PanelGroup direction="horizontal" className="panels" autoSaveId="cie.layout.h">
        <Panel defaultSize={26} minSize={16} order={1}>
          <ChatPane
            client={apiClient}
            connected={connected}
            onConnectedChange={onConnectedChange}
            onInsertCode={insertCode}
          />
        </Panel>

        <PanelResizeHandle className="resize-handle" />

        <Panel defaultSize={46} minSize={25} order={2}>
          <PanelGroup direction="vertical" autoSaveId="cie.layout.center">
            <Panel defaultSize={62} minSize={20} order={1}>
              <EditorPane value={script} onChange={setScript} theme={theme} />
            </Panel>
            <PanelResizeHandle className="resize-handle" />
            <Panel defaultSize={38} minSize={12} order={2}>
              <ConsolePane />
            </Panel>
          </PanelGroup>
        </Panel>

        <PanelResizeHandle className="resize-handle" />

        <Panel defaultSize={28} minSize={16} order={3}>
          <PanelGroup direction="vertical" autoSaveId="cie.layout.right">
            <Panel defaultSize={50} minSize={15} order={1}>
              <FileTree />
            </Panel>
            <PanelResizeHandle className="resize-handle" />
            <Panel defaultSize={50} minSize={15} order={2}>
              <WorkspacePane />
            </Panel>
          </PanelGroup>
        </Panel>
      </PanelGroup>
    </div>
  );
}
