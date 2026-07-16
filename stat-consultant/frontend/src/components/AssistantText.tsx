import { useState } from "react";

interface AssistantTextProps {
  reason: string;
  detail: string;
}

/** One assistant_text block: the 一言 reason always shown; the detail is
 *  collapsed behind a click-to-expand toggle (SPEC 4.4), and the toggle only
 *  appears when there is detail to show. */
export function AssistantText({ reason, detail }: AssistantTextProps) {
  const [open, setOpen] = useState(false);
  const hasDetail = detail.trim().length > 0;

  return (
    <div className="assistant-text">
      {reason && <p className="assistant-text__reason">{reason}</p>}
      {hasDetail && (
        <>
          <button
            type="button"
            className="assistant-text__toggle"
            aria-expanded={open}
            data-testid="detail-toggle"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? "詳細を隠す ▲" : "詳細を見る ▼"}
          </button>
          {open && <p className="assistant-text__detail">{detail}</p>}
        </>
      )}
    </div>
  );
}
