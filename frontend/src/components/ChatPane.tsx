import { useEffect, useRef, useState } from "react";
import type { CieApiClient } from "../api/client";
import type {
  ClarificationOption,
  CodeCandidate,
  Figure,
  ManuscriptSection,
} from "../api/types";

type Msg =
  | { id: string; kind: "user"; text: string }
  | { id: string; kind: "ai"; text: string }
  | { id: string; kind: "system"; text: string }
  | { id: string; kind: "error"; text: string; detail?: string | null }
  | {
      id: string;
      kind: "clarify";
      text: string;
      options: ClarificationOption[];
      intent: Record<string, unknown>;
      answered?: boolean;
    }
  | { id: string; kind: "confirm"; intent: Record<string, unknown>; summary: string }
  | {
      id: string;
      kind: "proposal";
      explanation: string;
      candidates: CodeCandidate[];
      recommendedId?: string;
      intent: Record<string, unknown>;
      offCatalog?: boolean;
      caveat?: string;
    }
  | { id: string; kind: "figures"; figures: Figure[]; warning?: string }
  | { id: string; kind: "manuscript"; sections: ManuscriptSection[] };

interface ChatPaneProps {
  client: CieApiClient;
  connected: boolean;
  /** Open the API 接続設定 modal (single place to set the session token). */
  onOpenSettings: () => void;
  onInsertCode: (code: string) => void;
  onRunCode: (code: string, intent?: Record<string, unknown>) => void;
  /** statistical_results of the most recent run (null → continuation disabled). */
  priorStats: Record<string, unknown> | null;
  /** R script of the most recent run — carried as prior_r_script (§3.2). */
  priorScript: string;
  /** intent_object of the most recent run — the lineage base for continuation. */
  priorIntent: Record<string, unknown>;
}

let seq = 0;
const nextId = () => `m${++seq}`;

/** Stable per-mount conversation id so the server can keep the running chat
 *  history for WS /ws/chat (falls back when crypto.randomUUID is unavailable). */
