import { highlightCode } from "../highlight";
import { RLogoIcon } from "../icons";

interface CodeCardProps {
  reason: string;
  language: string;
  code: string;
  onSend: (code: string, language: string) => void;
}

/** One assistant_code block: a one-line reason label, a dark code panel
 *  (terminal-style dots + highlighted code), and a full-width 「RStudioへ送る」
 *  button. */
export function CodeCard({ reason, language, code, onSend }: CodeCardProps) {
  return (
    <div className="code-card">
      {reason && <p className="code-card__reason">{reason}</p>}
      <div className="code-card__unit">
        <div className="code-card__body">
          <div className="code-card__dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <pre className="code-card__pre">
            <code
              className={`hljs language-${language}`}
              // highlight.js returns escaped, tokenised HTML — safe to inject.
              dangerouslySetInnerHTML={{ __html: highlightCode(code, language) }}
            />
          </pre>
        </div>
        {/* No live Addin connection signal exists yet (that's Step 6), so every
         *  click both best-effort queues the code (/api/rstudio/insert) and
         *  always falls back to a clipboard copy — the permanent fallback
         *  per SPEC 4.3. */}
        <button
          type="button"
          className="rstudio-btn"
          data-testid="send-rstudio"
          onClick={() => onSend(code, language)}
        >
          <RLogoIcon />
          <span>RStudioへ送る</span>
        </button>
      </div>
    </div>
  );
}
