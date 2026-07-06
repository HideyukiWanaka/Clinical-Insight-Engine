// CIE API client (spec/api/rest-api-contract.md §2 auth, §3 REST).
//
// - Base URL defaults to http://127.0.0.1:8000 (cie/api/main.py serve()).
// - Every request carries the X-CIE-Token session header (§2). The token is
//   printed once by the API launcher ("[CIE-API] X-CIE-Token=…") and injected
//   here via VITE_CIE_TOKEN or set at runtime by the shell.
// - On any non-2xx response we parse the {error_code,message,detail} envelope
//   and throw an ApiError that carries `detail` — the UI surfaces it so a
//   failure is never silent (spec §5; mirrors cie/ui/screens/workbench.py
//   _render_output_pane which always shows error_detail).

import type {
  ConsoleMessage,
  ErrorEnvelope,
  IntentRequest,
  IntentResponse,
  ProposeRequest,
  ProposeResponse,
  RunRequest,
  RunResponse,
  VisualizeRequest,
  VisualizeResponse,
  WorkspaceResetResponse,
} from "./types";

const DEFAULT_BASE_URL = "http://127.0.0.1:8000";

/** Error thrown for any non-2xx response; `detail` is shown to the user. */
export class ApiError extends Error {
  readonly errorCode: string;
  readonly detail: string | null;
  readonly status: number;

  constructor(status: number, envelope: Partial<ErrorEnvelope>) {
    const detail = envelope.detail ?? null;
    super(envelope.message || `Request failed (HTTP ${status})`);
    this.name = "ApiError";
    this.status = status;
    this.errorCode = envelope.error_code || "UNKNOWN";
    this.detail = detail;
  }
}

export interface ApiClientOptions {
  baseUrl?: string;
  token?: string;
}

function resolveBaseUrl(explicit?: string): string {
  if (explicit) return explicit;
  const fromEnv = import.meta.env.VITE_CIE_API_BASE as string | undefined;
  return (fromEnv && fromEnv.trim()) || DEFAULT_BASE_URL;
}

function resolveToken(explicit?: string): string {
  if (explicit) return explicit;
  const fromEnv = import.meta.env.VITE_CIE_TOKEN as string | undefined;
  return (fromEnv && fromEnv.trim()) || "";
}

export class CieApiClient {
  private baseUrl: string;
  private token: string;

  constructor(opts: ApiClientOptions = {}) {
    this.baseUrl = resolveBaseUrl(opts.baseUrl).replace(/\/+$/, "");
    this.token = resolveToken(opts.token);
  }

  /** Update the session token at runtime (e.g. pasted from the launcher). */
  setToken(token: string): void {
    this.token = token.trim();
  }

  hasToken(): boolean {
    return this.token.length > 0;
  }

