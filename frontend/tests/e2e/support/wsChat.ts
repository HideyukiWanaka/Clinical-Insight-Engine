import type { Page } from "@playwright/test";

// Test helper: mock the streaming chat endpoint WS /ws/chat (Phase 2). The real
// server runs the Planner and streams frames back over one socket per turn; the
// client (streamChat) opens a fresh socket for every chat turn and sends its
// request as the first message. These helpers emulate that protocol so e2e
// specs can drive the chat without a live backend — the same way the existing
// specs mock /ws/console.
//
// IMPORTANT: page.routeWebSocket installs a page init script, so it must be
// called BEFORE page.goto() (otherwise the already-loaded page opens a real
// socket). Install these helpers before connect()/goto().

export interface WsChatFrame {
  type: string;
  [k: string]: unknown;
}

/** True when the first message carries a resolved intent_object (a confirm/
 *  clarify follow-through or a continuation turn) rather than a raw prompt. */
export function hasIntentObject(msg: Record<string, unknown>): boolean {
  const io = msg.intent_object;
  return !!io && typeof io === "object" && Object.keys(io as object).length > 0;
}

/** The `delta` + terminal `proposal` frames for an analysis_proposal. */
export function proposalFrames(
  proposal: Record<string, unknown>,
  provenance: Record<string, unknown> = { llm_generated: true, from_cache: false, reason: "" },
): WsChatFrame[] {
  const explanation = String(
    (proposal as { explanation_markdown?: string }).explanation_markdown ?? "",
  );
  return [
    { type: "delta", text: explanation },
    {
      type: "proposal",
      execution_id: "exec-e2e",
      analysis_proposal: proposal,
      r_script_provenance: provenance,
    },
  ];
}

/** The terminal `figures` frame the visualization tool emits. */
export function figuresFrame(
  figures: Array<{ title: string; path?: string | null }>,
): WsChatFrame {
  return { type: "figures", execution_id: "viz-e2e", figures };
}

/** The terminal `manuscript` frame the reporting tool emits. */
export function manuscriptFrame(
  sections: Array<{ section_id: string; text: string; is_ai_generated: boolean }>,
): WsChatFrame {
  return { type: "manuscript", execution_id: "rep-e2e", manuscript_sections: sections };
}

/** The transparency `intent` echo the server emits before streaming a proposal
 *  on a high-confidence unambiguous turn. */
export function intentEcho(
  intent: Record<string, unknown>,
  confidence = 0.9,
): WsChatFrame {
  return { type: "intent", intent_object: intent, confidence_score: confidence };
}

/** Install a /ws/chat mock. `respond` maps the client's first message to the
 *  ordered frames the server would emit; this helper appends the terminal
 *  `done` frame and closes the socket (one connection per turn). Returns the
 *  accumulating list of received messages for post-hoc assertions.
 *
 *  MUST be awaited before page.goto() — routeWebSocket registration is async, so
 *  an un-awaited call races navigation and the page loads without the intercept
 *  (the client then opens a real socket that fails to connect). */
export async function routeWsChat(
  page: Page,
  respond: (msg: Record<string, unknown>) => WsChatFrame[],
): Promise<Record<string, unknown>[]> {
  const messages: Record<string, unknown>[] = [];
  await page.routeWebSocket(/\/ws\/chat/, (ws) => {
    ws.onMessage((raw) => {
      let msg: Record<string, unknown> = {};
      try {
        msg = JSON.parse(String(raw)) as Record<string, unknown>;
      } catch {
        /* a non-JSON frame never happens from the client; ignore */
      }
      messages.push(msg);
      for (const f of respond(msg)) ws.send(JSON.stringify(f));
      ws.send(JSON.stringify({ type: "done" }));
      ws.close();
    });
  });
  return messages;
}

/** Common case: a high-confidence turn. A prompt streams intent echo + proposal
 *  directly (no confirm gate); a resolved intent_object (or continuation)
 *  streams the proposal. Returns the received-messages list. Await before goto. */
export function installStandardChat(
  page: Page,
  opts: {
    intent: Record<string, unknown>;
    proposal: Record<string, unknown>;
    provenance?: Record<string, unknown>;
  },
): Promise<Record<string, unknown>[]> {
  return routeWsChat(page, (msg) =>
    hasIntentObject(msg)
      ? proposalFrames(opts.proposal, opts.provenance)
      : [intentEcho(opts.intent), ...proposalFrames(opts.proposal, opts.provenance)],
  );
}
