import { highlightCode } from "../highlight";

interface CodeCardProps {
  reason: string;
  language: string;
  code: string;
}

/** One assistant_code block: a one-line reason, the highlighted code, and the
 *  「RStudioへ送る」 button. Step 3 renders the button only — wiring is Step 5. */
export function CodeCard({ reason, language, code }: CodeCardProps) {
  return (
    <div className="code-card">
      {reason && <p className="code-card__reason">{reason}</p>}
      <pre className="code-card__pre">
        <code
          className={`hljs language-${language}`}
          // highlight.js returns escaped, tokenised HTML — safe to inject.
          dangerouslySetInnerHTML={{ __html: highlightCode(code, language) }}
        />
      </pre>
      <div className="code-card__actions">
        {/* Visual only in Step 3; onClick wired to /api/rstudio in Step 5. */}
        <button type="button" className="btn btn--accent" data-testid="send-rstudio">
          RStudioへ送る
        </button>
      </div>
    </div>
  );
}
