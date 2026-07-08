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
      intent: Record<string, unknown>;
    };

interface ChatPaneProps {
  client: CieApiClient;
  connected: boolean;
  onConnectedChange: () => void;
  onInsertCode: (code: string) => void;
  onRunCode: (code: string, intent?: Record<string, unknown>) => void;
  /** Real dataset state — rides in POST /api/intent (replaces the hardcode). */
  datasetUploaded: boolean;
  /** statistical_results of the most recent run (null → continuation disabled). */
  priorStats: Record<string, unknown> | null;
  /** R script of the most recent run — carried as prior_r_script (§3.2). */
  priorScript: string;
  /** intent_object of the most recent run — the lineage base for continuation. */
  priorIntent: Record<string, unknown>;
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

/** Pull a human-readable test/method label out of statistical_results for the
 *  土台チップ (base chip). Returns null if none is present. */
function statTestName(stats: Record<string, unknown> | null): string | null {
  if (!stats) return null;
  for (const key of ["test", "test_name", "method", "analysis"]) {
    const v = stats[key];
    if (typeof v === "string" && v.trim()) return v;
  }
  return null;
}

export function ChatPane({
  client,
  connected,
  onConnectedChange,
  onInsertCode,
  onRunCode,
  datasetUploaded,
  priorStats,
  priorScript,
  priorIntent,
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
  // When true, the next free-text send starts a NEW intent lineage even though
  // priorStats is still present. Cleared once a run in the new lineage lands
  // (sticky to the new lineage — phase8 design §4.2 / R-1).
  const [newAnalysisPending, setNewAnalysisPending] = useState(false);
  const resetStatsRef = useRef<Record<string, unknown> | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  const add = (m: Msg) => setMessages((prev) => [...prev, m]);

  // Continuation is the default while a run has produced statistics AND the user
  // has not just pressed "＋ 新しい解析" (§3.1 2回目以降 / design §4.2).
  const continuationActive = priorStats != null && !newAnalysisPending;

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [messages]);

  // A run in the new lineage produced fresh statistics → continuation is sticky
  // again for this lineage.
  useEffect(() => {
    if (newAnalysisPending && priorStats && priorStats !== resetStatsRef.current) {
      setNewAnalysisPending(false);
    }
  }, [priorStats, newAnalysisPending]);

  function send() {
    if (continuationActive) void sendContinuation();
    else void sendIntent();
  }

  function newAnalysis() {
    if (busy) return;
    resetStatsRef.current = priorStats;
    setNewAnalysisPending(true);
    add({
      id: nextId(),
      kind: "system",
      text: "新しい解析を開始します。次の入力は新規の意図として解釈します。",
    });
  }

  async function sendContinuation() {
    const query = input.trim();
    if (!query || busy) return;
    setInput("");
    add({ id: nextId(), kind: "user", text: query });
    setBusy(true);
    add({ id: nextId(), kind: "system", text: "追加解析を生成しています…" });
    try {
      const res = await client.propose({
        continuation_query: query,
        prior_statistical_results: priorStats,
        prior_r_script: priorScript,
      });
      if (!res.analysis_proposal) {
        const reason =
          res.r_script_provenance?.reason || "追加解析を生成できませんでした。";
        add({
          id: nextId(),
          kind: "error",
          text: "追加解析の生成に失敗しました。",
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
        // Inherit the lineage intent so a re-run still drafts the manuscript.
        intent: priorIntent,
      });
    } catch (err) {
      pushError(err);
    } finally {
      setBusy(false);
    }
  }

  async function sendIntent() {
    const prompt = input.trim();
    if (!prompt || busy) return;
    setInput("");
    add({ id: nextId(), kind: "user", text: prompt });
    setBusy(true);
    try {
      const res = await client.intent({ prompt, dataset_uploaded: datasetUploaded });
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
        intent,
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
            onRunCode={onRunCode}
          />
        ))}
      </div>

      {/* 土台チップ: いま何を土台にしているかを常時可視化（design §4.2）。
          横に「＋ 新しい解析」を併置し、話題変更時のみ1操作で文脈をリセットする。 */}
      <div className="chat__base" data-testid="chat-base">
        <span
          className={
            "chat__base-chip" +
            (continuationActive ? " chat__base-chip--active" : "")
          }
          data-testid="base-chip"
          title="現在の追加対話が土台にしている解析"
        >
          {continuationActive
            ? `土台: ${intentSummary(priorIntent)}${
                statTestName(priorStats) ? ` / ${statTestName(priorStats)}` : ""
              }`
            : newAnalysisPending
              ? "新しい解析（次の入力は新規の意図）"
              : "統計結果なし（初回の意図を入力）"}
        </span>
        <button
          type="button"
          className="mini-btn"
          data-testid="new-analysis"
          onClick={newAnalysis}
          disabled={busy || !continuationActive}
          title="文脈をリセットし、次の入力を新規の解析として送信します"
        >
          ＋ 新しい解析
        </button>
      </div>

      <div className="chat__composer">
        <textarea
          data-testid="chat-input"
          value={input}
          placeholder={
            continuationActive ? "追加の解析を入力（継続）…" : "解析したい内容を入力…"
          }
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button
          className="btn"
          data-testid="chat-send"
          disabled={busy || !input.trim()}
          onClick={send}
        >
          {continuationActive ? "継続送信" : "送信"}
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
  onRunCode,
}: {
  msg: Msg;
  busy: boolean;
  onConfirm: (intent: Record<string, unknown>) => void;
  onInsertCode: (code: string) => void;
  onRunCode: (code: string, intent?: Record<string, unknown>) => void;
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
                  {/* Insert = editor cursor (no run); Run = POST /api/run only
                      (no insert). Two-stage flow per spec/ui §3.1 / §4. */}
                  <button
                    className="mini-btn"
                    data-testid="candidate-insert"
                    title="スクリプトへ挿入（実行しない）"
                    onClick={() => onInsertCode(c.r_code)}
                  >
                    ✓ 挿入
                  </button>
                  <button
                    className="mini-btn mini-btn--run"
                    data-testid="candidate-run"
                    disabled={busy}
                    title="挿入せず即実行（POST /api/run）"
                    onClick={() => onRunCode(c.r_code, msg.intent)}
                  >
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
