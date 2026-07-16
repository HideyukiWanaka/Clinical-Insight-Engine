// Backend REST base. Dev: Vite on 5173, FastAPI on 8000 (same host).
const API_BASE = `http://${location.hostname || "localhost"}:8000`;

export interface ModelInfo {
  id: string;
  label: string;
  provider: string;
  available: boolean;
}

export interface ModelList {
  default: string;
  models: ModelInfo[];
}

/** Fetch the selectable models (with per-model availability) and the default. */
export async function fetchModels(): Promise<ModelList> {
  const res = await fetch(`${API_BASE}/api/models`);
  if (!res.ok) throw new Error(`models fetch failed: ${res.status}`);
  return (await res.json()) as ModelList;
}

/** Upload one Markdown/text reference to the backend. Returns the saved name. */
export async function uploadReference(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/references`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`upload failed: ${res.status}`);
  const data = (await res.json()) as { filename: string };
  return data.filename;
}

/** A file counts as a text reference (Step 4). Images are Step 9. */
export function isTextReference(file: File): boolean {
  return (
    /\.(md|markdown|txt)$/i.test(file.name) ||
    file.type === "text/markdown" ||
    file.type === "text/plain"
  );
}
