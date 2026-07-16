// Minimal syntax highlighter: highlight.js core with only the R grammar
// registered, keeping the bundle small. Replies are R (SPEC §6).
import hljs from "highlight.js/lib/core";
import r from "highlight.js/lib/languages/r";
import "highlight.js/styles/nord.css"; // dark code theme (navy, cool tones)

hljs.registerLanguage("r", r);

/** Return highlighted HTML for a code string. Falls back to plain (escaped)
 *  text for unknown languages so nothing ever renders raw/unescaped. */
export function highlightCode(code: string, language: string): string {
  const lang = hljs.getLanguage(language) ? language : "r";
  return hljs.highlight(code, { language: lang }).value;
}
