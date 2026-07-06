import { useEffect, useRef, useState } from "react";
import { ApiError, type CieApiClient } from "../api/client";
import type { CodeCandidate } from "../api/types";

type Msg =
  | { id: string; kind: "user"; text: string }
  | { id: string; kind: "ai"; text: string }
  | { id: string; kind: "system"; text: string }
  | { id: string; kind: "error"; text: string; detail?: string | null }
  | { id: string; kind: "clarify"; text: string; options: string[] }
  | { id: string; kind: "confirm"; intent: Record<string, unknown>; summary: string }
  | {
      id: string;
      kind: "proposal";
      explanation: string;
      candidates: CodeCandidate[];
      recommendedId?: string;
    };

interface ChatPaneProps {
  client: CieApiClient;
  connected: boolean;
  onConnectedChange: () => void;
  onInsertCode: (code: string) => void;
}

let seq = 0;
const nextId = () => `m${++seq}`;

function optionLabel(opt: Record<string, unknown>, i: number): string {
  const cand =
    opt.label ?? opt.question ?? opt.option_text ?? opt.text ?? opt.description;
  if (typeof cand === "string" && cand.trim()) return cand;
  return `選択肢 ${i + 1}: ${JSON.stringify(opt)}`;
}

function intentSummary(intent: Record<string, unknown>): string {
  const nl = intent.natural_language_summary;
  if (typeof nl === "string" && nl.trim()) return nl;
  const parts: string[] = [];
  if (intent.objective) parts.push(`目的: ${String(intent.objective)}`);
  if (intent.outcome_type) parts.push(`アウトカム: ${String(intent.outcome_type)}`);
  if (intent.predictor_type) parts.push(`予測因子: ${String(intent.predictor_type)}`);
  return parts.length ? parts.join(" / ") : "意図を解釈しました。";
}

export function ChatPane({
  client,
  connected,
  onConnectedChange,
  onInsertCode,
}: ChatPaneProps) {
  const [messages, setMessages] = useState<Msg[]>([
    {
      id: nextId(),
      kind: "system",
      text: "解析したい内容を入力してください（例: 男女で収縮期血圧を比べたい）。",
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [tokenDraft, setTokenDraft] = useState("");
  const logRef = useRef<HTMLDivElement>(null);

  const add = (m: Msg) => setMessages((prev) => [...prev, m]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [messages]);

  async function sendIntent() {
    const prompt = input.trim();
    if (!prompt || busy) return;
    setInput("");
    add({ id: nextId(), kind: "user", text: prompt });
    setBusy(true);
    try {
      const res = await client.intent({ prompt, dataset_uploaded: false });
      if (res.requires_human_clarification) {
        add({
          id: nextId(),
          kind: "clarify",
          text: "もう少し詳しく教えてください。以下を確認させてください:",
          options: (res.clarification_options ?? []).map(optionLabel),
        });
      } else {
        add({
          id: nextId(),
          kind: "confirm",
          intent: res.intent_object,
          summary: intentSummary(res.intent_object),
        });
      }
    } catch (err) {
      pushError(err);
    } finally {
      setBusy(false);
    }
  }

  async function propose(intent: Record<string, unknown>) {
    if (busy) return;
    setBusy(true);
    add({ id: nextId(), kind: "system", text: "解析コードを生成しています…" });
    try {
      const res = await client.propose({ intent_object: intent });
      if (!res.analysis_proposal) {
        const reason =
          res.r_script_provenance?.reason || "提案を生成できませんでした。";
        add({
          id: nextId(),
          kind: "error",
          text: "コード生成に失敗しました。",
          detail: reason,
        });
        return;
      }
      const p = res.analysis_proposal;
      add({
        id: nextId(),
        kind: "proposal",
        explanation: p.explanation_markdown ?? "",
        candidates: p.code_candidates ?? [],
        recommendedId: p.recommended_candidate_id,
      });
    } catch (err) {
      pushError(err);
    } finally {
      setBusy(false);
    }
  }

  function pushError(err: unknown) {
    if (err instanceof ApiError) {
      add({
        id: nextId(),
        kind: "error",
        text: err.message,
        detail: err.detail,
      });
    } else {
      add({
        id: nextId(),
        kind: "error",
        text: "予期しないエラーが発生しました。",
        detail: String((err as Error)?.message ?? err),
      });
    }
  }

  function applyToken() {
    const t = tokenDraft.trim();
    if (!t) return;
    client.setToken(t);
    setTokenDraft("");
    onConnectedChange();
    add({ id: nextId(), kind: "system", text: "セッショントークンを設定しました。" });
  }

  return (
    <div className="chat">
      <div className="chat__log" ref={logRef} data-testid="chat-log">
        {!connected && (
          <div className="msg msg--ai" data-testid="token-setter">
            <span className="msg__role">接続</span>
            APIのセッショントークン（起動時に <code>[CIE-API] X-CIE-Token=…</code>{" "}
            で表示）を貼り付けてください。
            <div className="confirm-row">
              <input
                aria-label="セッショントークン"
                value={tokenDraft}
                onChange={(e) => setTokenDraft(e.target.value)}
                placeholder="X-CIE-Token"
                style={{ flex: 1, minWidth: 0 }}
              />
              <button className="btn btn--ghost" onClick={applyToken}>
                設定
              </button>
            </div>
          </div>
        )}

        {messages.map((m) => (
          <MessageView
            key={m.id}
            msg={m}
            busy={busy}
            onConfirm={propose}
            onInsertCode={onInsertCode}
          />
        ))}
      </div>

      <div className="chat__composer">
        <textarea
          data-testid="chat-input"
          value={input}
          placeholder="解析したい内容を入力…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void sendIntent();
            }
          }}
        />
        <button
          className="btn"
          data-testid="chat-send"
          disabled={busy || !input.trim()}
          onClick={() => void sendIntent()}
        >
          送信
        </button>
      </div>
    </div>
  );
}

