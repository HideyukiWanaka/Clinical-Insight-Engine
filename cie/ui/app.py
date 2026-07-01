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
from cie.ui.screens.results import render_results
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
    from cie.agents.planner import PlannerAgent
    from cie.agents.reporting import ReportingAgent
    from cie.agents.reviewer import ReviewerAgent
    from cie.agents.statistics import StatisticsAgent
    from cie.agents.visualization import VisualizationAgent
    from cie.core.audit import AuditService
    from cie.core.config import CIEConfig
    from cie.core.database import get_engine, get_session, init_db
    from cie.core.llm_client import llm_client_from_env
    from cie.knowledge.ingestion_agent import KnowledgeIngestionAgent
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

    # Agents
    planner = PlannerAgent(policy_engine, schema_registry, audit, context_guard, llm_client)

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
    statistics    = StatisticsAgent(policy_engine, schema_registry, audit)
    visualization = VisualizationAgent(policy_engine, schema_registry, audit)
    reporting     = ReportingAgent(policy_engine, schema_registry, audit)
    reviewer      = ReviewerAgent(policy_engine, schema_registry, audit)

    agent_registry = {
        "data-quality": data_quality,
        "statistics":   statistics,
        "visualization": visualization,
        "reporting":    reporting,
        "reviewer":     reviewer,
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

    return {
        "token_manager": token_manager,
        "audit": audit,
        "planner": planner,
        "knowledge_ingestion": knowledge_ingestion,
        "knowledge_lifecycle": knowledge_lifecycle,
        "knowledge_loader": knowledge_loader,
        "orchestrator": orchestrator,
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
    node_results: list[dict] = result.get("node_results", [])
    node_statuses: dict = {}
    node_outputs: dict = {}
    for nr in node_results:
        nid = nr.get("node_id", "")
        node_statuses[nid] = nr.get("status", "unknown")
        node_outputs[nid] = nr.get("output_payload", {})
        agent = nr.get("agent_id", "")
        if agent == "data-quality":
            st.session_state["quality_report"] = nr.get("output_payload", {})
        elif agent == "statistics":
            st.session_state["analysis_plan"] = nr.get("output_payload", {})
        elif agent == "reviewer":
            st.session_state["review_result"] = nr.get("output_payload", {})
    st.session_state["node_statuses"] = node_statuses
    st.session_state["node_outputs"] = node_outputs
    st.session_state["workflow_definition"] = {
        "workflow_id": result.get("workflow_id_selected"),
        "rule_id": result.get("rule_id"),
        "justification": result.get("justification"),
    }


_SCREENS = ("dashboard", "intent", "data_preview", "workflow", "quality", "analysis", "results", "audit", "knowledge", "settings")

_NAV_LABELS: dict[str, str] = {
    "dashboard":    "ダッシュボード",
    "intent":       "研究意図入力",
    "data_preview": "データプレビュー",
    "workflow":     "ワークフロー",
    "quality":   "データ品質",
    "analysis":  "統計解析",
    "results":   "結果・レポート",
    "audit":     "監査ログ",
    "knowledge": "知識管理",
    "settings":  "設定",
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

        if action == "run_workflow":
            intent_object = st.session_state.get("intent_object") or {}
            execution_id = st.session_state.get("execution_id") or str(uuid.uuid4())
            services = _get_services()
            with st.spinner("ワークフローを実行中..."):
                try:
                    result = asyncio.run(
                        services["orchestrator"].run_workflow(execution_id, intent_object)
                    )
                    st.session_state["workflow_run_result"] = result
                    _unpack_workflow_result(result)
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

        st.session_state["approval_pending"] = False
        st.session_state["approval_context"] = None
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
                _append_activity(
                    agent_id="planner",
                    action="intent_extracted",
                    summary=f"意図解析完了 (id={execution_id[:8]})",
                    severity="INFO",
                )
            elif output.status == "clarification_required":
                st.session_state["intent_object"] = output.output_payload
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

    if start_requested:
        st.session_state["approval_pending"] = True
        st.session_state["approval_context"] = {
            "title": "この解釈で解析を開始します。内容を確認してください。",
            "is_irreversible": False,
            "action": "run_workflow",
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

    event = render_settings(
        current_provider=st.session_state["settings_current_provider"],
        provider_key_status=st.session_state["settings_key_status"],
    )

    if event is None:
        return

    action = event["action"]
    services = _get_services()
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
