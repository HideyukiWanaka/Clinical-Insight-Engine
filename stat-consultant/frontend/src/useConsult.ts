import { useCallback, useEffect, useRef, useState } from "react";
import type { AssistantBlock, Message, ServerFrame } from "./types";

// Backend WS. Dev: Vite on 5173, FastAPI on 8000 (README). Same host, port 8000.
const WS_URL = `ws://${location.hostname || "localhost"}:8000/ws/consult`;

let seq = 0;
const nextId = () => `m${++seq}`;

function newConversationId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `c${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

/** Owns the WS connection and the running message list. Transport adapted from
 *  cie ChatPane (input/WS/send); the Planner-era message kinds are dropped. */
export function useConsult() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const conversationId = useRef<string>(newConversationId());
  // Blocks of the assistant turn currently streaming in, flushed on `done`.
  const pending = useRef<AssistantBlock[]>([]);

  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);

    ws.onmessage = (ev) => {
      let frame: ServerFrame;
      try {
        frame = JSON.parse(ev.data as string);
      } catch {
        return;
      }
      switch (frame.type) {
        case "assistant_text":
          pending.current.push({
            kind: "text",
            reason: frame.reason,
            detail: frame.detail,
          });
          break;
        case "assistant_code":
          pending.current.push({
            kind: "code",
            reason: frame.reason,
            language: frame.language,
            code: frame.code,
          });
          break;
        case "done": {
          const blocks = pending.current;
          pending.current = [];
          setBusy(false);
          if (blocks.length > 0) {
            setMessages((m) => [
              ...m,
              { id: nextId(), role: "assistant", blocks },
            ]);
          }
          break;
        }
        case "error":
          pending.current = [];
          setBusy(false);
          setMessages((m) => [
            ...m,
            { id: nextId(), role: "error", text: frame.reason },
          ]);
          break;
      }
    };

    return () => ws.close();
  }, []);

  const send = useCallback((text: string, model: string) => {
    const trimmed = text.trim();
    const ws = wsRef.current;
    if (!trimmed || !ws || ws.readyState !== WebSocket.OPEN) return;
    setMessages((m) => [...m, { id: nextId(), role: "user", text: trimmed }]);
    setBusy(true);
    ws.send(
      JSON.stringify({
        text: trimmed,
        conversation_id: conversationId.current,
        model,
      }),
    );
  }, []);

  return { messages, connected, busy, send };
}
