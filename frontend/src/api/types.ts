// API envelope types — mirror cie/api/models.py (spec/api/rest-api-contract.md §3–§5).
// Nested domain objects (intent_object, analysis_proposal, …) are free-form on
// the wire (the API is a thin wrapper), so we keep them loosely typed but pin
// down the fields the shell actually renders.

export interface ErrorEnvelope {
  error_code: string;
  message: string;
  detail?: string | null;
  // POST /api/knowledge/ingest returns a 422 whose HTTPException detail carries
  // the PII check names that failed (cie/api/routes/knowledge.py). We surface
  // them so the rejection is explicit, never silent (§5).
  failed_checks?: string[] | null;
}

// POST /api/dataset (rest-api-contract §3.1 前提 / cie/api/routes/dataset.py).
// The response carries aggregate-only column metadata (DQ-001) — never row
// values. Column names are replaced by var_n aliases server-side; the shape
// mirrors build_dataset_context()'s `columns` output verbatim (§5, CLAUDE.md).
export interface DatasetColumn {
  var_n: string;
  // Original column header. Local-UI-only — never forwarded to the LLM (the
  // agents pipeline only ever sees var_n); shown so the user can confirm
  // which real column the AI's var_n reference points to.
  original_name: string;
  inferred_type: string;
  missing_count: number;
  missing_rate_pct: number;
}

export interface DatasetUploadResponse {
  dataset_id: string;
  // Origin label (filename, plus sheet name for Excel). Local-UI-only — shown
  // in the header badge /「解析対象データ」banner so the user always sees which
  // file the analysis runs against; never sent to the LLM pipeline.
  source_name?: string | null;
  registered_at?: string | null;
  row_count: number;
  column_count: number;
  columns: DatasetColumn[];
}

// GET /api/dataset — the currently registered dataset (null until an upload).
// Lets the UI restore the 解析対象データ indicator after a page reload.
export interface DatasetStatusResponse {
  dataset: DatasetUploadResponse | null;
}

// POST /api/dataset/excel/inspect → sheet names of a pending Excel upload;
// POST /api/dataset/excel/confirm registers the chosen sheet and returns the
// same DatasetUploadResponse shape as the CSV path.
export interface ExcelInspectResponse {
  upload_id: string;
  sheet_names: string[];
}

export interface ExcelConfirmRequest {
  upload_id: string;
  sheet_name: string;
}

// POST /api/dataset/from_existing — register a CSV/Excel file already sitting
// in the workspace (as listed by GET /api/files) without re-uploading it.
// The response is either a DatasetUploadResponse (CSV, registered
// immediately) or an ExcelInspectResponse (Excel, awaiting sheet selection —
// completed via the existing POST /api/dataset/excel/confirm).
export interface DatasetFromExistingRequest {
  path: string;
}

// /api/settings/llm — AI provider + API key management (distinct from the
// X-CIE-Token session auth). Never carries a key value in responses.
export interface LlmProviderStatus {
  provider: string;
  label: string;
  has_key: boolean;
}

export interface LlmSettingsResponse {
  active_provider: string;
  providers: LlmProviderStatus[];
}

export interface LlmProviderRequest {
  provider: string;
}

export interface LlmApiKeyRequest {
  provider: string;
  api_key: string;
}

export interface LlmApiKeyClearRequest {
  provider: string;
}

// /api/settings/storage — 保存先ルートの表示・変更。workspace_directory /
// database_filepath are the paths *this running process* actually writes to
// (already wired into every R executor/agent at startup — changing it only
// takes effect on next launch, see cie/api/routes/settings.py).
export interface StorageSettingsResponse {
  workspace_directory: string;
  database_filepath: string;
  pending_workspace_directory?: string | null;
}

export interface StorageDirectoryRequest {
  directory: string;
}

// POST /api/intent (§3.1)
export interface ConversationTurn {
  role: "user" | "assistant";
  text: string;
}

export interface IntentRequest {
  prompt: string;
  dataset_uploaded?: boolean;
  // Recent chat turns (oldest→newest, excluding the current prompt) so the
  // Planner reads a correction in context instead of as an isolated fragment.
  conversation_history?: ConversationTurn[];
}

// One clarification option the Planner offers; clicking applies intent_override.
export interface ClarificationOption {
  option_id?: string;
  label: string;
  intent_override?: Record<string, unknown>;
}

export interface IntentResponse {
  execution_id: string;
  intent_object: Record<string, unknown>;
  confidence_score: number;
  requires_human_clarification: boolean;
  clarification_options: Array<Record<string, unknown>>;
}

// POST /api/propose (§3.2)
export interface ProposeRequest {
  intent_object?: Record<string, unknown> | null;
  continuation_query?: string | null;
  prior_statistical_results?: Record<string, unknown> | null;
  prior_r_script?: string | null;
  // Recent chat turns so the conversational explanation reflects the dialogue.
  conversation_history?: ConversationTurn[];
}

export interface CodeCandidate {
  candidate_id: string;
  label?: string;
  r_code: string;
}

export interface AnalysisProposal {
  explanation_markdown?: string;
  code_candidates?: CodeCandidate[];
  recommended_candidate_id?: string;
}

