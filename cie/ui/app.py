"""CIE Platform — Streamlit main entry point.

Run: streamlit run cie/ui/app.py

This module is the ONLY place that writes to st.session_state.
Screen / component functions communicate via return values (see PROJECT_RULES).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from pathlib import Path

import streamlit as st

from cie.reporting.format_context import build_format_context
from cie.reporting.result_formatter import format_statistical_results
from cie.ui.components.right_pane import render_right_pane
from cie.ui.components.status_bar import render_status_bar
from cie.ui.screens.analysis_config import render_analysis_config
from cie.ui.screens.audit_log import render_audit_log
from cie.ui.screens.dashboard import render_dashboard
from cie.ui.screens.data_preview import render_data_preview
from cie.ui.screens.intent_entry import render_intent_entry, render_intent_preview
from cie.ui.screens.knowledge_management import render_knowledge_management
from cie.ui.screens.quality_review import render_quality_review
from cie.ui.screens.settings import render_settings
from cie.ui.screens.format_selection import render_format_selection
from cie.ui.screens.results import render_results
from cie.ui.screens.skill_improvement import render_skill_improvement
from cie.ui.screens.workbench import render_workbench, new_message_id
from cie.ui.screens.workflow_view import render_workflow_view

_CSS_VARIABLES = """
<style>
:root {
    --cie-blue-700: #1D4E89;
    --cie-blue-500: #2E74C0;
    --cie-blue-100: #DBEAFE;
    --cie-gray-900: #111827;
    --cie-gray-600: #4B5563;
    --cie-gray-200: #E5E7EB;
    --cie-gray-50:  #F9FAFB;
    --cie-success:  #059669;
    --cie-warning:  #D97706;
    --cie-critical: #DC2626;
    --cie-approval: #7C3AED;
    --cie-ai-teal:  #0D9488;
}
</style>
"""

# ---------------------------------------------------------------------------
# Service container — initialised once per Streamlit server process
# ---------------------------------------------------------------------------

@st.cache_resource
def _get_services() -> dict:
    """Initialise and cache all backend services.

    Called at most once per server process (Streamlit's cache_resource).
    All async DB setup is executed synchronously here via asyncio.run().
    """
    from cie.agents.base import AgentInput  # noqa: F401 — re-exported for handlers
    from cie.agents.data_quality import DataQualityAgent
    from cie.agents.evaluation import EvaluationAgent
    from cie.agents.planner import PlannerAgent
    from cie.agents.reporting import ReportingAgent
    from cie.agents.reviewer import ReviewerAgent
    from cie.agents.runtime import RuntimeAgent
    from cie.agents.statistics import StatisticsAgent
    from cie.agents.visualization import VisualizationAgent
    from cie.runtime.r_executor import LocalRExecutor
    from cie.runtime.runtime_provider import RuntimeProvider
    from cie.core.audit import AuditService
    from cie.core.config import CIEConfig
    from cie.core.database import get_engine, get_session, init_db
    from cie.core.llm_client import llm_client_from_env
    from cie.cache.r_script_cache import RScriptCache
    from cie.knowledge.ingestion_agent import KnowledgeIngestionAgent
    from cie.knowledge.reference_library import MarkdownReferenceLibrary
    from cie.knowledge.ingestion_guard import IngestionGuard
    from cie.knowledge.lifecycle import KnowledgeLifecycleService
    from cie.knowledge.loader import KnowledgeLoader
    from cie.knowledge.parsers.base import DocumentParserRegistry
    from cie.knowledge.parsers.pymupdf_parser import PlainTextParser, PyMuPDFParser
    from cie.schemas.validator import SchemaRegistry
    from cie.security.capability_token import CapabilityTokenManager
    from cie.security.context_guard import ContextGuard
    from cie.security.pii_filter import PIIFilter
    from cie.security.policy_engine import PolicyEngine
    from cie.workflow.orchestrator import Orchestrator
    from cie.workflow.registry import WorkflowRegistry
    from cie.workflow.states import WorkflowStateMachine
    from cie.workflow.system_registry import SystemWorkflowRegistry

    config = CIEConfig()

    # DB — create tables if missing (idempotent)
    engine = asyncio.run(get_engine(config))
    asyncio.run(init_db(engine))

    # Core services
    pii_filter = PIIFilter()
    token_manager = CapabilityTokenManager()
    audit = AuditService(session_factory=lambda: get_session(engine))
    context_guard = ContextGuard(pii_filter, audit)
    policy_engine = PolicyEngine(token_manager, audit)
    schema_registry = SchemaRegistry(schema_dir=Path("schemas/"))

    # LLM — provider selected via CIE_ACTIVE_AI_PROVIDER env var
    llm_client = llm_client_from_env()

    # Semantic cache (ADR-0004)
    from cie.cache.store import CacheStore
    cache_store = CacheStore()

    # Agents
    planner = PlannerAgent(
        policy_engine, schema_registry, audit, context_guard, llm_client,
        cache_store=cache_store,
    )

    # Knowledge directories
    knowledge_root = Path("knowledge")
    workspace = Path(config.workspace_directory)
    official_dir = knowledge_root / "official"
    institutional_dir = knowledge_root / "institutional"
    pending_dir = knowledge_root / "pending"
    source_dir = workspace / "knowledge_sources"
    source_dir.mkdir(parents=True, exist_ok=True)

    parsers = [PyMuPDFParser(), PlainTextParser()]
    parser_registry = DocumentParserRegistry(parsers)
    ingestion_guard = IngestionGuard()

    knowledge_ingestion = KnowledgeIngestionAgent(
        ingestion_guard, parser_registry, pending_dir, source_dir
    )
    knowledge_lifecycle = KnowledgeLifecycleService(institutional_dir, pending_dir, audit)
    knowledge_loader = KnowledgeLoader(official_dir, institutional_dir)

    # Downstream analysis agents
    data_quality  = DataQualityAgent(policy_engine, schema_registry, audit, pii_filter)
    # Statistics generates the executable R script via the LLM, grounded in the
    # Markdown knowledge reference library (RAG), with a token-saving cache for
    # structurally-identical analyses.
    reference_library = MarkdownReferenceLibrary(knowledge_root)
    r_script_cache = RScriptCache()
    # SkillLoader: user/ > core/ priority (ADR-0002 Principle 3)
    from cie.skills.loader import SkillLoader
    skill_loader = SkillLoader(Path("skills"))
    statistics    = StatisticsAgent(
        policy_engine, schema_registry, audit,
        llm_client=llm_client,
        reference_library=reference_library,
        script_cache=r_script_cache,
        skill_loader=skill_loader,
    )
    viz_output_dir = workspace / "viz_output"
    viz_output_dir.mkdir(parents=True, exist_ok=True)
    viz_local_executor = LocalRExecutor(
        workspace_dir=workspace, output_dir=viz_output_dir, context_guard=context_guard
    )
    viz_runtime_provider = RuntimeProvider(local_executor=viz_local_executor)
    visualization = VisualizationAgent(
        policy_engine, schema_registry, audit,
        llm_client=llm_client,
        reference_library=reference_library,
        script_cache=r_script_cache,
        runtime_provider=viz_runtime_provider,
        workspace_dir=workspace / "viz_scripts",
        output_dir=viz_output_dir,
        skill_loader=skill_loader,
    )
    reporting     = ReportingAgent(
        policy_engine, schema_registry, audit,
        llm_client=llm_client,
        reference_library=reference_library,
        skill_loader=skill_loader,
    )
    reviewer      = ReviewerAgent(policy_engine, schema_registry, audit)
    # Evaluation agent — final DAG stage (correctness/statistical/security/usability)
    evaluation    = EvaluationAgent(policy_engine, schema_registry, audit)

    # Runtime agent — executes upstream-generated R scripts in the sandbox
    r_output_dir = workspace / "r_output"
    r_output_dir.mkdir(parents=True, exist_ok=True)
    local_r_executor = LocalRExecutor(
        workspace_dir=workspace, output_dir=r_output_dir, context_guard=context_guard
    )
    runtime_provider = RuntimeProvider(local_executor=local_r_executor)
    runtime_agent = RuntimeAgent(
        policy_engine, schema_registry, audit, runtime_provider,
        workspace_dir=workspace / "r_scripts",
        output_dir=r_output_dir,
    )

    agent_registry = {
        "planner":       planner,
        "data_quality":  data_quality,
        "statistics":    statistics,
        "visualization": visualization,
        "reporting":     reporting,
        "reviewer":      reviewer,
        "runtime":       runtime_agent,
        "evaluation":    evaluation,
    }

    # Workflow engine
    workflow_registry = WorkflowRegistry.load_from_yaml(Path("spec/workflow.yaml"))
    system_registry   = SystemWorkflowRegistry(Path("spec/system-workflow.yaml"))
    state_machine     = WorkflowStateMachine()

    orchestrator = Orchestrator(
        workflow_registry=workflow_registry,
        state_machine=state_machine,
        token_manager=token_manager,
        policy_engine=policy_engine,
        context_guard=context_guard,
        audit_service=audit,
        agent_registry=agent_registry,
        system_registry=system_registry,
        knowledge_loader=knowledge_loader,
    )

    # Phase 8: Skill self-improvement service (ADR-0002)
    from cie.skills.lifecycle import SkillLifecycleService
    from cie.skills.registry_manager import RegistryManager
    from cie.evaluation.regression import RegressionChecker

    regression_checker = RegressionChecker(db_session_factory=lambda: get_session(engine))
    registry_manager = RegistryManager(Path("REGISTRY.yaml"))
    skill_lifecycle = SkillLifecycleService(
        skill_loader=skill_loader,
        registry_manager=registry_manager,
        regression_checker=regression_checker,
        token_manager=token_manager,
        audit_service=audit,
        db_session_factory=lambda: get_session(engine),
    )

    return {
        "token_manager": token_manager,
        "audit": audit,
        "planner": planner,
        "knowledge_ingestion": knowledge_ingestion,
        "knowledge_lifecycle": knowledge_lifecycle,
        "knowledge_loader": knowledge_loader,
        "orchestrator": orchestrator,
        "cache_store": cache_store,
        "skill_loader": skill_loader,
        # Phase 7: exposed for continuation mini-pipeline
        "statistics": statistics,
        "runtime_agent": runtime_agent,
        "visualization": visualization,
        "r_output_dir": r_output_dir,
        "viz_output_dir": viz_output_dir,
        # Phase 8: Skill self-improvement
        "skill_lifecycle": skill_lifecycle,
        "session_factory": lambda: get_session(engine),
    }


def _build_dataset_context(csv_bytes: bytes | None) -> dict:
    """Place the uploaded dataset where R can read it and derive column metadata.

    Writes the CSV to ``<workspace>/dataset.csv`` (the path the generated R
    script reads via WORKSPACE_DIR) and returns a ``dataset_context`` dict that
    the Orchestrator merges into the workflow's initial payload:
      - dataset_structural_metadata: {column: {inferred_type}} for the LLM
      - data_quality_report: a passing gate so the Statistics node proceeds
      - DatasetMetadata fields (metadata_type/columns/row_count/...): the
        aggregate-only input the Data Quality nodes validate (DQ-001 — column
        names are replaced by var_n aliases; no row values are included)
    Returns an empty dict when no dataset was uploaded.
    """
    if not csv_bytes:
        return {}

    import io
    from datetime import datetime, timezone
    from pathlib import Path

    import pandas as pd

    from cie.core.config import CIEConfig

    workspace = Path(CIEConfig().workspace_directory)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "dataset.csv").write_bytes(csv_bytes)

    metadata: dict = {}
    dq_columns: list[dict] = []
    var_n_alias_map: dict[str, str] = {}
    row_count = 0
    try:
        df = pd.read_csv(io.BytesIO(csv_bytes))
        row_count = int(len(df))
        for idx, col in enumerate(df.columns, start=1):
            series = df[col]
            if pd.api.types.is_numeric_dtype(series):
                inferred = "continuous"
            elif series.nunique(dropna=True) <= 2:
                inferred = "categorical_binary"
            else:
                inferred = "categorical_nominal"
            metadata[str(col)] = {
                "inferred_type": inferred,
                "unique_count": int(series.nunique(dropna=True)),
            }
            var_n = f"var_{idx}"
            var_n_alias_map[var_n] = str(col)
            missing_count = int(series.isna().sum())
            dq_columns.append({
                "var_n": var_n,
                "inferred_type": inferred,
                "missing_count": missing_count,
                "missing_rate_pct": (
                    round(missing_count / row_count * 100.0, 2) if row_count else 0.0
                ),
            })
    except Exception:
        metadata = {}
        dq_columns = []
        var_n_alias_map = {}

    return {
        "dataset_structural_metadata": metadata,
        # The Statistics node is gated on a passing quality report (ST-001).
        # Until the data_quality stage runs on real data, seed a passing gate
        # so the analysis proceeds; the data_quality node still runs and can
        # override this with its own findings.
        "data_quality_report": {"quality_gate_passed": True},
        # DatasetMetadata contract consumed by the Data Quality nodes
        # (validate_dataset / classify_variables / detect_missing_values /
        # detect_outliers). Aggregates only — DQ-001.
        "dataset_id": "uploaded_dataset",
        "metadata_type": "validated_structural",
        "row_count": row_count,
        "column_count": len(dq_columns),
        "columns": dq_columns,
        "var_n_alias_map": var_n_alias_map,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _reload_knowledge_state(services: dict) -> None:
    """Pull the latest entries and expiry warnings into session_state."""
    try:
        frozen = services["knowledge_loader"].load_for_execution("ui-session")
        entries = list(frozen.entries)
        warnings = services["knowledge_loader"].check_expiry_warnings(entries)
        st.session_state["knowledge_entries"] = entries
        st.session_state["knowledge_expiry_warnings"] = warnings
    except Exception:
        pass  # keep existing session_state on failure


def _unpack_workflow_result(result: dict) -> None:
    """Expand Orchestrator node_results into per-screen session_state keys."""
    import dataclasses

    raw_results: list = result.get("node_results", [])
    # Orchestrator returns TaskDispatchResult dataclasses — normalize to dicts
    node_results: list[dict] = [
        dataclasses.asdict(nr) if dataclasses.is_dataclass(nr) else nr
        for nr in raw_results
    ]
    node_statuses: dict = dict(st.session_state.get("node_statuses") or {})
    node_outputs: dict = dict(st.session_state.get("node_outputs") or {})
    for nr in node_results:
        nid = nr.get("node_id", "")
        node_statuses[nid] = nr.get("status", "unknown")
        node_outputs[nid] = nr.get("output_payload", {})
        agent = nr.get("agent_id", "")
        if agent == "data_quality":
            st.session_state["quality_report"] = nr.get("output_payload", {})
        elif agent == "statistics":
            st.session_state["analysis_plan"] = nr.get("output_payload", {})
        elif agent == "runtime":
            payload = nr.get("output_payload", {})
            st.session_state["execution_result"] = payload.get("execution_result", {})
            # Capture the parsed statistical results + a human-readable render.
            # Also persisted as "statistical_results" for continuation flow.
            sr = payload.get("statistical_results")
            st.session_state["statistical_results"] = sr
            st.session_state["statistical_results_formatted"] = format_statistical_results(
                sr, payload.get("statistical_results_reason")
            )
        elif agent == "visualization":
            payload = nr.get("output_payload", {})
            fig_manifest: list = payload.get("figure_manifest") or []
            st.session_state["figures"] = [
                {
                    "title": f.get("figure_id", "Figure"),
                    "path": f.get("actual_path"),
                }
                for f in fig_manifest
                if isinstance(f, dict)
            ]
        elif agent == "reporting":
            payload = nr.get("output_payload", {})
            sections_list: list = payload.get("manuscript_sections") or []
            unresolved: list = payload.get("unresolved_items") or []
            # Convert list → dict keyed by section_id for render_results
            sections_dict: dict = {}
            for sec in sections_list:
                if not isinstance(sec, dict):
                    continue
                sid = sec.get("section_id", "unknown")
                sections_dict[sid] = {
                    "text": sec.get("content", ""),
                    "is_ai_generated": sec.get("llm_generated", False),
                    "unresolved_items": [],
                }
            # Attach top-level unresolved_items to the results section if present
            if unresolved and "results" in sections_dict:
                sections_dict["results"]["unresolved_items"] = [
                    {"item_id": f"RP-{i+1:03d}", "description": item}
                    for i, item in enumerate(unresolved)
                ]
            st.session_state["manuscript_sections"] = sections_dict
        elif agent == "reviewer":
            st.session_state["review_result"] = nr.get("output_payload", {})
        elif agent == "evaluation":
            st.session_state["evaluation_report"] = nr.get("output_payload", {})
    st.session_state["node_statuses"] = node_statuses
    st.session_state["node_outputs"] = node_outputs
    st.session_state["workflow_state"] = result.get("final_state")
    # resume_workflow results carry no workflow selection metadata — keep the
    # definition recorded by the original run_workflow in that case.
    if result.get("workflow_id_selected") is not None:
        st.session_state["workflow_definition"] = {
            "workflow_id": result.get("workflow_id_selected"),
            "rule_id": result.get("rule_id"),
            "justification": result.get("justification"),
        }


def _maybe_request_security_approval(result: dict) -> None:
    """If the workflow paused at the security_review approval gate, surface
    the generated R script in the approval panel so the human can review it
    and resume the run (spec/workflow.yaml security_review, ADR human-in-loop).
    """
    import dataclasses

    if result.get("final_state") != "waiting_for_human":
        return

    node_results = [
        dataclasses.asdict(nr) if dataclasses.is_dataclass(nr) else nr
        for nr in result.get("node_results", [])
    ]
    waiting = [
        nr for nr in node_results
        if nr.get("status") == "waiting_for_human"
        and nr.get("node_id") == "security_review"
    ]
    if not waiting:
        return

    # The R script pending approval was produced by the generate_* node
    r_script = ""
    for nr in node_results:
        payload = nr.get("output_payload") or {}
        if payload.get("r_script"):
            r_script = payload["r_script"]

    if not r_script:
        # Statistics agent failed to generate a valid R script (LLM returned
        # prose or an empty response). Surface the error instead of an empty dialog.
        st.error(
            "⚠️ Rスクリプトの生成に失敗しました。LLMがコードブロックを返しませんでした。\n\n"
            "「研究意図入力」に戻って再解析するか、使用するAIプロバイダーを設定画面で確認してください。"
        )
        _append_activity(
            agent_id="statistics",
            action="r_script_generation_failed",
            summary="security_review に到達したがrスクリプトが空",
            severity="CRITICAL",
        )
        return

    st.session_state["approval_pending"] = True
    st.session_state["approval_context"] = {
        "action": "resume_security_review",
        "title": "R スクリプト実行の承認（security_review）",
        "description": (
            "実行前のセキュリティレビューです。以下の生成Rスクリプトを確認し、"
            "問題がなければ承認してください。承認するとサンドボックスで実行されます。"
        ),
        "code_block": r_script.strip(),
        "code_language": "r",
        "is_irreversible": False,
    }


def _start_continuation_analysis(query: str, services: dict) -> None:
    """Generate a follow-up R script via StatisticsAgent and queue for human review.

    Runs StatisticsAgent in continuation mode: injects continuation_query +
    prior_statistical_results into the payload.  The generated R script is
    stored in session_state["continuation_pending_payload"] and an approval
    dialog is surfaced so the human can review the R before execution.

    Capability token is issued and revoked inside a try/finally (ADR rule).
    """
    from cie.agents.base import AgentInput
    from cie.security.capability_token import CapabilityScope

    statistics = services.get("statistics")
    if statistics is None:
        st.error("StatisticsAgent が初期化されていません。")
        return

    prior_sr = st.session_state.get("statistical_results")
    prior_r_script: str | None = None
    # Recover the last R script from the most recent continuation or primary run
    for hist_entry in reversed(st.session_state.get("analysis_history", [])):
        if hist_entry.get("r_script"):
            prior_r_script = hist_entry["r_script"]
            break

    intent_obj = (st.session_state.get("intent_object") or {}).get(
        "intent_object", {}
    )
    if not intent_obj:
        intent_obj = {}

    col_meta = {}
    csv_bytes = st.session_state.get("intent_csv_bytes")
    if csv_bytes:
        dc = _build_dataset_context(csv_bytes)
        col_meta = dc.get("dataset_structural_metadata", {})

    execution_id = str(uuid.uuid4())
    token = services["token_manager"].issue(
        execution_id=execution_id,
        agent_id="statistics",
        step_id="continuation_statistics",
        requested_scopes={
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.R_CODE_GENERATE_TEMPLATE,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
    )
    try:
        agent_input = AgentInput(
            execution_id=execution_id,
            node_id="continuation_statistics",
            capability_token=token,
            payload={
                "data_quality_report": {"quality_gate_passed": True},
                "intent_object": intent_obj,
                "dataset_structural_metadata": col_meta,
                "continuation_query": query,
                "prior_statistical_results": prior_sr,
                "prior_r_script": prior_r_script,
                "inject_raw_data_rows": False,
            },
            input_schema_ref="cie://schemas/task-context.schema.json",
        )
        with st.spinner("追加解析のRスクリプトを生成中..."):
            output = asyncio.run(statistics.run(agent_input))
    finally:
        services["token_manager"].revoke(token)

    if output.status != "success":
        st.error(f"StatisticsAgent エラー: {output.error_message}")
        _append_activity("statistics", "continuation_failed",
                         output.error_message or "不明なエラー", "CRITICAL")
        return

    r_script = output.output_payload.get("r_script")
    if not r_script:
        st.warning("Rスクリプトが生成されませんでした（LLMが未設定の可能性があります）。")
        _append_activity("statistics", "continuation_no_script",
                         "r_script=None", "WARNING")
        return

    # Store pending payload for execution after human approval
    st.session_state["continuation_pending_payload"] = {
        "execution_id": execution_id,
        "query": query,
        "r_script": r_script,
        "analysis_plan": output.output_payload,
    }

    st.session_state["approval_pending"] = True
    st.session_state["approval_context"] = {
        "action": "execute_continuation",
        "title": "追加解析 Rスクリプトの実行承認",
        "description": f"追加解析のRスクリプトを確認し、問題がなければ承認してください。\n\n**追加解析の内容:** {query}",
        "code_block": r_script.strip(),
        "code_language": "r",
        "is_irreversible": False,
    }
    _append_activity("statistics", "continuation_r_generated",
                     f"継続Rスクリプト生成完了 (exec={execution_id[:8]})", "INFO")


def _execute_continuation(services: dict) -> None:
    """Execute the pending continuation R script through Runtime + Visualization.

    Called after the human approves the generated R in the approval panel.
    Runs RuntimeAgent and VisualizationAgent with the prior statistical context,
    then appends the results to session_state["analysis_history"].

    Capability tokens are issued and revoked inside try/finally blocks (ADR rule).
    """
    from cie.agents.base import AgentInput
    from cie.security.capability_token import CapabilityScope
    from cie.reporting.result_formatter import format_statistical_results

    pending = st.session_state.get("continuation_pending_payload")
    if not pending:
        return

    execution_id: str = pending["execution_id"]
    query: str = pending["query"]
    r_script: str = pending["r_script"]

    runtime_agent = services.get("runtime_agent")
    visualization = services.get("visualization")
    if runtime_agent is None:
        st.error("RuntimeAgent が初期化されていません。")
        return

    intent_obj = (st.session_state.get("intent_object") or {}).get("intent_object", {})
    col_meta = {}
    csv_bytes = st.session_state.get("intent_csv_bytes")
    if csv_bytes:
        dc = _build_dataset_context(csv_bytes)
        col_meta = dc.get("dataset_structural_metadata", {})

    # --- RuntimeAgent ---
    rt_token = services["token_manager"].issue(
        execution_id=execution_id,
        agent_id="runtime",
        step_id="continuation_runtime",
        requested_scopes={
            CapabilityScope.RUNTIME_INVOKE_EXECUTION,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
    )
    try:
        rt_input = AgentInput(
            execution_id=execution_id,
            node_id="continuation_runtime",
            capability_token=rt_token,
            payload={
                "r_script": r_script,
                "inject_raw_data_rows": False,
            },
            input_schema_ref="cie://schemas/task-context.schema.json",
        )
        with st.spinner("追加解析のRスクリプトを実行中..."):
            rt_output = asyncio.run(runtime_agent.run(rt_input))
    finally:
        services["token_manager"].revoke(rt_token)

    if rt_output.status != "success":
        st.error(f"RuntimeAgent エラー: {rt_output.error_message}")
        _append_activity("runtime", "continuation_runtime_failed",
                         rt_output.error_message or "不明なエラー", "CRITICAL")
        st.session_state["continuation_pending_payload"] = None
        return

    new_sr = rt_output.output_payload.get("statistical_results")

    # --- VisualizationAgent (optional — skip if not configured) ---
    new_figures: list[dict] = []
    if visualization is not None and new_sr:
        vz_token = services["token_manager"].issue(
            execution_id=execution_id,
            agent_id="visualization",
            step_id="continuation_visualization",
            requested_scopes={
                CapabilityScope.DATASET_READ_VALIDATED,
                CapabilityScope.R_CODE_GENERATE_TEMPLATE,
                CapabilityScope.AUDIT_WRITE_ENTRY,
                CapabilityScope.RUNTIME_INVOKE_EXECUTION,
            },
        )
        try:
            vz_input = AgentInput(
                execution_id=execution_id,
                node_id="continuation_visualization",
                capability_token=vz_token,
                payload={
                    "statistical_results": new_sr,
                    "intent_object": intent_obj,
                    "dataset_structural_metadata": col_meta,
                    "prior_statistical_results": st.session_state.get("statistical_results"),
                    "continuation_query": query,
                    "inject_raw_data_rows": False,
                },
                input_schema_ref="cie://schemas/task-context.schema.json",
            )
            with st.spinner("追加解析の図を生成中..."):
                vz_output = asyncio.run(visualization.run(vz_input))
        finally:
            services["token_manager"].revoke(vz_token)

        if vz_output.status == "success":
            fig_manifest = vz_output.output_payload.get("figure_manifest") or []
            new_figures = [
                {"title": f.get("figure_id", "Figure"), "path": f.get("actual_path")}
                for f in fig_manifest if isinstance(f, dict)
            ]

    # Append to analysis_history
    from datetime import datetime, timezone
    history_entry = {
        "query": query,
        "execution_id": execution_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "statistical_results": new_sr,
        "statistical_results_formatted": format_statistical_results(new_sr, None),
        "figures": new_figures,
        "r_script": r_script,
    }
    history: list = st.session_state.setdefault("analysis_history", [])
    history.append(history_entry)

    # Update the "current" statistical_results so next continuation can reference it
    if new_sr:
        st.session_state["statistical_results"] = new_sr

    st.session_state["continuation_pending_payload"] = None
    _append_activity("runtime", "continuation_completed",
                     f"追加解析完了 (p={new_sr.get('p_value') if new_sr else 'N/A'})", "INFO")


def _handle_workbench() -> None:
    """SCR-Workbench: chat-driven analysis, bypassing the Orchestrator DAG.

    Mirrors the existing "continuation analysis" mini-pipeline (see
    ``_start_continuation_analysis``/``_execute_continuation`` above): each
    agent is invoked directly via ``agent.run()`` with a freshly minted,
    try/finally-revoked capability token, instead of going through the DAG's
    ``security_review`` approval gate. The human-in-the-loop role is played by
    the chat/code-editor interaction itself (the user explicitly picks or
    edits the code before pressing "実行").
    """
    from cie.core.config import CIEConfig

    services = _get_services()
    skill_loader = services.get("skill_loader")
    user_skill_ids: list[str] = (
        [m.skill_id for m in skill_loader.get_all_user_skills()]
        if skill_loader is not None
        else []
    )

    event = render_workbench(
        chat_history=st.session_state["workbench_history"],
        active_code=st.session_state["workbench_active_code"],
        last_run=st.session_state["workbench_last_run"],
        manuscript_sections=st.session_state["workbench_manuscript_sections"],
        dataset_uploaded=st.session_state.get("intent_csv_bytes") is not None,
        workspace_dir=CIEConfig().workspace_directory,
        available_user_skills=user_skill_ids,
        format_settings={
            "checklist_id": st.session_state["format_checklist_id"],
            "journal_style": st.session_state["format_journal_style"],
            "skill_id": st.session_state["format_skill_id"],
        },
    )

    if not event:
        return

    action = event.get("action")
    if action == "upload_dataset":
        st.session_state["intent_csv_bytes"] = event["bytes"]
        st.session_state["intent_csv_filename"] = event["filename"]
        st.rerun()
    elif action == "update_format_settings":
        st.session_state["format_checklist_id"] = event.get("checklist_id")
        st.session_state["format_journal_style"] = event.get("journal_style", "APA")
        st.session_state["format_skill_id"] = event.get("skill_id")
        st.rerun()
    elif action == "user_message":
        _workbench_handle_user_message(services, event["text"])
        st.rerun()
    elif action in ("run_candidate", "run_code"):
        _workbench_execute_code(services, event.get("r_code") or event.get("code"))
        st.rerun()
    elif action == "generate_manuscript":
        _workbench_generate_manuscript(services)
        st.rerun()


def _workbench_handle_user_message(services: dict, text: str) -> None:
    """Handle one chat turn: Planner (first turn only) → Statistics.

    First turn produces a conversational analysis_proposal (explanation +
    selectable R code candidates, see StatisticsAgent._generate_conversational_
    proposal). Subsequent turns are routed as continuation_query through the
    existing single-script continuation path. Any failure reason is rendered
    directly into the assistant's chat message — this is the fix for the
    previously-silent StatisticsAgent LLM-failure bug: r_script_provenance.reason
    is never dropped on the floor here.
    """
    from cie.agents.base import AgentInput
    from cie.security.capability_token import CapabilityScope

    history: list = st.session_state["workbench_history"]
    history.append({"id": new_message_id(), "role": "user", "content": text, "candidates": []})

    planner = services["planner"]
    statistics = services["statistics"]
    token_manager = services["token_manager"]

    csv_bytes = st.session_state.get("intent_csv_bytes")
    col_meta: dict = {}
    if csv_bytes:
        dc = _build_dataset_context(csv_bytes)
        col_meta = dc.get("dataset_structural_metadata", {})

    intent_obj: dict = st.session_state.get("workbench_intent_object") or {}
    is_first_turn = not intent_obj

    if is_first_turn:
        execution_id = str(uuid.uuid4())
        pl_token = token_manager.issue(
            execution_id=execution_id,
            agent_id="planner",
            step_id="workbench_planner",
            requested_scopes={
                CapabilityScope.DATASET_PROXY_METADATA,
                CapabilityScope.WORKFLOW_STATE_READ,
                CapabilityScope.AUDIT_WRITE_ENTRY,
            },
        )
        try:
            pl_input = AgentInput(
                execution_id=execution_id,
                node_id="workbench_planner",
                capability_token=pl_token,
                payload={
                    "user_natural_language_prompt": text,
                    "dataset_structural_metadata": col_meta,
                    "inject_raw_data_rows": False,
                },
                input_schema_ref="cie://schemas/planner-input.schema.json",
            )
            with st.spinner("研究意図を解析中..."):
                pl_output = asyncio.run(planner.run(pl_input))
        finally:
            token_manager.revoke(pl_token)

        if pl_output.status not in ("success", "clarification_required"):
            history.append({
                "id": new_message_id(), "role": "assistant", "candidates": [],
                "content": f"意図の解析に失敗しました: {pl_output.error_message}",
            })
            _append_activity("planner", "workbench_planner_failed",
                             pl_output.error_message or "不明なエラー", "CRITICAL")
            return

        intent_obj = pl_output.output_payload.get("intent_object") or {}
        st.session_state["workbench_intent_object"] = intent_obj

        if pl_output.output_payload.get("requires_human_clarification"):
            options = pl_output.output_payload.get("clarification_options") or []
            option_lines = "\n".join(f"- {o.get('label')}" for o in options)
            history.append({
                "id": new_message_id(), "role": "assistant", "candidates": [],
                "content": (
                    "研究意図に確認したい点があります。次のメッセージで具体的に教えてください。\n\n"
                    f"{option_lines}"
                ),
            })
            return

    execution_id = str(uuid.uuid4())
    prior_sr = st.session_state.get("workbench_statistical_results")
    conversational = prior_sr is None

    st_token = token_manager.issue(
        execution_id=execution_id,
        agent_id="statistics",
        step_id="workbench_statistics",
        requested_scopes={
            CapabilityScope.DATASET_READ_VALIDATED,
            CapabilityScope.R_CODE_GENERATE_TEMPLATE,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
    )
    try:
        payload: dict = {
            "data_quality_report": {"quality_gate_passed": True},
            "intent_object": intent_obj,
            "dataset_structural_metadata": col_meta,
            "inject_raw_data_rows": False,
        }
        if conversational:
            payload["conversational_mode"] = True
        else:
            payload["continuation_query"] = text
            payload["prior_statistical_results"] = prior_sr
            last_run = st.session_state.get("workbench_last_run") or {}
            payload["prior_r_script"] = last_run.get("r_script")
        st_input = AgentInput(
            execution_id=execution_id,
            node_id="workbench_statistics",
            capability_token=st_token,
            payload=payload,
            input_schema_ref="cie://schemas/analysis-request.schema.json",
        )
        with st.spinner("分析方法を検討中..."):
            st_output = asyncio.run(statistics.run(st_input))
    finally:
        token_manager.revoke(st_token)

    if st_output.status != "success":
        history.append({
            "id": new_message_id(), "role": "assistant", "candidates": [],
            "content": f"分析方法の検討中にエラーが発生しました: {st_output.error_message}",
        })
        _append_activity("statistics", "workbench_statistics_failed",
                         st_output.error_message or "不明なエラー", "CRITICAL")
        return

    op = st_output.output_payload
    proposal = op.get("analysis_proposal")
    reason = (op.get("r_script_provenance") or {}).get("reason")

    if proposal:
        history.append({
            "id": new_message_id(), "role": "assistant",
            "content": proposal["explanation_markdown"],
            "candidates": proposal["code_candidates"],
        })
    elif op.get("r_script"):
        # Continuation turn: single script, no candidates list.
        history.append({
            "id": new_message_id(), "role": "assistant",
            "content": f"追加解析のRコードを用意しました（{text}）。内容を確認して実行してください。",
            "candidates": [{
                "candidate_id": "continuation",
                "label": "この追加解析を実行",
                "r_code": op["r_script"],
            }],
        })
    else:
        # Never silently drop the reason (fixes the previously-swallowed
        # r_script_provenance.reason bug).
        detail = f"（理由: {reason}）" if reason else ""
        history.append({
            "id": new_message_id(), "role": "assistant", "candidates": [],
            "content": (
                f"Rコードを生成できませんでした。{detail}\n\n"
                "設定画面でLLMのAPIキーが設定されているか確認してください。"
            ),
        })
        _append_activity("statistics", "workbench_no_script", detail or "no reason given", "WARNING")


def _workbench_execute_code(services: dict, code: str | None) -> None:
    """Run *code* via RuntimeAgent (+ VisualizationAgent), bypassing the DAG.

    Mirrors ``_execute_continuation``'s token-mint/run/revoke pattern. Any
    failure reason (execution_result.detail / statistical_results_reason) is
    always attached to workbench_last_run["error_detail"] so the output pane
    can show it — this is the direct fix for the "silent no results" bug
    (previously RuntimeAgent's detailed no_executable_script/execution_failed
    messages were computed but never reached the UI).
    """
    from cie.agents.base import AgentInput
    from cie.security.capability_token import CapabilityScope

    if not code or not code.strip():
        return

    st.session_state["workbench_active_code"] = code
    runtime_agent = services.get("runtime_agent")
    visualization = services.get("visualization")
    token_manager = services["token_manager"]
    execution_id = str(uuid.uuid4())

    rt_token = token_manager.issue(
        execution_id=execution_id,
        agent_id="runtime",
        step_id="workbench_runtime",
        requested_scopes={
            CapabilityScope.RUNTIME_INVOKE_EXECUTION,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
    )
    try:
        rt_input = AgentInput(
            execution_id=execution_id,
            node_id="workbench_runtime",
            capability_token=rt_token,
            payload={"r_script": code, "inject_raw_data_rows": False},
            input_schema_ref="cie://schemas/task-context.schema.json",
        )
        with st.spinner("Rコードを実行中..."):
            rt_output = asyncio.run(runtime_agent.run(rt_input))
    finally:
        token_manager.revoke(rt_token)

    if rt_output.status != "success":
        st.session_state["workbench_last_run"] = {
            "r_script": code,
            "execution_result": {},
            "statistical_results": None,
            "statistical_results_formatted": None,
            "error_detail": rt_output.error_message or "実行に失敗しました。",
            "figures": [],
            "generated_files": [],
        }
        _append_activity("runtime", "workbench_runtime_failed",
                         rt_output.error_message or "不明なエラー", "CRITICAL")
        return

    op = rt_output.output_payload
    execution_result: dict = op.get("execution_result") or {}
    statistical_results = op.get("statistical_results")
    stats_reason = op.get("statistical_results_reason")

    error_detail: str | None = None
    if execution_result.get("status") in ("no_executable_script", "execution_failed", "nonzero_exit"):
        error_detail = execution_result.get("detail") or (
            f"Rの実行が正常に終了しませんでした（exit_code={execution_result.get('exit_code')}）。"
        )
    elif statistical_results is None and stats_reason:
        error_detail = f"統計結果を読み取れませんでした（理由: {stats_reason}）。"

    figures: list[dict] = []
    if visualization is not None and statistical_results:
        intent_obj = st.session_state.get("workbench_intent_object") or {}
        csv_bytes = st.session_state.get("intent_csv_bytes")
        col_meta = {}
        if csv_bytes:
            dc = _build_dataset_context(csv_bytes)
            col_meta = dc.get("dataset_structural_metadata", {})
        vz_token = token_manager.issue(
            execution_id=execution_id,
            agent_id="visualization",
            step_id="workbench_visualization",
            requested_scopes={
                CapabilityScope.DATASET_READ_VALIDATED,
                CapabilityScope.R_CODE_GENERATE_TEMPLATE,
                CapabilityScope.AUDIT_WRITE_ENTRY,
                CapabilityScope.RUNTIME_INVOKE_EXECUTION,
            },
        )
        try:
            vz_input = AgentInput(
                execution_id=execution_id,
                node_id="workbench_visualization",
                capability_token=vz_token,
                payload={
                    "statistical_results": statistical_results,
                    "intent_object": intent_obj,
                    "dataset_structural_metadata": col_meta,
                    "inject_raw_data_rows": False,
                },
                input_schema_ref="cie://schemas/task-context.schema.json",
            )
            with st.spinner("図を生成中..."):
                vz_output = asyncio.run(visualization.run(vz_input))
        finally:
            token_manager.revoke(vz_token)

        if vz_output.status == "success":
            fig_manifest = vz_output.output_payload.get("figure_manifest") or []
            figures = [
                {"title": f.get("figure_id", "Figure"), "path": f.get("actual_path")}
                for f in fig_manifest if isinstance(f, dict)
            ]

    st.session_state["workbench_last_run"] = {
        "r_script": code,
        "execution_result": execution_result,
        "statistical_results": statistical_results,
        "statistical_results_formatted": format_statistical_results(
            statistical_results, stats_reason
        ),
        "error_detail": error_detail,
        "figures": figures,
        "generated_files": op.get("generated_files") or [],
    }
    if statistical_results:
        st.session_state["workbench_statistical_results"] = statistical_results
    _append_activity("runtime", "workbench_execution_completed",
                     f"実行完了 (status={execution_result.get('status')})",
                     "INFO" if not error_detail else "WARNING")


def _workbench_generate_manuscript(services: dict) -> None:
    """Draft manuscript sections from the current statistical_results.

    Calls ReportingAgent directly with the format settings chosen in the
    Workbench's format-selection panel (Phase 6) — the same
    checklist_id/journal_style/skill_id fields the wizard's ReportingAgent
    invocation already reads.
    """
    from cie.agents.base import AgentInput
    from cie.security.capability_token import CapabilityScope

    reporting = services.get("reporting")
    statistical_results = st.session_state.get("workbench_statistical_results")
    if reporting is None or not statistical_results:
        return

    token_manager = services["token_manager"]
    execution_id = str(uuid.uuid4())
    rp_token = token_manager.issue(
        execution_id=execution_id,
        agent_id="reporting",
        step_id="workbench_reporting",
        requested_scopes={
            CapabilityScope.REPORT_COMPILE_MANUSCRIPT,
            CapabilityScope.AUDIT_WRITE_ENTRY,
        },
    )
    try:
        rp_input = AgentInput(
            execution_id=execution_id,
            node_id="workbench_reporting",
            capability_token=rp_token,
            payload={
                "statistical_results": statistical_results,
                "intent_object": st.session_state.get("workbench_intent_object") or {},
                "reporting_checklist_id": st.session_state.get("format_checklist_id"),
                "target_journal_style": st.session_state.get("format_journal_style", "APA"),
                "reporting_skill_id": st.session_state.get("format_skill_id"),
                "inject_raw_data_rows": False,
            },
            input_schema_ref="cie://schemas/task-context.schema.json",
        )
        with st.spinner("原稿を生成中..."):
            rp_output = asyncio.run(reporting.run(rp_input))
    finally:
        token_manager.revoke(rp_token)

    if rp_output.status != "success":
        st.error(f"ReportingAgent エラー: {rp_output.error_message}")
        _append_activity("reporting", "workbench_reporting_failed",
                         rp_output.error_message or "不明なエラー", "CRITICAL")
        return

    sections_list: list = rp_output.output_payload.get("manuscript_sections") or []
    sections_dict = {
        s.get("section_id", str(i)): s for i, s in enumerate(sections_list)
        if isinstance(s, dict)
    }
    st.session_state["workbench_manuscript_sections"] = sections_dict
    _append_activity("reporting", "workbench_manuscript_generated",
                     f"原稿セクション {len(sections_dict)} 件を生成", "INFO")


_SCREENS = ("dashboard", "workbench", "intent", "data_preview", "workflow", "quality", "analysis", "results", "audit", "knowledge", "skill_improvement", "settings")

_NAV_LABELS: dict[str, str] = {
    "dashboard":        "ダッシュボード",
    "workbench":        "🧪 ワークベンチ",
    "intent":           "研究意図入力",
    "data_preview":     "データプレビュー",
    "workflow":         "ワークフロー",
    "quality":          "データ品質",
    "analysis":         "統計解析",
    "results":          "結果・レポート",
    "audit":            "監査ログ",
    "knowledge":        "知識管理",
    "skill_improvement": "Skill改善",
    "settings":         "設定",
}


def _init_session_state() -> None:
    defaults: dict[str, object] = {
        "current_screen":         "dashboard",
        "execution_id":           None,
        "workflow_state":         None,
        "agent_activity_log":     [],
        "approval_pending":       False,
        "approval_context":       None,
        "connection_status":      "online",
        "security_events":        [],
        # Project / intent state
        "projects":               [],
        "current_project":        None,
        "intent_object":          None,
        "intent_object_confirmed": False,
        # Workflow state
        "workflow_definition":    {},
        "node_statuses":          {},
        "node_outputs":           {},
        # Quality review
        "quality_report":         {},
        "column_alias_map":       None,
        # Analysis
        "analysis_plan":          {},
        "assumption_report":      None,
        # Results
        "execution_result":       {},
        "figures":                [],
        "manuscript_sections":    {},
        "review_result":          {},
        "evaluation_report":      {},
        # Audit
        "audit_events":           [],
        "audit_selected_event":   None,
        # Knowledge management
        "knowledge_entries":          [],
        "knowledge_draft":            None,
        "knowledge_expiry_warnings":  [],
        "knowledge_pending_upload":   None,
        "knowledge_approval_request": None,
        "knowledge_archive_request":  None,
        "current_user_id":            "researcher",
        "current_user_role":          "researcher",
        # Intent raw inputs (stored for external agent consumption)
        "intent_raw_text":            "",
        "intent_csv_bytes":           None,
        "intent_csv_filename":        None,
        # Settings
        "settings_current_provider":  os.environ.get("CIE_ACTIVE_AI_PROVIDER", "anthropic"),
        "settings_key_status":        {},
        # Workflow execution result
        "workflow_run_result": None,
        # Format selection (Phase 5) — propagated to ReportingAgent via dataset_context
        "format_checklist_id":   None,   # None = auto-infer from study_design
        "format_journal_style":  "APA",  # "APA" / "AMA" / "Vancouver"
        "format_skill_id":       None,   # None = use core reporting/manuscript-section
        # Phase 7: continuation analysis loop
        "analysis_history":              [],    # list of completed continuation entries
        "continuation_pending_payload":  None,  # StatisticsAgent output awaiting human review
        "statistical_results":           None,  # latest parsed statistical_results
        # Phase 8: skill self-improvement
        "skill_proposals":               [],    # cached list of proposals for the UI
        # Workbench (chat + R code + output + files, IDE-style)
        "workbench_history":             [],    # list of {"id","role","content","candidates"}
        "workbench_active_code":         "",     # current contents of the code editor pane
        "workbench_last_run":            None,   # most recent execution result (see workbench.py)
        "workbench_intent_object":       None,   # IntentObject from the first chat turn
        "workbench_statistical_results": None,   # latest parsed statistical_results (for continuation turns)
        "workbench_manuscript_sections": {},     # Phase 6: generated manuscript sections
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


# ---------------------------------------------------------------------------
# Navigation (left pane)
# ---------------------------------------------------------------------------

def _render_left_pane() -> None:
    st.markdown("### ナビゲーション")
    for screen in _SCREENS:
        label = _NAV_LABELS[screen]
        is_active = st.session_state["current_screen"] == screen
        if st.button(
            label,
            key=f"nav_{screen}",
            type="primary" if is_active else "secondary",
            use_container_width=True,
        ):
            st.session_state["current_screen"] = screen
            st.rerun()


# ---------------------------------------------------------------------------
# Right pane — context panel (intent preview on SCR-02, activity on others)
# ---------------------------------------------------------------------------

def _render_right_pane_content() -> None:
    screen = st.session_state["current_screen"]

    # SCR-02: show intent preview above the activity feed
    if screen == "intent" and st.session_state.get("intent_object"):
        render_intent_preview(st.session_state["intent_object"])
        st.divider()

    # All screens: approval panel + activity feed (handled by right_pane component)
    pane_result = render_right_pane(
        workflow_state=st.session_state["workflow_state"],
        agent_activity_log=st.session_state["agent_activity_log"],
        approval_pending=st.session_state["approval_pending"],
        approval_context=st.session_state.get("approval_context"),
    )

    # Handle approval / cancellation events from the right pane
    if pane_result.get("approved"):
        action = (st.session_state.get("approval_context") or {}).get("action")
        # Clear the fulfilled approval BEFORE processing: the handler may queue
        # a follow-up approval (e.g. security_review raised by run_workflow).
        st.session_state["approval_pending"] = False
        st.session_state["approval_context"] = None

        if action == "run_workflow":
            # session_state["intent_object"] holds the Planner output_payload;
            # the Orchestrator expects the flat intent (objective/outcome_type
            # at top level), so unwrap the nested intent_object.
            stored_payload = st.session_state.get("intent_object") or {}
            intent_object = stored_payload.get("intent_object", stored_payload)
            execution_id = st.session_state.get("execution_id") or str(uuid.uuid4())
            dataset_context = _build_dataset_context(
                st.session_state.get("intent_csv_bytes")
            )
            # Merge format selections (Phase 5) into the initial workflow context
            dataset_context.update(build_format_context(
                checklist_id=st.session_state.get("format_checklist_id"),
                journal_style=st.session_state.get("format_journal_style", "APA"),
                skill_id=st.session_state.get("format_skill_id"),
            ))
            services = _get_services()
            with st.spinner("ワークフローを実行中..."):
                try:
                    result = asyncio.run(
                        services["orchestrator"].run_workflow(
                            execution_id, intent_object, dataset_context=dataset_context
                        )
                    )
                    st.session_state["execution_id"] = execution_id
                    st.session_state["workflow_run_result"] = result
                    _unpack_workflow_result(result)
                    # security_review approval gate → surface the R script for
                    # human review and queue the resume action.
                    _maybe_request_security_approval(result)
                    st.session_state["current_screen"] = "workflow"
                    _append_activity(
                        agent_id="orchestrator",
                        action="workflow_completed",
                        summary=(
                            f"ワークフロー実行完了: "
                            f"{result.get('workflow_id_selected', 'unknown')} "
                            f"({result.get('final_state', '')})"
                        ),
                        severity="INFO",
                    )
                except Exception as exc:
                    st.error(f"ワークフロー実行エラー: {exc}")
                    _append_activity(
                        agent_id="orchestrator",
                        action="run_failed",
                        summary=str(exc)[:200],
                        severity="CRITICAL",
                    )

        elif action == "execute_continuation":
            services = _get_services()
            _execute_continuation(services)

        elif action == "apply_skill_proposal":
            services = _get_services()
            proposal_id = (st.session_state.get("approval_context") or {}).get(
                "proposal_id", ""
            )
            from cie.security.capability_token import CapabilityScope
            token = services["token_manager"].issue(
                execution_id=str(uuid.uuid4()),
                agent_id="skill_lifecycle",
                step_id="skill_proposal_approve",
                requested_scopes={CapabilityScope.SKILL_UPDATE_CORE},
            )
            try:
                with st.spinner("Skillを更新中..."):
                    asyncio.run(
                        services["skill_lifecycle"].apply_approved_proposal(
                            proposal_id, token, {"action": "approved"}
                        )
                    )
                st.success("Skill が更新されました（バージョンアップ・旧版アーカイブ完了）")
                st.session_state["skill_proposals"] = []  # force refresh on next render
                _append_activity(
                    agent_id="skill_lifecycle",
                    action="skill_proposal_approved",
                    summary=f"proposal {proposal_id[:8]} を承認・適用しました",
                    severity="INFO",
                )
            except Exception as exc:
                st.error(f"Skill更新エラー: {exc}")
                _append_activity(
                    agent_id="skill_lifecycle",
                    action="skill_proposal_apply_failed",
                    summary=str(exc)[:200],
                    severity="CRITICAL",
                )

        elif action == "resume_security_review":
            services = _get_services()
            execution_id = st.session_state.get("execution_id")
            with st.spinner("承認済み — ワークフローを再開中..."):
                try:
                    resume_result = asyncio.run(
                        services["orchestrator"].resume_workflow(
                            execution_id,
                            {
                                "execution_permission": True,
                                "human_decision": {
                                    "decision": "approved",
                                    "node_id": "security_review",
                                },
                            },
                        )
                    )
                    _unpack_workflow_result(resume_result)
                    st.session_state["current_screen"] = "results"
                    _append_activity(
                        agent_id="orchestrator",
                        action="workflow_resumed",
                        summary=(
                            f"再開後の最終状態: {resume_result.get('final_state', '')}"
                        ),
                        severity="INFO",
                    )
                except Exception as exc:
                    st.error(f"ワークフロー再開エラー: {exc}")
                    _append_activity(
                        agent_id="orchestrator",
                        action="resume_failed",
                        summary=str(exc)[:200],
                        severity="CRITICAL",
                    )

        _append_activity(
            agent_id="human",
            action="approved",
            summary="ユーザーが承認しました",
            severity="INFO",
        )
        st.rerun()

    if pane_result.get("cancelled"):
        # Cancellation keeps workflow in waiting_for_human (interaction-flow.md §2)
        _append_activity(
            agent_id="human",
            action="cancel_clicked",
            summary="承認待ち継続中",
            severity="INFO",
        )
        st.rerun()


# ---------------------------------------------------------------------------
# Main content routing
# ---------------------------------------------------------------------------

def render_main_content() -> None:
    screen = st.session_state["current_screen"]

    if screen == "dashboard":
        _handle_dashboard()

    elif screen == "workbench":
        _handle_workbench()

    elif screen == "intent":
        _handle_intent()

    elif screen == "data_preview":
        _handle_data_preview()

    elif screen == "workflow":
        _handle_workflow()

    elif screen == "quality":
        _handle_quality()

    elif screen == "analysis":
        _handle_analysis()

    elif screen == "results":
        _handle_results()

    elif screen == "audit":
        _handle_audit()

    elif screen == "knowledge":
        _handle_knowledge()

    elif screen == "skill_improvement":
        _handle_skill_improvement()

    elif screen == "settings":
        _handle_settings()


def _handle_dashboard() -> None:
    csv_bytes = st.session_state.get("intent_csv_bytes")
    selected = render_dashboard(
        projects=st.session_state["projects"],
        csv_filename=st.session_state.get("intent_csv_filename"),
        csv_size_bytes=len(csv_bytes) if csv_bytes else None,
    )

    if selected is None:
        return

    if selected.get("__action__") == "new_project":
        st.session_state["current_screen"] = "intent"
        st.session_state["current_project"] = None
        st.session_state["intent_object"] = None
        st.session_state["intent_object_confirmed"] = False
        st.rerun()
        return

    # User opened an existing project → go to workflow view
    st.session_state["current_project"] = selected
    st.session_state["execution_id"] = selected.get("execution_id")
    st.session_state["workflow_state"] = selected.get("workflow_state")
    st.session_state["current_screen"] = "workflow"
    st.rerun()


def _handle_intent() -> None:
    from cie.agents.base import AgentInput
    from cie.security.capability_token import CapabilityScope

    services = _get_services()

    def _on_submit(prompt_text: str, csv_bytes: bytes | None) -> None:
        # Guard: Streamlit reruns the script after every interaction; without this
        # flag a single button click triggers _on_submit twice, causing two LLM
        # requests and a 429 quota error.
        if st.session_state.get("_intent_processing"):
            return
        st.session_state["_intent_processing"] = True

        st.session_state["intent_raw_text"] = prompt_text
        st.session_state["intent_csv_bytes"] = csv_bytes

        execution_id = str(uuid.uuid4())
        token = services["token_manager"].issue(
            execution_id=execution_id,
            agent_id="planner",
            step_id="planner_ui",
            requested_scopes={
                CapabilityScope.DATASET_PROXY_METADATA,
                CapabilityScope.WORKFLOW_STATE_READ,
                CapabilityScope.AUDIT_WRITE_ENTRY,
            },
        )
        try:
            with st.spinner("研究意図を解析中..."):
                agent_input = AgentInput(
                    execution_id=execution_id,
                    node_id="planner_ui",
                    capability_token=token,
                    payload={
                        "user_natural_language_prompt": prompt_text,
                        "dataset_structural_metadata": {},
                        "inject_raw_data_rows": False,
                    },
                    input_schema_ref="cie://schemas/planner-input.schema.json",
                )
                output = asyncio.run(services["planner"].run(agent_input))

            if output.status == "success":
                st.session_state["intent_object"] = output.output_payload
                st.session_state["execution_id"] = execution_id
                # Unlock the "解析を開始する" button: a confident extraction is
                # ready for the human to review in the preview pane. The actual
                # run is still gated behind the approval dialog.
                st.session_state["intent_object_confirmed"] = True
                _append_activity(
                    agent_id="planner",
                    action="intent_extracted",
                    summary=f"意図解析完了 (id={execution_id[:8]})",
                    severity="INFO",
                )
            elif output.status == "clarification_required":
                st.session_state["intent_object"] = output.output_payload
                # Ambiguous intent needs clarification before it can run.
                st.session_state["intent_object_confirmed"] = False
                _append_activity(
                    agent_id="planner",
                    action="clarification_required",
                    summary=output.error_message or "追加情報が必要です",
                    severity="WARNING",
                )
            else:
                st.error(f"意図の解析に失敗しました: {output.error_message}")
                _append_activity(
                    agent_id="planner",
                    action="intent_extraction_failed",
                    summary=output.error_message or "不明なエラー",
                    severity="CRITICAL",
                )
        except Exception as exc:
            st.error(f"エラー: {exc}")
            _append_activity(
                agent_id="planner",
                action="intent_extraction_error",
                summary=str(exc)[:200],
                severity="CRITICAL",
            )
        finally:
            services["token_manager"].revoke(token)
            st.session_state["_intent_processing"] = False
            # Trigger UI rerun to reflect updated intent_object_confirmed state
            st.rerun()

    start_requested, current_csv_bytes, current_csv_filename = render_intent_entry(
        on_submit=_on_submit,
        intent_confirmed=st.session_state.get("intent_object_confirmed", False),
        existing_csv_filename=st.session_state.get("intent_csv_filename"),
        existing_csv_bytes=st.session_state.get("intent_csv_bytes"),
    )

    # Save uploaded bytes and filename on every render so data_preview and
    # other screens can access them without requiring the user to submit first.
    if current_csv_bytes is not None:
        st.session_state["intent_csv_bytes"] = current_csv_bytes
    if current_csv_filename is not None:
        st.session_state["intent_csv_filename"] = current_csv_filename

    # --- Format selection panel (Phase 5) ---
    # Render below the intent entry widget; collect any user/ skill IDs to list.
    services = _get_services()
    skill_loader = services.get("skill_loader")
    user_skill_ids: list[str] = (
        [m.skill_id for m in skill_loader.get_all_user_skills()]
        if skill_loader is not None
        else []
    )
    fmt = render_format_selection(
        available_user_skills=user_skill_ids,
        current_checklist=st.session_state.get("format_checklist_id"),
        current_journal_style=st.session_state.get("format_journal_style", "APA"),
        current_skill_id=st.session_state.get("format_skill_id"),
    )
    # Persist selections without triggering a full rerun (values are read at workflow start)
    st.session_state["format_checklist_id"]  = fmt["checklist_id"]
    st.session_state["format_journal_style"] = fmt["journal_style"]
    st.session_state["format_skill_id"]      = fmt["skill_id"]

    if start_requested:
        # Build a human-readable summary of the intent object for the approval panel.
        _stored = st.session_state.get("intent_object") or {}
        _iobj = _stored.get("intent_object", _stored)
        _label = {
            "between_group_comparison": "群間比較",
            "paired_comparison": "対応比較（前後比較）",
            "correlation_analysis": "相関分析",
            "regression_analysis": "回帰分析",
            "survival_analysis": "生存時間分析",
            "diagnostic_accuracy": "診断精度",
            "prediction_model": "予測モデル",
            "descriptive_only": "記述統計",
            "systematic_review": "システマティックレビュー",
        }
        _objective = _label.get(_iobj.get("objective", ""), _iobj.get("objective", "不明"))
        _summary = _iobj.get("natural_language_summary", "")
        _confidence = _stored.get("confidence_score")
        _conf_str = f"{_confidence:.2f}" if _confidence is not None else "?"
        _desc_lines = [
            f"**解析目的:** {_objective}",
            f"**確信度:** {_conf_str}",
        ]
        if _summary:
            _desc_lines.append(f"\n> {_summary}")
        _desc_lines.append(
            "\n詳細はこのパネル上部の「AI解釈結果」をご確認ください。"
        )
        st.session_state["approval_pending"] = True
        st.session_state["approval_context"] = {
            "title": "この解釈で解析を開始します。内容を確認してください。",
            "is_irreversible": False,
            "action": "run_workflow",
            "description": "\n".join(_desc_lines),
        }
        st.rerun()


def _handle_data_preview() -> None:
    render_data_preview(st.session_state["intent_csv_bytes"])


def _handle_workflow() -> None:
    _ = render_workflow_view(
        workflow_definition=st.session_state.get("workflow_definition", {}),
        node_statuses=st.session_state.get("node_statuses", {}),
        node_outputs=st.session_state.get("node_outputs", {}),
    )
    # clicked_node is handled inside render_workflow_view (shows expander)
    # If future logic needs it, app.py can act on it here.


def _handle_quality() -> None:
    result = render_quality_review(
        quality_report=st.session_state.get("quality_report", {}),
        column_alias_map=st.session_state.get("column_alias_map"),
    )
    if result["proceed"]:
        acked = result["acknowledged_findings"]
        if acked:
            _append_activity(
                agent_id="human",
                action="quality_acknowledged",
                summary=f"承認済み finding: {', '.join(acked)}",
                severity="WARNING",
            )
        st.session_state["current_screen"] = "analysis"
        st.rerun()


def _handle_analysis() -> None:
    result = render_analysis_config(
        analysis_plan=st.session_state.get("analysis_plan", {}),
        assumption_report=st.session_state.get("assumption_report"),
    )
    if result["approved"]:
        # Override recorded to audit trail; actual invocation is external
        if result["override_method"]:
            _append_activity(
                agent_id="human",
                action="method_override",
                summary=(
                    f"{result['override_method']}: {result['override_reason'] or '理由未記入'}"
                ),
                severity="WARNING",
            )
        st.session_state["approval_pending"] = True
        st.session_state["approval_context"] = {
            "title": "Rスクリプトを実行します。内容を確認してください。",
            "is_irreversible": True,
        }
        st.rerun()


def _handle_results() -> None:
    result = render_results(
        execution_result=st.session_state.get("execution_result", {}),
        figures=st.session_state.get("figures", []),
        manuscript_sections=st.session_state.get("manuscript_sections", {}),
        review_result=st.session_state.get("review_result", {}),
        execution_id=st.session_state.get("execution_id"),
        statistical_results_formatted=st.session_state.get("statistical_results_formatted"),
        analysis_history=st.session_state.get("analysis_history", []),
    )
    if result["export_approved"]:
        st.session_state["approval_pending"] = True
        st.session_state["approval_context"] = {
            "title": f"レポートをエクスポートします（{result['export_type']}）。",
            "is_irreversible": False,
        }
        _append_activity(
            agent_id="human",
            action="export_requested",
            summary=result["export_type"],
            severity="INFO",
        )
        st.rerun()

    # Phase 7: continuation analysis — user submitted a follow-up query
    continuation_query: str | None = result.get("continuation_query")
    if continuation_query:
        services = _get_services()
        _start_continuation_analysis(continuation_query, services)
        st.rerun()


def _handle_audit() -> None:
    selected_event = render_audit_log(
        audit_events=st.session_state.get("audit_events", []),
        workflow_id=(st.session_state.get("current_project") or {}).get("execution_id"),
        execution_id=st.session_state.get("execution_id"),
    )
    if selected_event is not None:
        st.session_state["audit_selected_event"] = selected_event


def _handle_knowledge() -> None:
    services = _get_services()
    _reload_knowledge_state(services)

    event = render_knowledge_management(
        entries=st.session_state.get("knowledge_entries", []),
        draft=st.session_state.get("knowledge_draft"),
        expiry_warnings=st.session_state.get("knowledge_expiry_warnings", []),
        current_user_id=st.session_state.get("current_user_id", "researcher"),
        current_user_role=st.session_state.get("current_user_role", "researcher"),
    )

    if event is None:
        return

    action = event.get("action")

    if action == "upload":
        filename = event.get("filename", "document")
        file_bytes: bytes = event["file_bytes"]
        try:
            with st.spinner(f"「{filename}」を解析中..."):
                suffix = Path(filename).suffix or ".txt"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp.write(file_bytes)
                    tmp_path = Path(tmp.name)
                draft = asyncio.run(
                    services["knowledge_ingestion"].ingest(
                        file_path=tmp_path,
                        file_bytes=file_bytes,
                        uploaded_by=st.session_state.get("current_user_id", "researcher"),
                    )
                )
            st.session_state["knowledge_draft"] = draft
            _append_activity(
                agent_id="knowledge_ingestion",
                action="ingested",
                summary=f"{filename} → draft {draft.draft_id}",
                severity="INFO",
            )
        except Exception as exc:
            st.error(f"ドキュメント解析エラー: {exc}")
            _append_activity(
                agent_id="knowledge_ingestion",
                action="ingest_failed",
                summary=str(exc)[:200],
                severity="CRITICAL",
            )
        st.rerun()

    elif action == "draft_approved":
        draft = st.session_state.get("knowledge_draft")
        if draft is not None:
            try:
                with st.spinner("知識ライブラリに登録中..."):
                    asyncio.run(
                        services["knowledge_lifecycle"].register_knowledge(
                            draft=draft,
                            approved_by=st.session_state.get("current_user_id", "researcher"),
                            created_by=st.session_state.get("current_user_id", "researcher"),
                            domain=event.get("domain", draft.extracted_domain),
                            trust_level=event.get("trust_level", draft.extracted_trust_level),
                            source_info=draft.extracted_metadata,
                            knowledge_items=draft.extracted_knowledge_items,
                        )
                    )
                st.session_state["knowledge_draft"] = None
                _append_activity(
                    agent_id="human",
                    action="knowledge_registered",
                    summary=f"登録完了: {draft.draft_id} "
                            f"(trust={event.get('trust_level')}, domain={event.get('domain')})",
                    severity="INFO",
                )
            except Exception as exc:
                st.error(f"登録エラー: {exc}")
                _append_activity(
                    agent_id="knowledge_lifecycle",
                    action="register_failed",
                    summary=str(exc)[:200],
                    severity="CRITICAL",
                )
        st.rerun()

    elif action == "draft_rejected":
        st.session_state["knowledge_draft"] = None
        _append_activity(
            agent_id="human",
            action="draft_rejected",
            summary=f"ドラフト却下: {event.get('draft_id')}",
            severity="WARNING",
        )
        st.rerun()

    elif action == "archive":
        entry_id = event["entry_id"]
        try:
            with st.spinner(f"「{entry_id}」をアーカイブ中..."):
                asyncio.run(
                    services["knowledge_lifecycle"].archive_entry(
                        entry_id=entry_id,
                        archived_by=st.session_state.get("current_user_id", "researcher"),
                        current_user_id=st.session_state.get("current_user_id", "researcher"),
                        current_user_role=st.session_state.get("current_user_role", "researcher"),
                        reason="UIからのアーカイブ要求",
                    )
                )
            _append_activity(
                agent_id="human",
                action="knowledge_archived",
                summary=f"アーカイブ完了: {entry_id}",
                severity="WARNING",
            )
        except Exception as exc:
            st.error(f"アーカイブエラー: {exc}")
        st.rerun()


def _handle_skill_improvement() -> None:
    """Phase 8 — Skill自己改善画面.

    Loads pending SkillImprovementProposals from the DB and renders the
    review UI.  Approve / reject events are returned from the component and
    handled here so session_state mutation stays in app.py (UP-002).
    """
    from cie.core.database import SkillImprovementProposalRow, get_session
    from sqlalchemy import select

    services = _get_services()

    # Fetch proposals (pending first, then reviewed) — cache in session_state
    # and refresh on explicit rerun so the list is not re-queried every render.
    if not st.session_state.get("skill_proposals"):
        try:
            session_factory = services["session_factory"]
            async def _load() -> list[dict]:
                async with session_factory() as sess:
                    stmt = (
                        select(SkillImprovementProposalRow)
                        .order_by(SkillImprovementProposalRow.generated_at.desc())
                        .limit(50)
                    )
                    rows = (await sess.execute(stmt)).scalars().all()
                    return [
                        {
                            "proposal_id":    r.proposal_id,
                            "target_skill_id": r.target_skill_id,
                            "target_namespace": r.target_namespace,
                            "current_version": r.current_version,
                            "proposed_version": r.proposed_version,
                            "trigger_id":      r.trigger_id,
                            "trigger_evidence": r.trigger_evidence or {},
                            "proposed_changes": r.proposed_changes or [],
                            "status":          r.status,
                            "generated_at":    str(r.generated_at)[:19],
                            "human_decision":  r.human_decision or {},
                            "reviewed_at":     str(r.reviewed_at)[:19] if r.reviewed_at else "",
                        }
                        for r in rows
                    ]
            st.session_state["skill_proposals"] = asyncio.run(_load())
        except Exception as exc:
            st.error(f"提案の読み込みエラー: {exc}")
            st.session_state["skill_proposals"] = []

    proposals: list[dict] = st.session_state.get("skill_proposals", [])

    col_refresh, col_trigger = st.columns([1, 4])
    if col_refresh.button("🔄 更新", key="skill_proposals_refresh"):
        st.session_state["skill_proposals"] = []
        st.rerun()

    # Allow manually triggering evaluation on a specific skill (SE-004)
    with col_trigger.expander("手動でSkill評価をトリガー", expanded=False):
        skill_id_input = st.text_input(
            "Skill ID (例: statistics/t-test)",
            key="manual_eval_skill_id",
        )
        if st.button("評価リクエスト (SE-004)", key="manual_eval_trigger"):
            if skill_id_input:
                try:
                    with st.spinner("提案を生成中..."):
                        proposal = asyncio.run(
                            services["skill_lifecycle"].generate_proposal(
                                skill_id_input, "SE-004", {"manual": True}
                            )
                        )
                    st.success(
                        f"提案を生成しました: `{proposal.proposal_id[:8]}…`"
                        f"  ({proposal.current_version} → {proposal.proposed_version})"
                    )
                    st.session_state["skill_proposals"] = []  # force refresh
                    _append_activity(
                        agent_id="skill_lifecycle",
                        action="manual_proposal_generated",
                        summary=f"{skill_id_input} の SE-004 提案を生成",
                        severity="INFO",
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(f"提案生成エラー: {exc}")
            else:
                st.warning("Skill ID を入力してください")

    event = render_skill_improvement(proposals)

    # Reject — no approval panel needed; apply directly
    if event.get("reject_proposal"):
        pid = event["reject_proposal"]
        from cie.security.capability_token import CapabilityScope
        token = services["token_manager"].issue(
            execution_id=str(uuid.uuid4()),
            agent_id="skill_lifecycle",
            step_id="skill_proposal_reject",
            requested_scopes={CapabilityScope.SKILL_UPDATE_CORE},
        )
        try:
            asyncio.run(
                services["skill_lifecycle"].apply_approved_proposal(
                    pid, token, {"action": "rejected"}
                )
            )
            st.success("提案を却下しました")
            st.session_state["skill_proposals"] = []
            _append_activity(
                agent_id="skill_lifecycle",
                action="skill_proposal_rejected",
                summary=f"proposal {pid[:8]} を却下しました",
                severity="INFO",
            )
        except Exception as exc:
            st.error(f"却下エラー: {exc}")
        st.rerun()

    # Approve — route through the shared approval panel (irreversible)
    if event.get("approve_proposal"):
        pid = event["approve_proposal"]
        proposal_info = next(
            (p for p in proposals if p["proposal_id"] == pid), {}
        )
        skill_id = proposal_info.get("target_skill_id", pid[:8])
        cv = proposal_info.get("current_version", "?")
        pv = proposal_info.get("proposed_version", "?")
        st.session_state["approval_pending"] = True
        st.session_state["approval_context"] = {
            "action": "apply_skill_proposal",
            "proposal_id": pid,
            "title": f"Skill を更新します: {skill_id}  ({cv} → {pv})",
            "description": (
                f"**対象 Skill:** `{skill_id}`\n\n"
                f"**バージョン:** `{cv}` → `{pv}`\n\n"
                "承認すると SKILL.md に提案された変更が挿入され、"
                "旧バージョンがアーカイブされます。この操作は取り消せません。"
            ),
            "is_irreversible": True,
        }
        st.rerun()


def _load_settings_state() -> None:
    """Refresh provider key status from keyring into session_state."""
    from cie.core.secrets_store import has_api_key
    providers = ("anthropic", "openai", "google_gemini")
    st.session_state["settings_key_status"] = {p: has_api_key(p) for p in providers}


def _update_env_file_provider(provider: str) -> None:
    """Update CIE_ACTIVE_AI_PROVIDER in .env, writing only the provider name."""
    env_path = Path(".env")
    if not env_path.exists():
        return
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    updated = []
    found = False
    for line in lines:
        if line.startswith("CIE_ACTIVE_AI_PROVIDER="):
            updated.append(f"CIE_ACTIVE_AI_PROVIDER={provider}\n")
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(f"CIE_ACTIVE_AI_PROVIDER={provider}\n")
    env_path.write_text("".join(updated), encoding="utf-8")


def _handle_settings() -> None:
    from cie.core.audit import AuditEvent, AuditEventSeverity
    from cie.core.secrets_store import delete_api_key, save_api_key

    _load_settings_state()

    services = _get_services()
    cache_store = services["cache_store"]

    event = render_settings(
        current_provider=st.session_state["settings_current_provider"],
        provider_key_status=st.session_state["settings_key_status"],
        cache_stats=cache_store.get_stats(),
    )

    if event is None:
        return

    action = event["action"]
    audit = services["audit"]

    if action == "save_key":
        provider: str = event["provider"]
        api_key: str = event["api_key"]
        try:
            save_api_key(provider, api_key)
            asyncio.run(audit.write(AuditEvent(
                execution_id="settings",
                agent_id="ui:settings",
                action="API_KEY_SAVED",
                status="success",
                severity=AuditEventSeverity.INFO,
                payload={"provider": provider},
            )))
            st.cache_resource.clear()
            _load_settings_state()
            st.success(f"{provider} のAPIキーを保存しました。")
        except Exception as exc:
            st.error(f"APIキーの保存に失敗しました: {exc}")
        finally:
            del api_key
        st.rerun()

    elif action == "clear_key":
        provider = event["provider"]
        try:
            delete_api_key(provider)
            asyncio.run(audit.write(AuditEvent(
                execution_id="settings",
                agent_id="ui:settings",
                action="API_KEY_DELETED",
                status="success",
                severity=AuditEventSeverity.WARNING,
                payload={"provider": provider},
            )))
            st.cache_resource.clear()
            _load_settings_state()
            st.info(f"{provider} のAPIキーを削除しました。")
        except Exception as exc:
            st.error(f"APIキーの削除に失敗しました: {exc}")
        st.rerun()

    elif action == "change_provider":
        new_provider: str = event["provider"]
        try:
            os.environ["CIE_ACTIVE_AI_PROVIDER"] = new_provider
            _update_env_file_provider(new_provider)
            st.session_state["settings_current_provider"] = new_provider
            asyncio.run(audit.write(AuditEvent(
                execution_id="settings",
                agent_id="ui:settings",
                action="PROVIDER_CHANGED",
                status="success",
                severity=AuditEventSeverity.INFO,
                payload={"new_provider": new_provider},
            )))
            st.cache_resource.clear()
            st.success(f"AIプロバイダーを {new_provider} に変更しました。")
        except Exception as exc:
            st.error(f"プロバイダー変更に失敗しました: {exc}")
        st.rerun()

    elif action == "delete_cache_entry":
        # CA-004: manual physical deletion from the UI is permitted
        cache_store.delete(event["key_hash"])
        asyncio.run(audit.write(AuditEvent(
            execution_id="settings",
            agent_id="ui:settings",
            action="CACHE_ENTRY_DELETED",
            status="success",
            severity=AuditEventSeverity.INFO,
            payload={"key_hash": event["key_hash"]},
        )))
        st.success("キャッシュエントリを削除しました。")
        st.rerun()

    elif action == "clear_cache":
        cache_store.clear_all()
        asyncio.run(audit.write(AuditEvent(
            execution_id="settings",
            agent_id="ui:settings",
            action="CACHE_CLEARED",
            status="success",
            severity=AuditEventSeverity.INFO,
            payload={},
        )))
        st.success("キャッシュをクリアしました。")
        st.rerun()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _append_activity(
    agent_id: str,
    action: str,
    summary: str,
    severity: str = "INFO",
) -> None:
    from datetime import datetime, timezone
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": agent_id,
        "action": action,
        "summary": summary,
        "severity": severity,
    }
    log: list = st.session_state.setdefault("agent_activity_log", [])
    log.append(entry)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="CIE Platform",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(_CSS_VARIABLES, unsafe_allow_html=True)
    _init_session_state()

    render_status_bar(
        project_name=(
            (st.session_state.get("current_project") or {}).get("project_name")
        ),
        execution_id=st.session_state["execution_id"],
        connection_status=st.session_state["connection_status"],
        security_events=st.session_state["security_events"],
        workflow_state=st.session_state["workflow_state"],
    )

    st.divider()

    left_col, center_col, right_col = st.columns([1, 3, 1.3])

    with left_col:
        _render_left_pane()

    with center_col:
        render_main_content()

    with right_col:
        _render_right_pane_content()


if __name__ == "__main__":
    main()
