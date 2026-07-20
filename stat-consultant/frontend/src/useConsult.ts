import { useCallback, useEffect, useRef, useState } from "react";
import type { ImagePayload } from "./api";
import type { AssistantBlock, Message, ServerFrame } from "./types";

// Same-origin, like API_BASE in api.ts: FastAPI serves this page in the bundled
// app, and Vite proxies /ws in dev. Scheme follows the page so an https deploy
// doesn't get blocked as mixed content.
const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/consult`;

// Namespaced to match the R Addin's `statConsultant.baseUrl` option convention.
const CONVERSATION_ID_KEY = "statConsultant.conversationId";
const MESSAGES_KEY = "statConsultant.messages";

let seq = 0;
const nextId = () => `m${++seq}`;

function newConversationId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `c${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

/** Reuse the same conversation across reloads/restarts (single ongoing
 *  conversation only — no multi-conversation history, per SPEC 4.5/§10). */
function loadOrCreateConversationId(): string {
  try {
    const existing = localStorage.getItem(CONVERSATION_ID_KEY);
    if (existing) return existing;
  } catch {
    /* localStorage unavailable (private mode etc.) — fall through */
  }
  const id = newConversationId();
  try {
    localStorage.setItem(CONVERSATION_ID_KEY, id);
  } catch {
    /* non-fatal: conversation just won't persist across reloads */
  }
  return id;
}

/** Restore the last-rendered message list for instant display before the WS
 *  round-trip completes. Backend-side `turns` (Anthropic message shape) can't
 *  reconstruct this richer shape (language/reason per code block), so the
 *  display cache lives here, separate from the backend's own persistence. */
function loadCachedMessages(): Message[] {
  try {
    const raw = localStorage.getItem(MESSAGES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as Message[]) : [];
  } catch {
    return [];
  }
}

const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000];

/** Owns the WS connection and the running message list. Transport adapted from
 *  cie ChatPane (input/WS/send); the Planner-era message kinds are dropped.
 *
 *  Reconnects on drop (e.g. laptop sleep) with backoff, and persists the
 *  conversation id + rendered messages to localStorage so the same
 *  conversation resumes across a reload or the next day. */
export function useConsult() {
  const [messages, setMessages] = useState<Message[]>(loadCachedMessages);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const conversationId = useRef<string>(loadOrCreateConversationId());
  // Blocks of the assistant turn currently streaming in, flushed on `done`.
  const pending = useRef<AssistantBlock[]>([]);
  const reconnectAttempt = useRef(0);
  const reconnectTimer = useRef<number | undefined>(undefined);
  const stopped = useRef(false);
  // Lets the WS onclose handler (defined once, inside the connect effect
  // below) see the latest `busy` without re-running that effect on every change.
  const busyRef = useRef(busy);

  useEffect(() => {
    try {
      localStorage.setItem(MESSAGES_KEY, JSON.stringify(messages));
    } catch {
      /* quota exceeded or unavailable — non-fatal, just skip this write */
    }
  }, [messages]);

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  useEffect(() => {
    stopped.current = false;

    function connect() {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttempt.current = 0;
        setConnected(true);
      };

      ws.onclose = () => {
        // Unmounting closes the socket intentionally — skip the error
        // message and reconnect entirely; the component is going away.
        if (stopped.current) return;

        setConnected(false);
        // A turn was mid-flight when the socket dropped: the server never
        // committed a partial assistant turn either (it only adds one after
        // the full reply is generated), so there's nothing to resume — drop
        // it and let the user resend.
        if (pending.current.length > 0 || busyRef.current) {
          pending.current = [];
          setBusy(false);
          setMessages((m) => [
            ...m,
            {
              id: nextId(),
              role: "error",
              text: "接続が切れたため、もう一度お試しください。",
            },
          ]);
        }
        const delay =
          RECONNECT_DELAYS_MS[
            Math.min(reconnectAttempt.current, RECONNECT_DELAYS_MS.length - 1)
          ];
        reconnectAttempt.current += 1;
        reconnectTimer.current = window.setTimeout(connect, delay);
      };

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
    }

    connect();

    return () => {
      stopped.current = true;
      window.clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, []);

  /** Start a new conversation: fresh id, cleared history. The WS connection
   *  itself doesn't need to change — `send()` sends `conversation_id` per
   *  message, not per connection. */
  const resetConversation = useCallback(() => {
    const id = newConversationId();
    conversationId.current = id;
    try {
      localStorage.setItem(CONVERSATION_ID_KEY, id);
    } catch {
      /* non-fatal: new id just won't survive a reload */
    }
    pending.current = [];
    setBusy(false);
    setMessages([]);
  }, []);

  const send = useCallback(
    (text: string, model: string, image?: ImagePayload | null) => {
      const trimmed = text.trim();
      const ws = wsRef.current;
      // A reference figure alone (no text) is a valid turn (Step 9).
      if ((!trimmed && !image) || !ws || ws.readyState !== WebSocket.OPEN) return;
      setMessages((m) => [
        ...m,
        {
          id: nextId(),
          role: "user",
          text: trimmed,
          ...(image ? { imageUrl: image.dataUrl } : {}),
        },
      ]);
      setBusy(true);
      ws.send(
        JSON.stringify({
          text: trimmed,
          conversation_id: conversationId.current,
          model,
          // The figure is sent for this turn only; the backend never persists it.
          ...(image
            ? { image: { media_type: image.media_type, data: image.data } }
            : {}),
        }),
      );
    },
    [],
  );

  return { messages, connected, busy, send, resetConversation };
}
