// Inline SVG icons — kept in code (no asset files) so the bundle stays self-contained.

export function PaperclipIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 8.5 12.5 17a4 4 0 0 1-5.66-5.66l8-8a2.5 2.5 0 0 1 3.54 3.54l-8 8a1 1 0 0 1-1.42-1.42l7.3-7.3" />
    </svg>
  );
}

export function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M22 2 11 13" />
      <path d="M22 2 15 22l-4-9-9-4 20-7z" />
    </svg>
  );
}

/** Approximation of the R logo: grey ring + blue R, reads on a dark button. */
export function RLogoIcon() {
  return (
    <svg viewBox="0 0 36 24" aria-hidden="true">
      <ellipse cx="18" cy="12" rx="17" ry="11" fill="#a8b1bd" />
      <ellipse cx="18" cy="12.8" rx="12.5" ry="7" fill="#2b2f36" />
      <text x="18" y="17" textAnchor="middle" fontSize="13" fontWeight="700"
        fontFamily="Arial, sans-serif" fill="#2775ba">R</text>
    </svg>
  );
}

/** Empty-state illustration: a stats report + a researcher. */
export function ResearcherIllustration() {
  return (
    <svg viewBox="0 0 120 96" fill="none" stroke="currentColor" strokeWidth="2.4"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="8" y="14" width="66" height="52" rx="6" />
      <line x1="20" y1="54" x2="68" y2="54" />
      <line x1="24" y1="54" x2="24" y2="44" />
      <line x1="32" y1="54" x2="32" y2="36" />
      <line x1="40" y1="54" x2="40" y2="47" />
      <circle cx="58" cy="34" r="10" />
      <path d="M58 34 58 24 A10 10 0 0 1 66.5 39 Z" fill="currentColor" stroke="none" />
      <circle cx="94" cy="40" r="9" />
      <path d="M80 72 a14 14 0 0 1 28 0" />
    </svg>
  );
}

/** Small assistant avatar glyph (a mini bar chart). */
export function AssistantAvatarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <line x1="6" y1="16" x2="6" y2="12" />
      <line x1="12" y1="16" x2="12" y2="7" />
      <line x1="18" y1="16" x2="18" y2="10" />
    </svg>
  );
}
