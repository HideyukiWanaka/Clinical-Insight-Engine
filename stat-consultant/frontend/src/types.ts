// Frames exchanged over WS /ws/consult (backend SPEC 4.4).

/** A block within one assistant turn. */
export type AssistantBlock =
  | { kind: "text"; reason: string; detail: string }
  | { kind: "code"; reason: string; language: string; code: string };

/** A rendered chat message. A user message may carry an attached reference
 *  figure preview (Step 9); ``text`` may be empty when only a figure was sent. */
export type Message =
  | { id: string; role: "user"; text: string; imageUrl?: string }
  | { id: string; role: "assistant"; blocks: AssistantBlock[] }
  | { id: string; role: "error"; text: string };

/** Server → client frames. */
export type ServerFrame =
  | { type: "assistant_text"; reason: string; detail: string }
  | { type: "assistant_code"; reason: string; language: string; code: string }
  | { type: "done" }
  | { type: "error"; reason: string };
