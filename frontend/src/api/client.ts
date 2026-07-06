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
  ErrorEnvelope,
  IntentRequest,
  IntentResponse,
  ProposeRequest,
  ProposeResponse,
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

  getBaseUrl(): string {
    return this.baseUrl;
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
}

/** Shared singleton used by the app; tests construct their own instances. */
export const apiClient = new CieApiClient();
