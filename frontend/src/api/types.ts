// API envelope types — mirror cie/api/models.py (spec/api/rest-api-contract.md §3–§5).
// Nested domain objects (intent_object, analysis_proposal, …) are free-form on
// the wire (the API is a thin wrapper), so we keep them loosely typed but pin
// down the fields the shell actually renders.

export interface ErrorEnvelope {
  error_code: string;
  message: string;
  detail?: string | null;
}

// POST /api/intent (§3.1)
export interface IntentRequest {
  prompt: string;
  dataset_uploaded?: boolean;
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

// WS /ws/console (§4.1) — sanitized console frames.
export interface ConsoleMessage {
  type: "stdout" | "stderr" | "exit";
  text: string;
  exit_code?: number | null;
}
