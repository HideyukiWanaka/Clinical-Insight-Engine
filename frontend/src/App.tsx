import { useCallback, useEffect, useRef, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { apiClient } from "./api/client";
import { ChatPane } from "./components/ChatPane";
import { ConsolePane } from "./components/ConsolePane";
import { DatasetModal } from "./components/DatasetModal";
import { EditorPane, type EditorHandle } from "./components/EditorPane";
import { FileTree } from "./components/FileTree";
import { Header } from "./components/Header";
import { KnowledgeModal } from "./components/KnowledgeModal";
import { LlmSettingsModal } from "./components/LlmSettingsModal";
import { SettingsModal } from "./components/SettingsModal";
import { WorkspacePane } from "./components/WorkspacePane";
import { applyTheme, getInitialTheme, type Theme } from "./theme";
import type { DatasetUploadResponse } from "./api/types";
import { useRunner } from "./useRunner";

const INITIAL_SCRIPT = `# CIE Workbench — R スクリプト
# チャットの提案コードを「✓ 挿入」でカーソル位置へ、「▶ Run」で実行します。
`;

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => {
    const t = getInitialTheme();
    applyTheme(t);
    return t;
  });
  const [script, setScript] = useState(INITIAL_SCRIPT);
  const [editorTab, setEditorTab] = useState("code");
  const [consoleTab, setConsoleTab] = useState("console");
  const editorRef = useRef<EditorHandle>(null);
  // Bumps whenever the session token changes so the header status refreshes.
  const [, setTokenTick] = useState(0);
  // Registered dataset (§3.1 前提) and the 解析データ modal open state.
  const [datasetInfo, setDatasetInfo] = useState<DatasetUploadResponse | null>(null);
  const [datasetOpen, setDatasetOpen] = useState(false);
  // 参考資料（知識取り込み）modal — a separate 入口 from 解析データ (§5).
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  // セッショントークン設定 modal — opened from the header connection status.
  const [settingsOpen, setSettingsOpen] = useState(false);
  // AIプロバイダー設定 modal — opened from the header "🤖 AIモデル" entry.
  const [llmSettingsOpen, setLlmSettingsOpen] = useState(false);
  // Bumped when a run completes so the FileTree re-lists new generated files.
  const [refreshKey, setRefreshKey] = useState(0);

  const runner = useRunner(apiClient);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      applyTheme(next);
      return next;
    });
  }, []);

  // Chat "✓ 挿入": drop the candidate at the editor cursor, do not run (§3.1).
  const insertCode = useCallback((code: string) => {
    editorRef.current?.insertAtCursor(code);
  }, []);

  // "▶ 実行" (chat / editor): run without further insertion. Bring the console
  // forward so the streamed log is visible immediately (§4).
  const runCode = useCallback(
    (code: string, intent?: Record<string, unknown>) => {
      setConsoleTab("console");
      runner.runCode(code, intent);
    },
    [runner],
  );

  // Surface the structured result on the Result tab once it lands (§3.2, §4),
  // and refresh the file tree (a run may have generated new files, §3.4).
  useEffect(() => {
    if (runner.result) {
      setEditorTab("result");
      setRefreshKey((n) => n + 1);
    }
  }, [runner.result]);

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
        onOpenDataset={() => setDatasetOpen(true)}
        datasetUploaded={datasetInfo != null}
        onOpenKnowledge={() => setKnowledgeOpen(true)}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenLlmSettings={() => setLlmSettingsOpen(true)}
      />

      {settingsOpen && (
        <SettingsModal
          client={apiClient}
          connected={connected}
          onClose={() => setSettingsOpen(false)}
          onConnectedChange={onConnectedChange}
        />
      )}

      {llmSettingsOpen && (
        <LlmSettingsModal
          client={apiClient}
          connected={connected}
          onClose={() => setLlmSettingsOpen(false)}
        />
      )}

      {datasetOpen && (
        <DatasetModal
          client={apiClient}
          connected={connected}
          current={datasetInfo}
          onClose={() => setDatasetOpen(false)}
          onUploaded={setDatasetInfo}
        />
      )}

      {knowledgeOpen && (
        <KnowledgeModal
          client={apiClient}
          connected={connected}
          onClose={() => setKnowledgeOpen(false)}
        />
      )}

      <PanelGroup direction="horizontal" className="panels" autoSaveId="cie.layout.h">
        <Panel defaultSize={26} minSize={16} order={1}>
          <ChatPane
            client={apiClient}
            connected={connected}
            onOpenSettings={() => setSettingsOpen(true)}
            onInsertCode={insertCode}
            onRunCode={runCode}
            datasetUploaded={datasetInfo != null}
            priorStats={runner.result?.statistical_results ?? null}
            priorScript={runner.lastScript}
            priorIntent={runner.lastIntent}
          />
        </Panel>

        <PanelResizeHandle className="resize-handle" />

        <Panel defaultSize={46} minSize={25} order={2}>
          <PanelGroup direction="vertical" autoSaveId="cie.layout.center">
            <Panel defaultSize={62} minSize={20} order={1}>
              <EditorPane
                ref={editorRef}
                value={script}
                onChange={setScript}
                theme={theme}
                onRunCode={runCode}
                running={runner.running}
                result={runner.result}
                tab={editorTab}
                onTabChange={setEditorTab}
              />
            </Panel>
            <PanelResizeHandle className="resize-handle" />
            <Panel defaultSize={38} minSize={12} order={2}>
              <ConsolePane
                lines={runner.consoleLines}
                figures={runner.figures}
                tab={consoleTab}
                onTabChange={setConsoleTab}
              />
            </Panel>
          </PanelGroup>
        </Panel>

        <PanelResizeHandle className="resize-handle" />

        <Panel defaultSize={28} minSize={16} order={3}>
          <PanelGroup direction="vertical" autoSaveId="cie.layout.right">
            <Panel defaultSize={50} minSize={15} order={1}>
              <FileTree
                client={apiClient}
                connected={connected}
                refreshKey={refreshKey}
              />
            </Panel>
            <PanelResizeHandle className="resize-handle" />
            <Panel defaultSize={50} minSize={15} order={2}>
              <WorkspacePane
                result={runner.result}
                onResetWorkspace={runner.resetWorkspace}
                resetting={runner.running}
                client={apiClient}
                connected={connected}
                intent={runner.lastIntent}
              />
            </Panel>
          </PanelGroup>
        </Panel>
      </PanelGroup>
    </div>
  );
}
