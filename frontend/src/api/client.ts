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
  ChatStreamEvent,
  ConsoleMessage,
  DatasetFromExistingRequest,
  DatasetStatusResponse,
  DatasetUploadResponse,
  ErrorEnvelope,
  ExcelConfirmRequest,
  ExcelInspectResponse,
  FileContentResponse,
  FileEntry,
  FilesResponse,
  IntentRequest,
  IntentResponse,
  KnowledgeApproveRequest,
  KnowledgeApproveResponse,
  KnowledgeIngestResponse,
  KnowledgeListResponse,
  KnowledgeRejectRequest,
  KnowledgeRejectResponse,
  KnowledgeReindexResponse,
  LlmApiKeyClearRequest,
  LlmApiKeyRequest,
  LlmProviderRequest,
  LlmSettingsResponse,
  ProposeRequest,
  ProposeResponse,
  ReportRequest,
  ReportResponse,
  RunRequest,
  RunResponse,
  StorageDirectoryRequest,
  StorageSettingsResponse,
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
  /** PII check names from a knowledge ingest 422 (§3.8); null otherwise. */
  readonly failedChecks: string[] | null;

  constructor(status: number, envelope: Partial<ErrorEnvelope>) {
    const detail = envelope.detail ?? null;
    super(envelope.message || `Request failed (HTTP ${status})`);
    this.name = "ApiError";
    this.status = status;
    this.errorCode = envelope.error_code || "UNKNOWN";
    this.detail = detail;
    this.failedChecks = envelope.failed_checks ?? null;
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

const TOKEN_STORAGE_KEY = "cie.session_token";

function resolveToken(explicit?: string): string {
  if (explicit) return explicit;
  // scripts/dev.sh mints one token per machine and writes it to both
  // frontend/.env.local (VITE_CIE_TOKEN) and the API's env — so the env var
  // always reflects the CURRENT API instance. It must win over a stored
  // token: otherwise, once the API is restarted with a fresh random token
  // (no dev.sh, or CIE_API_SESSION_TOKEN unset), a stale localStorage value
  // would keep shadowing the correct one forever, and every request would
  // 401 with no obvious way to recover short of manually clearing storage.
  const fromEnv = import.meta.env.VITE_CIE_TOKEN as string | undefined;
  if (fromEnv && fromEnv.trim()) return fromEnv.trim();
  // No build-time token configured (e.g. pointed at a remote API without
  // dev.sh) — fall back to whatever the user last pasted in 接続設定.
  try {
    const stored = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    if (stored && stored.trim()) return stored.trim();
  } catch {
    // Storage unavailable (private mode etc.) — no token available.
  }
  return "";
}

export class CieApiClient {
  private baseUrl: string;
  private token: string;

  constructor(opts: ApiClientOptions = {}) {
    this.baseUrl = resolveBaseUrl(opts.baseUrl).replace(/\/+$/, "");
    this.token = resolveToken(opts.token);
  }

  /** Update the session token at runtime (e.g. pasted from the launcher) and
   *  persist it so a page reload keeps the connection. */
  setToken(token: string): void {
    this.token = token.trim();
    try {
      if (this.token) window.localStorage.setItem(TOKEN_STORAGE_KEY, this.token);
      else window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    } catch {
      // Storage unavailable — the token still works for this session.
    }
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
        const failedChecks =
          (inner.failed_checks as string[] | undefined) ??
          (obj.failed_checks as string[] | undefined);
        return {
          error_code: String(inner.error_code ?? obj.error_code ?? "ERROR"),
          message: String(inner.message ?? obj.message ?? "リクエストに失敗しました。"),
          detail:
            (inner.detail as string | undefined) ??
            (typeof obj.detail === "string" ? (obj.detail as string) : null),
          failed_checks: Array.isArray(failedChecks) ? failedChecks : null,
        };
      }
    } catch {
      // fall through to a generic envelope
    }
    return { error_code: `HTTP_${res.status}`, message: res.statusText };
  }

  /** Authenticated GET returning JSON, with the same error framing as post(). */
  private async getJson<T>(path: string): Promise<T> {
    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}${path}`, {
        headers: { "X-CIE-Token": this.token },
      });
    } catch (cause) {
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

  /** Authenticated multipart file POST. We attach ONLY X-CIE-Token and let the
   *  browser set Content-Type (with its multipart boundary) — never set it by
   *  hand (R-4/K-4). Same error framing as post(). */
  private async postFile<T>(path: string, file: File): Promise<T> {
    const form = new FormData();
    form.append("file", file);
    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}${path}`, {
        method: "POST",
        headers: { "X-CIE-Token": this.token },
        body: form,
      });
    } catch (cause) {
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

  /** POST /api/dataset — register the working CSV (rest-api-contract §3.1 前提).
   *  The response is aggregate-only column metadata — no row values (§5). */
  uploadDataset(file: File): Promise<DatasetUploadResponse> {
    return this.postFile<DatasetUploadResponse>("/api/dataset", file);
  }

  /** POST /api/dataset/excel/inspect — upload an Excel workbook and get its
   *  sheet names back; the file is held server-side pending confirm. */
  inspectExcelDataset(file: File): Promise<ExcelInspectResponse> {
    return this.postFile<ExcelInspectResponse>("/api/dataset/excel/inspect", file);
  }

  /** POST /api/dataset/excel/confirm — register the chosen sheet of a pending
   *  Excel upload. Returns the same aggregate-only shape as uploadDataset. */
  confirmExcelDataset(body: ExcelConfirmRequest): Promise<DatasetUploadResponse> {
    return this.post<DatasetUploadResponse>("/api/dataset/excel/confirm", body);
  }

  /** GET /api/dataset — the currently registered dataset (null until an
   *  upload). Restores the 解析対象データ indicator after a page reload. */
  getDatasetStatus(): Promise<DatasetStatusResponse> {
    return this.getJson<DatasetStatusResponse>("/api/dataset");
  }

  /** POST /api/dataset/from_existing — register a CSV/Excel file already in
   *  the workspace (a GET /api/files path) without re-uploading it. CSV
   *  resolves to a DatasetUploadResponse; Excel resolves to an
   *  ExcelInspectResponse awaiting POST /api/dataset/excel/confirm. */
  registerExistingDataset(
    body: DatasetFromExistingRequest,
  ): Promise<DatasetUploadResponse | ExcelInspectResponse> {
    return this.post<DatasetUploadResponse | ExcelInspectResponse>(
      "/api/dataset/from_existing",
      body,
    );
  }

  /** POST /api/files — add a local file to the workspace under uploads/.
   *  Never overwrites (the server suffixes duplicate names). */
  uploadWorkspaceFile(file: File): Promise<FileEntry> {
    return this.postFile<FileEntry>("/api/files", file);
  }

  // ── AI provider / API key settings (/api/settings/llm) ─────────────────────
  // Distinct from the session token: this is "which LLM, and its key" — never
  // returns a key value, only per-provider has_key booleans.

  /** GET /api/settings/llm — active provider + which providers have a key. */
  getLlmSettings(): Promise<LlmSettingsResponse> {
    return this.getJson<LlmSettingsResponse>("/api/settings/llm");
  }

  /** POST /api/settings/llm/provider — switch the active provider. Takes
   *  effect on the next LLM call; no API restart needed. */
  setLlmProvider(body: LlmProviderRequest): Promise<LlmSettingsResponse> {
    return this.post<LlmSettingsResponse>("/api/settings/llm/provider", body);
  }

  /** POST /api/settings/llm/key — save a provider's API key (OS keyring). */
  saveLlmApiKey(body: LlmApiKeyRequest): Promise<LlmSettingsResponse> {
    return this.post<LlmSettingsResponse>("/api/settings/llm/key", body);
  }

  /** POST /api/settings/llm/key/clear — remove a provider's stored key. */
  clearLlmApiKey(body: LlmApiKeyClearRequest): Promise<LlmSettingsResponse> {
    return this.post<LlmSettingsResponse>("/api/settings/llm/key/clear", body);
  }

  // ── 保存先ルート設定 (/api/settings/storage) ─────────────────────────────
  // workspace_directory is wired into every R executor/agent at process
  // startup, so unlike the LLM provider above, changing it here only
  // persists to .env for the *next* launch — this process keeps using its
  // current path (see cie/api/routes/settings.py).

  /** GET /api/settings/storage — the paths this running process writes to. */
  getStorageSettings(): Promise<StorageSettingsResponse> {
    return this.getJson<StorageSettingsResponse>("/api/settings/storage");
  }

  /** POST /api/settings/storage/workspace_directory — persist a new
   *  workspace root to .env. Takes effect on the next launch only. */
  setWorkspaceDirectory(
    body: StorageDirectoryRequest,
  ): Promise<StorageSettingsResponse> {
    return this.post<StorageSettingsResponse>(
      "/api/settings/storage/workspace_directory",
      body,
    );
  }

  /** GET /api/files — read-only workspace listing (§3.6). */
  listFiles(): Promise<FilesResponse> {
    return this.getJson<FilesResponse>("/api/files");
  }

  /** GET /api/files/content — a text file's content + language (§3.7).
   *  Images use fetchImageObjectUrl instead (raw bytes, must be revoked). */
  fetchFileContent(path: string): Promise<FileContentResponse> {
    return this.getJson<FileContentResponse>(
      `/api/files/content?path=${encodeURIComponent(path)}`,
    );
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

  /** POST /api/report — statistical_results + intent → manuscript sections
   *  (Reporting, §3.5). Calls the existing ReportingAgent unchanged; the format
   *  selection (checklist / journal style / user Skill) rides in the payload.
   *  Failure is never silent: `error_detail` is populated on any failure (§5). */
  report(body: ReportRequest): Promise<ReportResponse> {
    return this.post<ReportResponse>("/api/report", body);
  }

  /** POST /api/workspace/reset — delete the persisted .RData + summary so the
   *  next run starts from an empty workspace (workspace-persistence spec §3). */
  resetWorkspace(): Promise<WorkspaceResetResponse> {
    return this.post<WorkspaceResetResponse>("/api/workspace/reset", {});
  }

  // ── Knowledge Ingestion Pipeline (§3.8/§3.9, ADR-0003) ────────────────────
  // Reference-material entry, kept separate from the 解析データ (patient) path
  // (§5). AI proposes; the human approve() call is the only registration
  // trigger — the frontend never sends approved_by_human (server always True).

  /** POST /api/knowledge/ingest — upload a reference document (pdf/md/txt/docx)
   *  and receive an AI-extracted draft for human review. A PII-contaminated
   *  document is rejected with 422; the resulting ApiError carries
   *  `failedChecks` so the rejection is shown explicitly, never silently (§5). */
  ingestKnowledge(file: File): Promise<KnowledgeIngestResponse> {
    return this.postFile<KnowledgeIngestResponse>("/api/knowledge/ingest", file);
  }

  /** POST /api/knowledge/approve — register a human-approved draft into
   *  institutional/ (ADR-0003). The selected domain/trust_level ride in the
   *  body; corrections is optional (v1 minimal). Returns the new entry_id. */
  approveKnowledge(
    body: KnowledgeApproveRequest,
  ): Promise<KnowledgeApproveResponse> {
    return this.post<KnowledgeApproveResponse>("/api/knowledge/approve", body);
  }

  /** POST /api/knowledge/reject — reject a pending draft (reason required). */
  rejectKnowledge(
    body: KnowledgeRejectRequest,
  ): Promise<KnowledgeRejectResponse> {
    return this.post<KnowledgeRejectResponse>("/api/knowledge/reject", body);
  }

  /** GET /api/knowledge — read-only registry listing (§3.8). No archive
   *  endpoint exists in REST (K-3), so the UI only browses these entries. */
  listKnowledge(): Promise<KnowledgeListResponse> {
    return this.getJson<KnowledgeListResponse>("/api/knowledge");
  }

  /** POST /api/knowledge/reindex — rebuild the local embedding index (§3.9).
   *  Returns {status,chunks}; a 501 (no retriever wired) surfaces as an
   *  ApiError the UI shows as "対応retriever未配線" without over-stating it —
   *  the approval itself already succeeded (K-6). */
  reindexKnowledge(): Promise<KnowledgeReindexResponse> {
    return this.post<KnowledgeReindexResponse>("/api/knowledge/reindex", {});
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

  /** WS /ws/chat — drive one chat turn with streaming (§4, Phase 2). Auth is
   *  the first message (`{token,…}`), like streamConsole.
   *
   * Send a `prompt` for a fresh natural-language turn (the server runs the
   * Planner and routes to `clarify` / `confirm` / streamed `proposal`), or an
   * `intentObject` to skip the Planner and stream the proposal for a
   * confirmed/clarified intent. The server emits `intent`/`clarify`/`confirm`
   * routing frames, then `delta`* + `proposal` (or `error`), then `done`.
   * `onClose` fires exactly once. `conversationId` lets the server keep the
   * running history so the reply reflects the whole dialogue. Returns the
   * socket so the caller can close it early. */
  streamChat(params: {
    conversationId: string;
    prompt?: string;
    intentObject?: Record<string, unknown>;
    onMessage: (event: ChatStreamEvent) => void;
    onError: (message: string) => void;
    onClose: () => void;
  }): WebSocket {
    const ws = new WebSocket(`${this.getWsBaseUrl()}/ws/chat`);
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
          conversation_id: params.conversationId,
          // Omitted-when-absent: the server routes by which one is present.
          intent_object: params.intentObject ?? null,
          prompt: params.prompt ?? "",
        }),
      );
    };
    ws.onmessage = (event) => {
      try {
        params.onMessage(JSON.parse(event.data as string) as ChatStreamEvent);
      } catch {
        // A non-JSON frame should never happen; ignore rather than crash.
      }
    };
    ws.onerror = () => {
      params.onError(`チャット接続に失敗しました (${this.getWsBaseUrl()}/ws/chat)。`);
    };
    ws.onclose = finish;
    return ws;
  }
}

/** Shared singleton used by the app; tests construct their own instances. */
export const apiClient = new CieApiClient();