function MessageView({
  msg,
  busy,
  onConfirm,
  onInsertCode,
}: {
  msg: Msg;
  busy: boolean;
  onConfirm: (intent: Record<string, unknown>) => void;
  onInsertCode: (code: string) => void;
}) {
  switch (msg.kind) {
    case "user":
      return <div className="msg msg--user">{msg.text}</div>;
    case "system":
      return <div className="msg msg--system">{msg.text}</div>;
    case "ai":
      return (
        <div className="msg msg--ai">
          <span className="msg__role">AI</span>
          {msg.text}
        </div>
      );
    case "error":
      return (
        <div className="msg msg--error" data-testid="chat-error">
          <span className="msg__role">エラー</span>
          {msg.text}
          {msg.detail && (
            <div style={{ marginTop: 4, fontSize: 12, opacity: 0.85 }}>
              理由: {msg.detail}
            </div>
          )}
        </div>
      );
    case "clarify":
      return (
        <div className="msg msg--ai" data-testid="chat-clarify">
          <span className="msg__role">AI</span>
          {msg.text}
          <div className="clarify">
            {msg.options.map((o, i) => (
              <span key={i} className="mini-btn" style={{ cursor: "default" }}>
                {o}
              </span>
            ))}
          </div>
        </div>
      );
    case "confirm":
      return (
        <div className="msg msg--ai" data-testid="chat-confirm">
          <span className="msg__role">AI</span>
          {msg.summary}
          <div className="confirm-row">
            <button
              className="btn"
              data-testid="confirm-propose"
              disabled={busy}
              onClick={() => onConfirm(msg.intent)}
            >
              この意図で解析を提案 →
            </button>
          </div>
        </div>
      );
    case "proposal":
      return (
        <div className="msg msg--ai" data-testid="chat-proposal">
          <span className="msg__role">AI</span>
          {msg.explanation && (
            <div data-testid="proposal-explanation">{msg.explanation}</div>
          )}
          {msg.candidates.map((c) => (
            <div className="candidate" key={c.candidate_id} data-testid="code-candidate">
              <div className="candidate__bar">
                <span>{c.label || c.candidate_id}</span>
                {msg.recommendedId === c.candidate_id && (
                  <span className="rec">推奨</span>
                )}
                <div className="candidate__actions">
                  {/* Actual insert/run behavior is Phase 3 (spec §3.1). */}
                  <button
                    className="mini-btn"
                    disabled
                    title="Phase 3 で有効化"
                    onClick={() => onInsertCode(c.r_code)}
                  >
                    ✓ 挿入
                  </button>
                  <button className="mini-btn" disabled title="Phase 3 で有効化">
                    ▶ 実行
                  </button>
                </div>
              </div>
              <pre>
                <code>{c.r_code}</code>
              </pre>
            </div>
          ))}
        </div>
      );
    default:
      return null;
  }
}
