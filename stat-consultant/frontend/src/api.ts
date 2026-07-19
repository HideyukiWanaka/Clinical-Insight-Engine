// Backend REST base. Dev: Vite on 5173, FastAPI on 8000 (same host).
const API_BASE = `http://${location.hostname || "localhost"}:8000`;

export interface ModelInfo {
  id: string;
  label: string;
  provider: string;
}

export interface ModelList {
  default: string;
  models: ModelInfo[];
}

/** Fetch the currently invocable models (per configured provider) and the default. */
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
  if (!res.ok) {
    let detail = `upload failed: ${res.status}`;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* keep status */
    }
    throw new Error(detail);
  }
  const data = (await res.json()) as { filename: string };
  return data.filename;
}

/** A file the backend can turn into a reference (Step 4). Images are Step 9. */
export function isSupportedReference(file: File): boolean {
  return (
    /\.(md|markdown|txt|pdf)$/i.test(file.name) ||
    file.type === "text/markdown" ||
    file.type === "text/plain" ||
    file.type === "application/pdf"
  );
}

/** A reference figure attached for one turn only (Step 9): base64 payload for
 *  the WS frame plus a data URL for the in-chat preview. */
export interface ImagePayload {
  media_type: string;
  data: string; // base64 (no data: prefix)
  dataUrl: string; // full data URL for <img> preview
}

const IMAGE_MEDIA_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
]);

/** True for the image types the backend vision call accepts (Step 9). */
export function isImage(file: File): boolean {
  return (
    IMAGE_MEDIA_TYPES.has(file.type) ||
    /\.(png|jpe?g|gif|webp)$/i.test(file.name)
  );
}

/** Read an image File into an {@link ImagePayload} (base64 + data URL). */
export function readImagePayload(file: File): Promise<ImagePayload> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("画像の読み込みに失敗しました"));
    reader.onload = () => {
      const dataUrl = String(reader.result || "");
      const comma = dataUrl.indexOf(",");
      const header = dataUrl.slice(0, comma);
      const data = dataUrl.slice(comma + 1);
      // Prefer the browser-reported type; fall back to what FileReader encoded.
      const mediaMatch = /data:([^;]+)/.exec(header);
      const media_type =
        file.type && IMAGE_MEDIA_TYPES.has(file.type)
          ? file.type
          : mediaMatch?.[1] || "image/png";
      if (!data) {
        reject(new Error("画像が空です"));
        return;
      }
      resolve({ media_type, data, dataUrl });
    };
    reader.readAsDataURL(file);
  });
}

/** Queue one code block for the (not-yet-existing) RStudio Addin to consume (Step 6). */
export async function sendToRStudio(code: string, language: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/rstudio/insert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, language }),
  });
  if (!res.ok) {
    let detail = `送信に失敗しました: ${res.status}`;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* keep status */
    }
    throw new Error(detail);
  }
}