function newConversationId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `c${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

// Send-shortcut label: ⌘ on macOS, Ctrl elsewhere (both are accepted).
const modKeyLabel = /Mac|iP(hone|ad|od)/.test(navigator.platform) ? "⌘" : "Ctrl";

function optionLabel(opt: Record<string, unknown>, i: number): string {
  const cand =
    opt.label ?? opt.question ?? opt.option_text ?? opt.text ?? opt.description;
  if (typeof cand === "string" && cand.trim()) return cand;
  return `選択肢 ${i + 1}: ${JSON.stringify(opt)}`;
}

/** Normalize a raw API clarification option into the structured shape the chat
 *  renders and acts on (a clickable answer carries its intent_override). */
function toClarificationOption(
  opt: Record<string, unknown>,
  i: number,
): ClarificationOption {
  const override =
    opt.intent_override && typeof opt.intent_override === "object"
      ? (opt.intent_override as Record<string, unknown>)
      : undefined;
  return {
    option_id: typeof opt.option_id === "string" ? opt.option_id : undefined,
    label: optionLabel(opt, i),
    intent_override: override,
  };
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
  onOpenSettings,
  onInsertCode,
  onRunCode,
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
  // When true, the next free-text send starts a NEW intent lineage even though
  // priorStats is still present. Cleared once a run in the new lineage lands
  // (sticky to the new lineage — phase8 design §4.2 / R-1).
  const [newAnalysisPending, setNewAnalysisPending] = useState(false);
  const resetStatsRef = useRef<Record<string, unknown> | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const conversationId = useRef<string>(newConversationId());

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
    if (continuationActive) sendContinuation();
    else sendIntent();
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

  // Follow-up (継続) turn: stream over WS just like a fresh turn, but ride the
  // lineage intent + prior results/script so the server extends the prior
  // analysis. The explanation types in live (delta) and the proposal inherits
  // priorIntent so a re-run still drafts the manuscript. R execution stays
  // human-gated — candidates are never auto-run.
  function sendContinuation() {
    const query = input.trim();
    if (!query || busy) return;
    setInput("");
    add({ id: nextId(), kind: "user", text: query });
    runChat({
      intentObject: priorIntent,
      continuationQuery: query,
      priorStatisticalResults: priorStats,
      priorRScript: priorScript,
    });
  }

  function sendIntent() {
    const prompt = input.trim();
    if (!prompt || busy) return;
    setInput("");
    add({ id: nextId(), kind: "user", text: prompt });
    runChat({ prompt });
  }

  // Explicit tool affordance (図/原稿): the Dialog agent's deterministic routing
  // gate. Runs the chosen tool on the prior run's results over WS /ws/chat — no
  // free-text guessing, so a code refinement is never mistaken for a tool call.
  function runTool(tool: "visualization" | "reporting") {
    if (busy || priorStats == null) return;
    add({
      id: nextId(),
      kind: "user",
      text: tool === "visualization" ? "この結果で図を作成" : "この結果で原稿を作成",
    });
    runChat({
      requestedTool: tool,
      intentObject: priorIntent,
      priorStatisticalResults: priorStats,
      priorRScript: priorScript,
    });
  }

  // Apply a clicked clarification option: merge its intent_override into the
  // Planner's intent and stream the proposal for it (skips the Planner). The
  // merged intent carries the resolved field (outcome_variables, paired, …),
  // which the StatisticsAgent reads directly.
  function answerClarification(
    msgId: string,
    opt: ClarificationOption,
    intent: Record<string, unknown>,
  ) {
    if (busy) return;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId && m.kind === "clarify" ? { ...m, answered: true } : m,
      ),
    );
    add({ id: nextId(), kind: "user", text: opt.label });
    const merged = { ...intent, ...(opt.intent_override ?? {}) };
    runChat({ intentObject: merged });
  }

  // Confirm a low-confidence intent → stream its proposal (skips the Planner).
  function confirmIntent(intent: Record<string, unknown>) {
    if (busy) return;
    runChat({ intentObject: intent });
  }

  // Drive one chat turn over WS /ws/chat. With `prompt`, the server runs the
  // Planner and routes to a clarify/confirm frame or (high confidence) an
  // `intent` echo + streamed proposal. With `intentObject`, it streams the
  // proposal directly. The explanation types in live (delta frames) inside one
  // AI bubble that becomes the full proposal on the terminal `proposal` frame.
  // Overlap is prevented by callers (inputs disabled while busy); R execution
  // stays human-gated — candidates are never auto-run here.
  function runChat(opts: {
    prompt?: string;
    intentObject?: Record<string, unknown>;
    continuationQuery?: string;
    priorStatisticalResults?: Record<string, unknown> | null;
    priorRScript?: string;
    requestedTool?: "visualization" | "reporting";
  }) {
    setBusy(true);
    let streamId: string | null = null;
    let settled = false;
    let resolvedIntent: Record<string, unknown> = opts.intentObject ?? {};

    const ensureStreamBubble = (): string => {
      if (streamId == null) {
        streamId = nextId();
        add({ id: streamId, kind: "ai", text: "" });
      }
      return streamId;
    };

    client.streamChat({
      conversationId: conversationId.current,
      prompt: opts.prompt,
      intentObject: opts.intentObject,
      continuationQuery: opts.continuationQuery,
      priorStatisticalResults: opts.priorStatisticalResults,
      priorRScript: opts.priorRScript,
      requestedTool: opts.requestedTool,
      onMessage: (ev) => {
        switch (ev.type) {
          case "intent":
            // High-confidence hand-off: echo the understood intent so the step
            // is transparent, never silent (the user can correct it next turn).
            resolvedIntent = ev.intent_object ?? resolvedIntent;
            add({
              id: nextId(),
              kind: "ai",
              text: `${intentSummary(resolvedIntent)}\n解析コードを提案します。`,
            });
            break;
          case "clarify":
            settled = true;
            add({
              id: nextId(),
              kind: "clarify",
              text: "もう少し詳しく教えてください。以下から選ぶか、自由入力で訂正してください:",
              options: (ev.clarification_options ?? []).map(toClarificationOption),
              intent: ev.intent_object ?? {},
            });
            break;
          case "confirm":
            settled = true;
            add({
              id: nextId(),
              kind: "confirm",
              intent: ev.intent_object ?? {},
              summary: intentSummary(ev.intent_object ?? {}),
            });
            break;
          case "delta": {
            const id = ensureStreamBubble();
            setMessages((prev) =>
              prev.map((x) =>
                x.id === id && x.kind === "ai"
                  ? { ...x, text: x.text + ev.text }
                  : x,
              ),
            );
            break;
          }
          case "proposal": {
            settled = true;
            const p = ev.analysis_proposal;
            const msg: Msg = {
              id: streamId ?? nextId(),
              kind: "proposal",
              explanation: p.explanation_markdown ?? "",
              candidates: p.code_candidates ?? [],
              recommendedId: p.recommended_candidate_id,
              intent: resolvedIntent,
              offCatalog: p.off_catalog,
              caveat: p.caveat_markdown,
            };
            if (streamId != null) {
              const sid = streamId;
              setMessages((prev) => prev.map((x) => (x.id === sid ? msg : x)));
            } else {
              add(msg);
            }
            break;
          }
          case "figures":
            settled = true;
            add({
              id: nextId(),
              kind: "figures",
              figures: ev.figures ?? [],
              warning: ev.warning,
            });
            break;
          case "manuscript":
            settled = true;
            add({
              id: nextId(),
              kind: "manuscript",
              sections: ev.manuscript_sections ?? [],
            });
            break;
          case "error":
            settled = true;
            add({
              id: nextId(),
              kind: "error",
              text: "コード生成に失敗しました。",
              detail:
                ev.reason ||
                ev.r_script_provenance?.reason ||
                "提案を生成できませんでした。",
            });
            break;
          // "done" → no action; onClose clears busy.
        }
      },
      onError: (message) => {
        if (settled) return;
        settled = true;
        add({ id: nextId(), kind: "error", text: "接続エラー", detail: message });
      },
      onClose: () => {
        if (!settled) {
          // Socket closed before any terminal frame — surface it, never silent.
          add({
            id: nextId(),
            kind: "error",
            text: "処理が中断されました。",
            detail: "サーバとの接続が終了しました。",
          });
        }
        setBusy(false);
      },
    });
  }

  return (
    <div className="chat">
      <div className="chat__log" ref={logRef} data-testid="chat-log">
        {!connected && (
          <div className="msg msg--ai" data-testid="token-setter">
            <span className="msg__role">接続</span>
            APIに未接続です。接続設定でセッショントークンを設定してください
            （ヘッダー右上のステータスからも開けます）。
            <div className="confirm-row">
              <button
                className="btn btn--ghost"
                data-testid="open-settings-from-chat"
                onClick={onOpenSettings}
              >
                接続設定を開く
              </button>
            </div>
          </div>
        )}

        {messages.map((m) => (
          <MessageView
            key={m.id}
            msg={m}
            busy={busy}
            client={client}
            onConfirm={confirmIntent}
            onClarify={answerClarification}
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
        {/* 明示的なツール操作（決定論ゲート）: 直近の解析結果に対して図/原稿を
            生成する。自由文からの推測はせず、押下＝そのツールに確定ルーティング。 */}
        <button
          type="button"
          className="mini-btn"
          data-testid="tool-visualize"
          onClick={() => runTool("visualization")}
          disabled={busy || !continuationActive}
          title="直近の結果から図を生成します"
        >
          📊 図を作成
        </button>
        <button
          type="button"
          className="mini-btn"
          data-testid="tool-report"
          onClick={() => runTool("reporting")}
          disabled={busy || !continuationActive}
          title="直近の結果から原稿セクションを生成します"
        >
          📝 原稿を作成
        </button>
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
            (continuationActive
              ? "追加の解析を入力（継続）…"
              : "解析したい内容を入力…") + `（${modKeyLabel}+Enterで送信）`
          }
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            // Send only on Cmd/Ctrl+Enter. A plain Enter inserts a newline —
            // and, critically, an Enter that confirms an IME conversion
            // (isComposing) never sends the message mid-composition.
            if (
              e.key === "Enter" &&
              (e.metaKey || e.ctrlKey) &&
              !e.nativeEvent.isComposing
            ) {
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
          title={`${modKeyLabel}+Enter でも送信できます`}
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
  client,
  onConfirm,
  onClarify,
  onInsertCode,
  onRunCode,
}: {
  msg: Msg;
  busy: boolean;
  client: CieApiClient;
  onConfirm: (intent: Record<string, unknown>) => void;
  onClarify: (
    msgId: string,
    opt: ClarificationOption,
    intent: Record<string, unknown>,
  ) => void;
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
            {msg.options.map((o, i) => {
              // An option with an intent_override is answerable — clicking it
              // applies the choice and proceeds. Options without an override
              // (rare, e.g. an informational prompt) stay non-interactive.
              const actionable = !!o.intent_override && !msg.answered;
              return (
                <button
                  key={o.option_id ?? i}
                  type="button"
                  className="mini-btn"
                  data-testid="clarify-option"
                  disabled={!actionable || busy}
                  style={actionable ? undefined : { cursor: "default" }}
                  onClick={
                    actionable
                      ? () => onClarify(msg.id, o, msg.intent)
                      : undefined
                  }
                >
                  {o.label}
                </button>
              );
            })}
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
          {msg.offCatalog && (
            <div className="msg msg--warn" data-testid="off-catalog-warning" role="alert">
              {msg.caveat ??
                "⚠️ この解析は標準Skillに無いパターンです。生成コードの統計的妥当性を必ずご確認ください。"}
            </div>
          )}
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
    case "figures":
      return (
        <div className="msg msg--ai" data-testid="chat-figures">
          <span className="msg__role">AI</span>
          {msg.warning && (
            <div className="figure__warning" data-testid="chat-figures-warning">
              ⚠️ 一部の図が生成できませんでした: {msg.warning}
            </div>
          )}
          {msg.figures.length === 0 ? (
            <div data-testid="chat-figures-empty">生成された図はありません。</div>
          ) : (
            <div className="figures">
              {msg.figures.map((f, i) => (
                <figure className="figure" key={i} data-testid="chat-figure">
                  {f.path && <ChatFigureImg client={client} path={f.path} title={f.title} />}
                  <figcaption className="figure__caption">{f.title}</figcaption>
                </figure>
              ))}
            </div>
          )}
        </div>
      );
    case "manuscript":
      return (
        <div className="msg msg--ai" data-testid="chat-manuscript">
          <span className="msg__role">AI</span>
          {msg.sections.length === 0 ? (
            <div data-testid="chat-manuscript-empty">
              生成された原稿セクションはありません。
            </div>
          ) : (
            msg.sections.map((s) => (
              <section
                key={s.section_id}
                className="manuscript"
                data-testid="chat-manuscript-section"
              >
                <div className="manuscript__bar">
                  <span className="manuscript__title">{s.section_id}</span>
                  {s.is_ai_generated && <span className="manuscript__ai">AI生成</span>}
                </div>
                {/* Copyable text: a plain, selectable block — no auto-clipboard (§3.5). */}
                <pre className="manuscript__text">{s.text}</pre>
              </section>
            ))
          )}
        </div>
      );
    default:
      return null;
  }
}

/** Load a workspace figure as an auth-fetched object URL (a bare <img src> can't
 *  send the X-CIE-Token header). Revokes the URL on unmount / path change. */
function ChatFigureImg({
  client,
  path,
  title,
}: {
  client: CieApiClient;
  path: string;
  title: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;
    client
      .fetchImageObjectUrl(path)
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        revoked = u;
        setUrl(u);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [client, path]);

  if (failed) {
    return (
      <div className="figure__error" data-testid="chat-figure-error">
        図を読み込めませんでした（{path}）。
      </div>
    );
  }
  if (!url) return <div className="figure__loading">図を読み込み中…</div>;
  return <img src={url} alt={title} className="figure__img" data-testid="chat-figure-img" />;
}
