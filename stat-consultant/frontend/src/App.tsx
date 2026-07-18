import { useEffect, useRef, useState } from "react";
import "./App.css";
import researcherArt from "./assets/researcher.png";
import { fetchModels, isTextReference, type ModelInfo, uploadReference } from "./api";
import { ChatMessage } from "./components/ChatMessage";
import { SettingsModal } from "./components/SettingsModal";
import { GearIcon, PaperclipIcon, SendIcon } from "./icons";
import { useConsult } from "./useConsult";

function App() {
  const { messages, connected, busy, send } = useConsult();
  const [input, setInput] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  // Load the selectable models; keep a valid selection as availability changes
  // (e.g. after a key is saved in settings).
  function refreshModels() {
    fetchModels()
      .then((data) => {
        setModels(data.models);
        setModel((current) => {
          const ok = data.models.find((m) => m.id === current && m.available);
          return ok ? current : data.default;
        });
      })
      .catch(() => setModels([]));
  }

  useEffect(refreshModels, []);

  // Keep the newest message in view as the conversation grows.
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [messages]);

  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  function showToast(msg: string) {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2800);
  }

  function submit() {
    if (!input.trim() || busy) return;
    send(input, model);
    setInput("");
  }

  function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file
    if (!file) return;
    // One attach button, auto-routed by type. Markdown/text → reference store;
    // images are handled in Step 9.
    if (!isTextReference(file)) {
      showToast("テキスト/Markdown を選んでください（画像は今後対応）");
      return;
    }
    uploadReference(file)
      .then(() => showToast("参考資料として保存しました"))
      .catch(() => showToast("アップロードに失敗しました"));
  }

  return (
    <div className="app">
      <header className="app__header">
        <span className="app__title">Stat Consultant</span>
        <div className="app__header-right">
          {models.length > 0 && (
            <select
              className="app__model"
              data-testid="model-select"
              aria-label="モデルを選択"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            >
              {models.map((m) => (
                <option key={m.id} value={m.id} disabled={!m.available}>
                  {m.label}
                  {m.available ? "" : "（未設定）"}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            className="app__gear"
            data-testid="open-settings"
            aria-label="設定"
            title="APIキーの設定"
            onClick={() => setSettingsOpen(true)}
          >
            <GearIcon />
          </button>
          <span
            className={`app__status ${connected ? "is-on" : "is-off"}`}
            title={connected ? "接続中" : "未接続"}
          />
        </div>
      </header>

      <main className="app__log" ref={logRef}>
        {messages.length === 0 ? (
          <div className="app__empty">
            <img className="app__empty-art" src={researcherArt} alt="" />
            <p className="app__empty-title">こんにちは、研究者さん</p>
            <p className="app__empty-sub">Rコードのこと、気軽に聞いてください。</p>
          </div>
        ) : (
          messages.map((m) => <ChatMessage key={m.id} msg={m} />)
        )}
      </main>

      <footer className="app__composer">
        <div className="composer__pill">
          <input
            ref={fileRef}
            type="file"
            accept=".md,.markdown,.txt,text/markdown,text/plain"
            hidden
            data-testid="file-input"
            onChange={onPickFile}
          />
          <button
            type="button"
            className="composer__attach"
            data-testid="attach"
            aria-label="参考資料を添付"
            title="参考資料（Markdown/テキスト）を添付"
            onClick={() => fileRef.current?.click()}
          >
            <PaperclipIcon />
          </button>
          <textarea
            className="composer__input"
            data-testid="chat-input"
            value={input}
            rows={1}
            placeholder="統計の相談を入力…"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends; Shift+Enter is a newline. Never send mid-IME
              // conversion (isComposing) — critical for Japanese input.
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <button
            type="button"
            className="composer__send"
            data-testid="chat-send"
            aria-label="送信"
            disabled={busy || !input.trim()}
            onClick={submit}
          >
            <SendIcon />
          </button>
        </div>
      </footer>

      {settingsOpen && (
        <SettingsModal
          onClose={() => setSettingsOpen(false)}
          onKeysChanged={refreshModels}
          onToast={showToast}
        />
      )}

      {toast && (
        <div className="toast" role="status" data-testid="toast">
          {toast}
        </div>
      )}
    </div>
  );
}

export default App;