  getToken(): string {
    return this.token;
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  /** Same host/port as the REST base, ws:// or wss:// scheme (§4).
   *  "http://…" → "ws://…", "https://…" → "wss://…". */
  getWsBaseUrl(): string {
    return this.baseUrl.replace(/^http/i, "ws");
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CIE-Token": this.token,
        },
        body: JSON.stringify(body),
      });
    } catch (cause) {
      // Network/connection failure — surface a reason rather than failing mute.
      throw new ApiError(0, {
        error_code: "NETWORK_ERROR",
        message: "APIサーバに接続できません。",
        detail: `${this.baseUrl}${path} への接続に失敗しました (${String(
          (cause as Error)?.message ?? cause,
        )})。cie/api を 127.0.0.1 で起動しているか確認してください。`,
      });
    }

    if (!res.ok) {
      const envelope = await this.readErrorEnvelope(res);
      throw new ApiError(res.status, envelope);
    }
    return (await res.json()) as T;
  }

  private async readErrorEnvelope(res: Response): Promise<Partial<ErrorEnvelope>> {
    try {
      const data = (await res.json()) as unknown;
      // FastAPI wraps HTTPException payloads under `detail`; the API also
      // returns bare ErrorResponse envelopes (401 middleware). Handle both.
      if (data && typeof data === "object") {
        const obj = data as Record<string, unknown>;
        const inner =
          obj.detail && typeof obj.detail === "object"
            ? (obj.detail as Record<string, unknown>)
            : obj;
        return {
          error_code: String(inner.error_code ?? obj.error_code ?? "ERROR"),
          message: String(inner.message ?? obj.message ?? "リクエストに失敗しました。"),
          detail:
            (inner.detail as string | undefined) ??
            (typeof obj.detail === "string" ? (obj.detail as string) : null),
        };
      }
    } catch {
      // fall through to a generic envelope
    }
    return { error_code: `HTTP_${res.status}`, message: res.statusText };
  }

  /** POST /api/intent — natural-language prompt → intent_object (Planner). */
  intent(body: IntentRequest): Promise<IntentResponse> {
    return this.post<IntentResponse>("/api/intent", body);
  }

  /** POST /api/propose — intent_object (or continuation) → analysis_proposal. */
  propose(body: ProposeRequest): Promise<ProposeResponse> {
    return this.post<ProposeResponse>("/api/propose", body);
  }

  /** POST /api/run — execute an R script (Runtime). Failure is never silent:
   *  the response's `error_detail` is populated on any run failure (§3.3, §5). */
  run(body: RunRequest): Promise<RunResponse> {
    return this.post<RunResponse>("/api/run", body);
  }

  /** POST /api/visualize — statistical_results → figures (Visualization, §3.4). */
  visualize(body: VisualizeRequest): Promise<VisualizeResponse> {
    return this.post<VisualizeResponse>("/api/visualize", body);
  }

  /** POST /api/workspace/reset — delete the persisted .RData + summary so the
   *  next run starts from an empty workspace (workspace-persistence spec §3). */
  resetWorkspace(): Promise<WorkspaceResetResponse> {
    return this.post<WorkspaceResetResponse>("/api/workspace/reset", {});
  }

  /** GET /api/files/content — fetch a workspace image as an object URL.
   *  The image bytes need the X-CIE-Token header (§2), so a bare `<img src>`
   *  won't work; we fetch as a blob and return a URL the caller must revoke. */
  async fetchImageObjectUrl(path: string): Promise<string> {
    const url = `${this.baseUrl}/api/files/content?path=${encodeURIComponent(path)}`;
    const res = await fetch(url, { headers: { "X-CIE-Token": this.token } });
    if (!res.ok) {
      const envelope = await this.readErrorEnvelope(res);
      throw new ApiError(res.status, envelope);
    }
    return URL.createObjectURL(await res.blob());
  }

  /** WS /ws/console — run `rScript` and stream its sanitized stdout (§4.1).
   *
   * Auth is the first message (`{token,…}`, §2), not the HTTP middleware. The
   * backend executor is batch, so it streams the sanitized summary line-by-line
   * followed by an `exit` frame, then closes. Returns the socket so the caller
   * can close it early; `onClose` fires exactly once when the socket ends. */
  streamConsole(params: {
    rScript: string;
    executionId?: string;
    onMessage: (msg: ConsoleMessage) => void;
    onError: (message: string) => void;
    onClose: () => void;
  }): WebSocket {
    const ws = new WebSocket(`${this.getWsBaseUrl()}/ws/console`);
    let closed = false;
    const finish = () => {
      if (closed) return;
      closed = true;
      params.onClose();
    };

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          token: this.token,
          r_script: params.rScript,
          execution_id: params.executionId,
        }),
      );
    };
    ws.onmessage = (event) => {
      try {
        params.onMessage(JSON.parse(event.data as string) as ConsoleMessage);
      } catch {
        // A non-JSON frame should never happen; ignore rather than crash.
      }
    };
    ws.onerror = () => {
      params.onError(
        `コンソール接続に失敗しました (${this.getWsBaseUrl()}/ws/console)。`,
      );
    };
    ws.onclose = finish;
    return ws;
  }
}

/** Shared singleton used by the app; tests construct their own instances. */
export const apiClient = new CieApiClient();
