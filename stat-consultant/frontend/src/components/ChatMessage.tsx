import type { Message } from "../types";
import { AssistantAvatarIcon } from "../icons";
import { AssistantText } from "./AssistantText";
import { CodeCard } from "./CodeCard";

/** Render one chat message: a user bubble, an assistant turn (avatar + a
 *  sequence of text / code blocks), or an error notice. */
export function ChatMessage({
  msg,
  onSendToRStudio,
}: {
  msg: Message;
  onSendToRStudio: (code: string, language: string) => void;
}) {
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
        <span className="msg__avatar" aria-hidden="true">
          <AssistantAvatarIcon />
        </span>
        <div className="msg__error">{msg.text}</div>
      </div>
    );
  }

  return (
    <div className="msg msg--assistant">
      <span className="msg__avatar" aria-hidden="true">
        <AssistantAvatarIcon />
      </span>
      <div className="msg__blocks">
        {msg.blocks.map((b, i) =>
          b.kind === "text" ? (
            <AssistantText key={i} reason={b.reason} detail={b.detail} />
          ) : (
            <CodeCard
              key={i}
              reason={b.reason}
              language={b.language}
              code={b.code}
              onSend={onSendToRStudio}
            />
          ),
        )}
      </div>
    </div>
  );
}
