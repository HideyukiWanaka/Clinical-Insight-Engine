// Light/dark theme handling. The toggle stamps `data-theme` on <html> so it
// wins over the prefers-color-scheme default in both directions
// (spec/ui/ide-workbench-spec.md §2).
export type Theme = "light" | "dark";

const STORAGE_KEY = "cie.theme";

export function getInitialTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  const prefersDark =
    window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  return prefersDark ? "dark" : "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(STORAGE_KEY, theme);
}
