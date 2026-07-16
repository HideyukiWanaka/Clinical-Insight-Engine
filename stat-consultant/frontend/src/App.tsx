import { useEffect, useRef, useState } from "react";
import "./App.css";
import { ChatMessage } from "./components/ChatMessage";
import { useConsult } from "./useConsult";

function App() {
  const { messages, connected, busy, send } = useConsult();
  const [input, setInput] = useState("");
  const logRef = useRef<HTMLDivElement>(null);

  // Keep the newest message in view as the conversation grows.
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [messages]);

  function submit() {
    if (!input.trim() || busy) return;
    send(input);
    setInput("");
  }

  return (
    <div className="app">
      <header className="app__header">
        <span className="app__title">Stat Consultant</span>
        <span
          className={`app__status ${connected ? "is-on" : "is-off"}`}
          title={connected ? "接続中" : "未接続"}
        />
      </header>

      <main className="app__log" ref={logRef}>
        {messages.length === 0 ? (
          <div className="app__empty">
            統計の相談をどうぞ。例:「A群とB群の血圧を比較したい」
          </div>
        ) : (
          messages.map((m) => <ChatMessage key={m.id} msg={m} />)
        )}
      </main>

      <footer className="app__composer">
        <textarea
          className="composer__input"
          data-testid="chat-input"
          value={input}
          rows={1}
          placeholder="統計の相談を入力…（Enterで送信 / Shift+Enterで改行）"
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
          className="btn btn--accent composer__send"
          data-testid="chat-send"
          disabled={busy || !input.trim()}
          onClick={submit}
        >
          送信
        </button>
      </footer>
    </div>
  );
}

export default App;