export interface RScriptProvenance {
  llm_generated?: boolean;
  from_cache?: boolean;
  knowledge_references?: unknown[];
  // Always present when generation failed (§3.2) — the frontend must show it.
  reason?: string;
}

export interface ProposeResponse {
  execution_id: string;
  analysis_proposal: AnalysisProposal | null;
  r_script_provenance: RScriptProvenance;
}

// POST /api/run (§3.3)
export interface RunRequest {
  r_script: string;
  persist_workspace?: boolean;
}

export interface ExecutionResult {
  status?: string;
  exit_code?: number;
  duration_ms?: number;
  sanitized_stdout_summary?: string;
  detail?: string | null;
}

export interface RunResponse {
  execution_id: string;
  execution_result: ExecutionResult;
  statistical_results?: Record<string, unknown> | null;
  statistical_results_reason?: string | null;
  generated_files?: string[];
  workspace_summary?: Record<string, unknown> | null;
  // Always present when the run failed (§3.3, §5) — the frontend must show it.
  error_detail?: string | null;
}

// POST /api/workspace/reset (spec/runtime-workspace-persistence.md §3)
export interface WorkspaceResetResponse {
  removed: string[];
}

// POST /api/visualize (§3.4)
export interface VisualizeRequest {
  statistical_results: Record<string, unknown>;
  intent_object: Record<string, unknown>;
}

export interface Figure {
  title: string;
  path?: string | null;
}

export interface VisualizeResponse {
  execution_id: string;
  figures: Figure[];
  error_detail?: string | null;
}

// POST /api/report (§3.5)
export interface ReportRequest {
  statistical_results: Record<string, unknown>;
  intent_object: Record<string, unknown>;
  reporting_checklist_id?: string | null;
  target_journal_style?: string;
  reporting_skill_id?: string | null;
}

export interface ManuscriptSection {
  section_id: string;
  text: string;
  is_ai_generated: boolean;
}

export interface ReportResponse {
  execution_id: string;
  manuscript_sections: ManuscriptSection[];
  error_detail?: string | null;
}

// GET /api/files (§3.6) — read-only workspace listing (cie/api/models.py).
export interface FileEntry {
  path: string;
  size_bytes: number;
  modified: string;
  // "image" | "text" | "other" (cie/api/routes/files.py _kind).
  kind: string;
}

export interface FilesResponse {
  files: FileEntry[];
}

// GET /api/files/content (§3.7) — text files return {text, language};
// images return raw bytes (fetched via fetchImageObjectUrl instead).
export interface FileContentResponse {
  text: string;
  language: string;
}

// ── Knowledge Ingestion Pipeline (§3.8/§3.9, ADR-0003) ──────────────────────
// Mirrors cie/api/models.py Knowledge*. The reference-material entry is kept
// deliberately separate from the 解析データ (patient) entry (§5, ADR-0005 原則4).

// POST /api/knowledge/ingest — extracted draft metadata (free-form on the wire).
export interface KnowledgeSourceInfo {
  title?: string | null;
  year?: string | number | null;
  doi?: string | null;
  url?: string | null;
  [key: string]: unknown;
}

// One AI-extracted knowledge item awaiting human review. confidence < 0.7 is
// flagged 🟡 in the UI (cie/ui/components/knowledge_review.py threshold).
export interface KnowledgeItem {
  statement?: string;
  direct_quote?: string;
  confidence?: number;
  caveats?: string;
  [key: string]: unknown;
}

export interface KnowledgeExtracted {
  source_info: KnowledgeSourceInfo;
  domain: string;
  trust_level: string;
  knowledge_items: KnowledgeItem[];
}

export interface KnowledgeIngestResponse {
  draft_id: string;
  extracted: KnowledgeExtracted;
  extraction_limitations: string[];
}

// POST /api/knowledge/approve — the human-in-the-loop registration trigger.
// approved_by_human is NEVER sent by the frontend (the server always sets True,
// ADR-0002/0003). corrections is optional; v1 sends only domain/trust_level.
export interface KnowledgeApproveRequest {
  draft_id: string;
  domain: string;
  trust_level: string;
  corrections?: Record<string, unknown>;
}

export interface KnowledgeApproveResponse {
  entry_id: string;
  indexed_docs?: number | null;
  chunks?: number | null;
}

// POST /api/knowledge/reject — reason is required (無言失敗禁止 §5).
export interface KnowledgeRejectRequest {
  draft_id: string;
  reason: string;
}

export interface KnowledgeRejectResponse {
  draft_id: string;
  status: string;
}

// GET /api/knowledge — read-only registry (the REST list returns these 5 fields
// only; no archive endpoint exists, so the UI is view-only — K-3).
export interface KnowledgeListEntry {
  entry_id: string | null;
  domain: string | null;
  status: string | null;
  trust_level: string | null;
  title: string | null;
}

export interface KnowledgeListResponse {
  entries: KnowledgeListEntry[];
}

// POST /api/knowledge/reindex — {status,chunks}; 501 when no retriever is wired.
export interface KnowledgeReindexResponse {
  status: string;
  chunks: number;
}

// WS /ws/console (§4.1) — sanitized console frames.
export interface ConsoleMessage {
  type: "stdout" | "stderr" | "exit";
  text: string;
  exit_code?: number | null;
}
