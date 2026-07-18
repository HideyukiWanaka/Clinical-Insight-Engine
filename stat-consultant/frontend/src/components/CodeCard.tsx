import { highlightCode } from "../highlight";
import { RLogoIcon } from "../icons";

interface CodeCardProps {
  reason: string;
  language: string;
  code: string;
}

/** One assistant_code block: a one-line reason label, a dark code panel
 *  (terminal-style dots + highlighted code), and a full-width 「RStudioへ送る」
 *  button. Step 3 renders the button only — wiring is Step 5. */
export function CodeCard({ reason, language, code }: CodeCardProps) {
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
        {/* Visual only in Step 3; onClick wired to /api/rstudio in Step 5. */}
        <button type="button" className="rstudio-btn" data-testid="send-rstudio">
          <RLogoIcon />
          <span>RStudioへ送る</span>
        </button>
      </div>
    </div>
  );
}
