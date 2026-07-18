import { useEffect, useRef, useState } from "react";
import "./App.css";
import researcherArt from "./assets/researcher.png";
import {
  fetchModels,
  type ImagePayload,
  isImage,
  isSupportedReference,
  type ModelInfo,
  readImagePayload,
  sendToRStudio,
  uploadReference,
} from "./api";
import { ChatMessage } from "./components/ChatMessage";
import { SettingsModal } from "./components/SettingsModal";
import { GearIcon, PaperclipIcon, SendIcon } from "./icons";
import { useConsult } from "./useConsult";

function App() {
  const { messages, connected, busy, send } = useConsult();
  const [input, setInput] = useState("");
  // A reference figure staged for the next turn only (Step 9); not persisted.
  const [pendingImage, setPendingImage] = useState<ImagePayload | null>(null);
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
    // Send when there's text OR a staged reference figure (Step 9).
    if ((!input.trim() && !pendingImage) || busy) return;
    send(input, model, pendingImage);
    setInput("");
    setPendingImage(null);
  }

  // No live Addin connection signal exists yet (Step 6 adds the real Addin +
  // heartbeat). Per SPEC 4.3, the clipboard copy is the permanent fallback —
  // every click copies to clipboard, and best-effort queues the code too so
  // a future Addin poll has something to consume.
  function handleSendToRStudio(code: string, language: string) {
    sendToRStudio(code, language).catch(() => {
      /* queueing failure is non-fatal; the clipboard copy is the real fallback */
    });

    navigator.clipboard
      .writeText(code)
      .then(() => showToast("コピーしました"))
      .catch(() => showToast("コピーに失敗しました。手動でコピーしてください"));
  }

  function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file
    if (!file) return;
    // One attach button, auto-routed by type. Images → this-turn 参考図 (Step 9);
    // Markdown/text/PDF → persisted reference store (Step 4).
    if (isImage(file)) {
      readImagePayload(file)
        .then((img) => {
          setPendingImage(img);
          showToast("今回の参考図として送信します");
        })
        .catch((err) =>
          showToast(err instanceof Error ? err.message : "画像の読み込みに失敗しました"),
        );
      return;
    }
    if (!isSupportedReference(file)) {
      showToast("画像、またはテキスト/Markdown/PDF を選んでください");
      return;
    }
    uploadReference(file)
      .then(() => showToast("参考資料として保存しました"))
      .catch((e) =>
        showToast(e instanceof Error ? e.message : "アップロードに失敗しました"),
      );
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
          messages.map((m) => (
            <ChatMessage key={m.id} msg={m} onSendToRStudio={handleSendToRStudio} />
          ))
        )}
      </main>

      <footer className="app__composer">
        {pendingImage && (
          <div className="composer__figure" data-testid="pending-figure">
            <img
              className="composer__figure-thumb"
              src={pendingImage.dataUrl}
              alt="添付した参考図"
            />
            <span className="composer__figure-label">今回の参考図</span>
            <button
              type="button"
              className="composer__figure-remove"
              aria-label="参考図を取り消す"
              title="参考図を取り消す"
              onClick={() => setPendingImage(null)}
            >
              ×
            </button>
          </div>
        )}
        <div className="composer__pill">
          <input
            ref={fileRef}
            type="file"
            accept=".md,.markdown,.txt,.pdf,.png,.jpg,.jpeg,.gif,.webp,text/markdown,text/plain,application/pdf,image/png,image/jpeg,image/gif,image/webp"
            hidden
            data-testid="file-input"
            onChange={onPickFile}
          />
          <button
            type="button"
            className="composer__attach"
            data-testid="attach"
            aria-label="ファイルを添付"
            title="参考資料（Markdown/テキスト/PDF）または参考図（画像）を添付"
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
            disabled={busy || (!input.trim() && !pendingImage)}
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
