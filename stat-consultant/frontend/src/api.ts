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

export interface KeyStatus {
  provider: string;
  label: string;
  has_key: boolean;
}

async function keysResponse(res: Response): Promise<KeyStatus[]> {
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* keep status */
    }
    throw new Error(detail);
  }
  return ((await res.json()) as { providers: KeyStatus[] }).providers;
}

/** Which providers already have a stored key (never the key itself). */
export async function fetchKeyStatus(): Promise<KeyStatus[]> {
  return keysResponse(await fetch(`${API_BASE}/api/settings/keys`));
}

/** Save a provider's API key (stored server-side in the OS keychain). */
export async function saveApiKey(provider: string, apiKey: string): Promise<KeyStatus[]> {
  return keysResponse(
    await fetch(`${API_BASE}/api/settings/keys`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, api_key: apiKey }),
    }),
  );
}

/** Remove a provider's stored key. */
export async function clearApiKey(provider: string): Promise<KeyStatus[]> {
  return keysResponse(
    await fetch(`${API_BASE}/api/settings/keys/${provider}`, { method: "DELETE" }),
  );
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
