import type { Message } from "../types";
import { AssistantText } from "./AssistantText";
import { CodeCard } from "./CodeCard";

/** Render one chat message: a user bubble, an assistant turn (a sequence of
 *  text / code blocks), or an error notice. */
export function ChatMessage({ msg }: { msg: Message }) {
  if (msg.role === "user") {
    return (
      <div className="msg msg--user">
        <div className="msg__bubble">{msg.text}</div>
      </div>
    );
  }

  if (msg.role === "error") {
    return (
      <div className="msg msg--assistant">
        <div className="msg__error">{msg.text}</div>
      </div>
    );
  }

  return (
    <div className="msg msg--assistant">
      <div className="msg__blocks">
        {msg.blocks.map((b, i) =>
          b.kind === "text" ? (
            <AssistantText key={i} reason={b.reason} detail={b.detail} />
          ) : (
            <CodeCard key={i} reason={b.reason} language={b.language} code={b.code} />
          ),
        )}
      </div>
    </div>
  );
}
